#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""宿主机键鼠注入代理（Windows，必须跑在交互式会话 session 1）。

事件来源：命名管道 \\\\.\\pipe\\hermit_remote_input
启动方式：
    schtasks /run /tn HermitRemoteInput      # 任务类型：仅在用户登录时运行，session 1

协议（管道内，multiprocessing.connection 自动带长度前缀）：
    {"t":"m","dx":12,"dy":-3}        相对移动
    {"t":"c","b":"l|r|m","d":1|0}    鼠标按键 down/up
    {"t":"w","d":120,"h":0}          滚轮（120 = 一格）
    {"t":"k","vk":65,"d":1|0}        键盘 down/up（vk 为 Windows 虚拟键码）
    {"t":"u","s":"你好"}              直接输入文本（走 UNICODE，绕过键盘布局）
    {"t":"release"}                  释放所有按下的键和鼠标键
"""
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from multiprocessing.connection import Listener

PIPE_NAME = r"\\.\pipe\hermit_remote_input"
AUTHKEY = os.environ.get("REMOTE_PIPE_TOKEN", "hermit-remote-input").encode()

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR))


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR))


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD))


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT))


class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT

# 需要用 EXTENDEDKEY 标志的虚拟键（方向键、编辑键、右 Ctrl/Alt、Win 键等）
EXTENDED_VKS = {
    0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28,  # PgUp/PgDn/End/Home/方向键
    0x2C, 0x2D, 0x2E, 0x6F,                          # PrintScreen/Insert/Delete/NumDivide
    0x5B, 0x5C, 0x5D,                                # Win / Menu
    0x90, 0x91,                                      # NumLock / ScrollLock
    0xA3, 0xA5,                                      # 右 Ctrl / 右 Alt
}

pressed_keys = set()
pressed_buttons = set()


def _send(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        err = ctypes.get_last_error()
        if err:
            print(f"[WARN] SendInput {sent}/{n} err={err}", flush=True)


def _mouse(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=INPUT_MOUSE)
    inp.u.mi = MOUSEINPUT(dx=dx, dy=dy, mouseData=data & 0xFFFFFFFF,
                          dwFlags=flags, time=0, dwExtraInfo=0)
    _send(inp)


def _key(vk, down, extended=None):
    if extended is None:
        extended = vk in EXTENDED_VKS
    flags = 0 if down else KEYEVENTF_KEYUP
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    _send(inp)


def _unicode_char(ch):
    code = ord(ch)
    for down in (True, False):
        flags = KEYEVENTF_UNICODE | (0 if down else KEYEVENTF_KEYUP)
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = KEYBDINPUT(wVk=0, wScan=code, dwFlags=flags, time=0, dwExtraInfo=0)
        _send(inp)


def release_all():
    for vk in list(pressed_keys):
        try:
            _key(vk, False)
        except Exception:
            pass
    pressed_keys.clear()
    for b in list(pressed_buttons):
        flags = {"l": MOUSEEVENTF_LEFTUP, "r": MOUSEEVENTF_RIGHTUP,
                 "m": MOUSEEVENTF_MIDDLEUP}.get(b)
        if flags:
            _mouse(flags)
    pressed_buttons.clear()


def handle(ev):
    t = ev.get("t")
    if t == "m":
        dx = int(ev.get("dx", 0))
        dy = int(ev.get("dy", 0))
        if dx or dy:
            _mouse(MOUSEEVENTF_MOVE, dx, dy)
    elif t == "c":
        b = ev.get("b", "l")
        down = bool(ev.get("d"))
        flags = {
            ("l", True): MOUSEEVENTF_LEFTDOWN, ("l", False): MOUSEEVENTF_LEFTUP,
            ("r", True): MOUSEEVENTF_RIGHTDOWN, ("r", False): MOUSEEVENTF_RIGHTUP,
            ("m", True): MOUSEEVENTF_MIDDLEDOWN, ("m", False): MOUSEEVENTF_MIDDLEUP,
        }.get((b, down))
        if flags:
            _mouse(flags)
            if down:
                pressed_buttons.add(b)
            else:
                pressed_buttons.discard(b)
    elif t == "w":
        v = int(ev.get("d", 0))
        h = int(ev.get("h", 0))
        if v:
            _mouse(MOUSEEVENTF_WHEEL, data=v)
        if h:
            _mouse(MOUSEEVENTF_HWHEEL, data=h)
    elif t == "k":
        vk = int(ev.get("vk", 0))
        down = bool(ev.get("d"))
        if not vk:
            return
        _key(vk, down, ev.get("ext"))
        if down:
            pressed_keys.add(vk)
        else:
            pressed_keys.discard(vk)
    elif t == "u":
        for ch in str(ev.get("s", "")):
            _unicode_char(ch)
    elif t == "release":
        release_all()


def serve():
    listener = Listener(PIPE_NAME, authkey=AUTHKEY)
    print(f"[READY] listening on {PIPE_NAME} pid={os.getpid()}", flush=True)
    conn = listener.accept()
    print("[CONN] client connected", flush=True)
    try:
        while True:
            raw = conn.recv_bytes()
            if not raw:
                continue
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                continue
            handle(ev)
    except (EOFError, OSError) as e:
        print(f"[DISC] {e}", flush=True)
    finally:
        release_all()
        try:
            conn.close()
        except Exception:
            pass
        listener.close()
        print("[EXIT] released all keys", flush=True)


if __name__ == "__main__":
    serve()
