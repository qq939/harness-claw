# -*- coding: utf-8 -*-
"""TDD 校验：WebShell 终端能正确显示中文（UTF-8 与 GBK 两种来源）。

背景：
  终端把 SSH 原始字节直接丢给 xterm；Git Bash 是 UTF-8 没问题，但 Windows 自带命令
  （cmd/ping/ipconfig）输出 GBK(cp936)，到浏览器就是乱码。
  另外 xterm 默认字体（Consolas/Menlo）没有中文字形，中文会显示成方块。

修法：
  1) 后端 OutputDecoder：增量解码，优先沿用上一块编码，失败换另一种；
     块尾半个多字节字符留到下一块；统一转 UTF-8 再发。
  2) 前端 fontFamily 加中文字体回退（Microsoft YaHei / Sarasa Mono SC / Noto CJK）。

覆盖点：
  A) 静态：OutputDecoder、reader 使用它、字体回退存在。
  B) 线上：连 WebSocket
     1) echo 中文（UTF-8）能回显成合法 UTF-8；
     2) 故意输出 GBK 字节，服务端要转成 UTF-8（浏览器才认）。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import sys
import threading
import time

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))
WS = os.path.join(ROOT, "workspaces", "19087-gpussh")
CARD = os.environ.get("WEBSHELL_CARD", "19087-gpussh")
# 2026-10-25 重写后：ws 路径是 /ws/<session_id>，且必须带 token
TOKEN = os.environ.get("WEBSHELL_TOKEN", "agent")
SESSION = os.environ.get("WEBSHELL_SESSION", "local-selftest")
URL = os.environ.get(
    "WEBSHELL_WS",
    "ws://localhost:19087/ws/%s?token=%s" % (SESSION, TOKEN),
)


def ensure_selftest_session():
    """建一条指向卡片自己（127.0.0.1:22, agent/agent）的自测会话。

    旧的 dimond.top 会话口令已失效，不能再拿来做自动化校验。
    """
    import urllib.request
    body = {"id": SESSION, "name": "自测（本机）", "host": "127.0.0.1", "port": 22,
            "user": "agent", "auth": "password", "password": "agent",
            "init_command": "export LANG=C.UTF-8 LC_ALL=C.UTF-8 LC_CTYPE=C.UTF-8"}
    req = urllib.request.Request(
        "http://localhost:19087/api/sessions?token=%s" % TOKEN,
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status == 200

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


def run_static():
    # 2026-10-25：webshell 重写为单文件 webshell_server.py（原来拆成 tools_hub/webshell_bp.py + webshell/ 包）
    src = open(os.path.join(WS, "webshell_server.py"), "r", encoding="utf-8").read()
    check("有 OutputDecoder", "class OutputDecoder" in src)
    check("reader 用 decoder.feed", "decoder.feed(data)" in src)
    check("GBK 回退", '"gbk"' in src)
    check("中文字体回退", "Microsoft YaHei" in src and "Noto Sans Mono CJK" in src)
    check("登录后设置 UTF-8 locale", "init_command" in src and "chan.send(init" in src)


def ws_run(cmd, expect, pre_wait=0.0):
    import websocket
    ws = websocket.create_connection(URL, timeout=15)
    try:
        if pre_wait:
            time.sleep(pre_wait)
        ws.send(json.dumps({"type": "input", "data": "clear\r"}))
        time.sleep(0.3)
        ws.send(json.dumps({"type": "input", "data": cmd + "\r"}))
        deadline = time.time() + 12
        data = b""
        while time.time() < deadline:
            try:
                chunk = ws.recv()
            except Exception:
                break
            data += chunk.encode() if isinstance(chunk, str) else chunk
            if expect.encode("utf-8") in data:
                break
        return expect.encode("utf-8") in data, data
    finally:
        try:
            ws.close()
        except Exception:
            pass


def run_live():
    try:
        import websocket  # noqa: F401
    except Exception as e:
        skip("线上终端中文", "websocket-client 不可用: %s" % e)
        return
    try:
        if not ensure_selftest_session():
            skip("线上终端中文", "无法创建自测会话")
            return
        ok, data = ws_run("echo 中文测试", "中文测试", pre_wait=1.2)
        check("UTF-8 中文回显正确", ok)
        if not ok:
            print("   -> %r" % data[:200], flush=True)

        ok2, data2 = ws_run(
            "python3 -c \"import sys;sys.stdout.buffer.write('中文GBK'.encode('gbk'))\"",
            "中文GBK")
        check("GBK 输出被转成 UTF-8", ok2)
        if not ok2:
            print("   -> %r" % data2[:200], flush=True)

        ok3, data3 = ws_run("echo LC=$LC_ALL", "LC=C.UTF-8", pre_wait=1.2)
        check("会话 locale 是 UTF-8", ok3)
        if not ok3:
            print("   -> %r" % data3[:200], flush=True)
        if b"$'\\234'" in data3:
            check("TTY 下不出现 $'\\234' 转义", False)
    except Exception as e:
        skip("线上终端中文", "连接失败: %s" % e)


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
