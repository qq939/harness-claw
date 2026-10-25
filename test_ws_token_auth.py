# -*- coding: utf-8 -*-
"""TDD 校验：所有 WebSocket 接口都要 token 鉴权（?token=xxx）。

背景：
  2026-10-22 的入侵是从公网无鉴权的面板进来的：
    /ws/ssh?container=xxx → 面板用写死的 agent/agent 登进任意卡片。
  现在所有 ws 接口都必须带 token（默认 "agent"，可用 HARNESS_WS_TOKEN / WEBSHELL_TOKEN 改）。

覆盖点：
  A) 静态
     1) control 有 ws_token / ws_token_ok，且在 before_request 里拦 /ws；
     2) 面板 SSH 终端页把 token 写进 JS（ws URL 带 token 参数）；
     3) 19087 的 webshell：页面 / REST / WS 都要求 token，且有「＋ 新增配置」按钮。
  B) 线上
     4) 19087：无 token → 401；有 token → 200；WS 无 token → 401（握手阶段就拒）。
     5) 19080：/ws/ssh 无 token / 错 token → 401；有 token → 101 并能真的开出终端。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import base64
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 150
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")
WS_CARD = os.environ.get("WS_CARD", "19087-gpussh")
WS_PORT = int(os.environ.get("WS_CARD_PORT", "19087"))
TOKEN = os.environ.get("HARNESS_WS_TOKEN", "agent")

failures = []
skips = []

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def skip(name, reason):
    print("[SKIP] %s (%s)" % (name, reason), flush=True)
    skips.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def http(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:
        return None, str(e).encode()


def ws_handshake(host, port, path, payload=None, wait=3.0):
    """做一次 WS 握手；返回 (状态行, 收到的文本)。"""
    s = socket.create_connection((host, port), 10)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(("GET %s HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n" % (path, host, port, key)).encode())
    s.settimeout(4)
    try:
        status = s.recv(256).decode("utf-8", "replace").split("\r\n")[0]
    except Exception:
        status = "TIMEOUT"
    buf = b""
    if payload is not None:
        data = json.dumps(payload).encode()
        mask = os.urandom(4)
        head = bytearray([0x81])
        n = len(data)
        if n < 126:
            head.append(0x80 | n)
        else:
            head.append(0x80 | 126)
            head += struct.pack(">H", n)
        head += mask
        head += bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        s.sendall(bytes(head))
        time.sleep(wait)
        try:
            while True:
                d = s.recv(65536)
                if not d:
                    break
                buf += d
        except Exception:
            pass
    s.close()
    return status, buf.decode("utf-8", "replace")


def run_static():
    app = read(os.path.join("control", "app.py"))
    check("control 有 ws_token / ws_token_ok",
          "def ws_token(" in app and "def ws_token_ok(" in app)
    check("control 在 before_request 拦 /ws",
          re.search(r"@app\.before_request[\s\S]{0,400}?path\.startswith\(\"/ws\"\)", app) is not None)
    check("面板 SSH 终端页把 token 写进 JS",
          "const WS_TOKEN = '{ws_token()}'" in app and "ws/ssh?container={container_name}&token=" in app)
    check("compose 设置 HARNESS_WS_TOKEN", "HARNESS_WS_TOKEN" in read(os.path.join("docker-compose.yml")))

    ws_path = os.path.join("workspaces", WS_CARD, "webshell_server.py")
    if not os.path.isfile(ws_path):
        skip("19087 webshell 静态检查", "文件不存在")
        return
    src = read(os.path.join("workspaces", WS_CARD, "webshell_server.py"))
    check("webshell 页面/REST 校验 token", "def _authorized()" in src)
    check("webshell ws 路由要求 token", '@sock.route("/ws/<sid>")' in src)
    check("webshell 有 before_request 拦 /ws",
          re.search(r"@app\.before_request[\s\S]{0,400}?path\.startswith\(\"/ws\"\)", src) is not None)
    check("有「＋ 新增配置」按钮", "＋ 新增配置" in src and "btnAdd" in src)
    check("配置支持新增/编辑/删除", "upsert_session" in src and "delete_session" in src)
    check("token 来自环境变量", "WEBSHELL_TOKEN" in src)


def run_live():
    base = "http://localhost:%d" % WS_PORT
    code, body = http(base + "/")
    check("19087 页面无 token → 401 (%s)" % code, code == 401)
    code, body = http(base + "/?token=" + TOKEN)
    check("19087 页面有 token → 200 (%s)" % code, code == 200)
    if code == 200:
        check("页面含「＋ 新增配置」", "＋ 新增配置" in body.decode("utf-8", "replace"))
    code, _ = http(base + "/api/sessions")
    check("19087 REST 无 token → 401 (%s)" % code, code == 401)
    code, _ = http(base + "/api/sessions?token=" + TOKEN)
    check("19087 REST 有 token → 200 (%s)" % code, code == 200)

    status, _ = ws_handshake("localhost", WS_PORT, "/ws/default")
    check("19087 WS 无 token → 401 (%s)" % status.strip(), "401" in status)
    status, _ = ws_handshake("localhost", WS_PORT, "/ws/default?token=" + TOKEN)
    check("19087 WS 有 token → 101 (%s)" % status.strip(), "101" in status)

    status, _ = ws_handshake("localhost", 19080, "/ws/ssh?container=19081-hub")
    check("面板 WS 无 token → 401 (%s)" % status.strip(), "401" in status)
    status, _ = ws_handshake("localhost", 19080, "/ws/ssh?container=19081-hub&token=bad")
    check("面板 WS 错 token → 401 (%s)" % status.strip(), "401" in status)
    status, out = ws_handshake("localhost", 19080, "/ws/ssh?container=19081-hub&token=" + TOKEN,
                               {"type": "input", "data": "echo HARNESS_WS_TOKEN_OK\r"})
    clean = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", out)
    check("面板 WS 有 token 真能开终端 (%s)" % status.strip(),
          "101" in status and "HARNESS_WS_TOKEN_OK" in clean)


def run():
    try:
        run_static()
        run_live()
    except Exception as e:
        import traceback
        traceback.print_exc()
        check("harness completed without exception (%s)" % e, False)


if __name__ == "__main__":
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(TIMEOUT_SECONDS)
    if t.is_alive():
        print("FAIL: test timed out after %ds" % TIMEOUT_SECONDS, flush=True)
        sys.exit(1)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)), flush=True)
        sys.exit(1)
    print("ALL CHECKS PASSED%s" % (" (%d skipped)" % len(skips) if skips else ""), flush=True)
    sys.exit(0)
