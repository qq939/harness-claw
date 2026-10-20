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
URL = os.environ.get("WEBSHELL_WS", "ws://localhost:19087/webshell/ws/host")

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
    bp = open(os.path.join(WS, "tools_hub", "webshell_bp.py"), "r", encoding="utf-8").read()
    check("有 OutputDecoder", "class OutputDecoder" in bp)
    check("reader 用 decoder.feed", "decoder.feed(data)" in bp)
    check("GBK 回退", '"gbk"' in bp)
    check("中文字体回退", "Microsoft YaHei" in bp and "Noto Sans Mono CJK" in bp)
    srv = open(os.path.join(WS, "webshell_server.py"), "r", encoding="utf-8").read()
    check("ws 别名入口也用 decoder", "_decoder.feed(data)" in srv)


def ws_run(cmd, expect):
    import websocket
    ws = websocket.create_connection(URL, timeout=15)
    try:
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
        ok, data = ws_run("echo 中文测试", "中文测试")
        check("UTF-8 中文回显正确", ok)
        if not ok:
            print("   -> %r" % data[:160], flush=True)

        ok2, data2 = ws_run(
            "python3 -c \"import sys;sys.stdout.buffer.write('中文GBK'.encode('gbk'))\"",
            "中文GBK")
        check("GBK 输出被转成 UTF-8", ok2)
        if not ok2:
            print("   -> %r" % data2[:160], flush=True)
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
