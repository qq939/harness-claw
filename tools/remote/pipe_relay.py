#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SSH 会话里的中继：stdin（来自卡片容器）→ 宿主机命名管道 → 注入代理。

帧格式：4 字节大端长度 + UTF-8 JSON。
退出条件：stdin 关闭（容器断线）或管道断开；退出前关闭连接，代理会自动释放所有按键。
"""
import json
import os
import struct
import sys
import time
from multiprocessing.connection import Client

PIPE_NAME = r"\\.\pipe\hermit_remote_input"
AUTHKEY = os.environ.get("REMOTE_PIPE_TOKEN", "hermit-remote-input").encode()


def connect(retries=40, delay=0.25):
    last = None
    for _ in range(retries):
        try:
            return Client(PIPE_NAME, authkey=AUTHKEY)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(delay)
    raise SystemExit(f"connect pipe failed: {last}")


def main():
    conn = connect()
    out = sys.stdout
    out.write("RELAY_READY\n")
    out.flush()
    stdin = sys.stdin.buffer
    try:
        while True:
            head = stdin.read(4)
            if not head or len(head) < 4:
                break
            (n,) = struct.unpack(">I", head)
            if n <= 0 or n > 1 << 20:
                break
            payload = stdin.read(n)
            if payload is None or len(payload) < n:
                break
            conn.send_bytes(payload)
    except (BrokenPipeError, EOFError, OSError) as e:
        print(f"relay closed: {e}", flush=True)
    finally:
        try:
            conn.send_bytes(json.dumps({"t": "release"}).encode())
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
