# -*- coding: utf-8 -*-
"""TDD 校验：所有 WebSocket 端点都要求 token 鉴权。

覆盖点：
  1) 三个 WS 端点（control /ws/ssh、obs /ws、ssh-gateway）源码里都有 token 校验。
  2) token 统一来自环境变量 WS_TOKEN，未设置时回退默认值。
  3) docker-compose 给三个服务都注入了 WS_TOKEN。
  4) 前端页面（终端页、obs 首页）连接 WS 时带上了 token。
  5) 线上实测：不带 token / 带错 token 一律被拒；带正确 token 才能连上。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import base64
import os
import socket
import struct
import sys
import threading
import time

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))

# 线上实测用的目标
CONTROL_PORT = 18080
OBS_PORT = 18000
GATEWAY_PORT = 18800
# 宿主机上任意一张 claude 卡片的容器名，用于 /ws/ssh 实测
SSH_CONTAINER = os.environ.get("SSH_CONTAINER", "18081-hub")

failures = []
skips = []


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def skip(name, why):
    print("[SKIP] " + name + " (" + why + ")", flush=True)
    skips.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


# --- 最小 WebSocket 客户端（手写握手 + 帧解析，避免引入第三方依赖） ---

def ws_handshake(port, path, host="127.0.0.1", timeout=12):
    """发起 WS 握手，返回 (socket, HTTP 状态行, 已读到的剩余字节)。"""
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        "GET %s HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: %s\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n" % (path, host, port, key)
    )
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    s.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    status = head.split(b"\r\n")[0].decode(errors="replace") if head else ""
    return s, status, rest


def ws_read(s, rest, deadline=5.0, max_frames=6):
    """读取若干帧，返回 [(opcode名, 载荷)]。close 帧的载荷含 close code。"""
    buf = rest
    frames = []
    end = time.time() + deadline
    while len(frames) < max_frames and time.time() < end:
        while True:
            if len(buf) < 2:
                break
            b0, b1 = buf[0], buf[1]
            opcode = b0 & 0x0F
            masked = b1 & 0x80
            length = b1 & 0x7F
            idx = 2
            if length == 126:
                if len(buf) < 4:
                    break
                length = struct.unpack(">H", buf[2:4])[0]
                idx = 4
            elif length == 127:
                if len(buf) < 10:
                    break
                length = struct.unpack(">Q", buf[2:10])[0]
                idx = 10
            if masked:
                if len(buf) < idx + 4:
                    break
                mask = buf[idx:idx + 4]
                idx += 4
            if len(buf) < idx + length:
                break
            payload = buf[idx:idx + length]
            if masked:
                payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
            buf = buf[idx + length:]
            if opcode == 0x8:
                code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else None
                frames.append(("close", code, payload[2:].decode(errors="replace")))
            elif opcode == 0x1:
                frames.append(("text", payload.decode(errors="replace")[:200]))
            else:
                frames.append(("opcode%d" % opcode, "", ""))
        try:
            chunk = s.recv(4096)
        except Exception:
            break
        if not chunk:
            break
        buf += chunk
    return frames


def probe(port, path, read_seconds=4.0):
    """连一次 WS，返回 (http_status, frames)。握手失败时 frames 为空。"""
    try:
        s, status, rest = ws_handshake(port, path)
    except Exception as e:
        return ("EXC:%r" % e), []
    try:
        frames = ws_read(s, rest, deadline=read_seconds)
    finally:
        try:
            s.close()
        except Exception:
            pass
    return status, frames


def close_codes(frames):
    return [f[1] for f in frames if f[0] == "close"]


def text_payloads(frames):
    return [f[1] for f in frames if f[0] == "text"]


def section(text, start_marker, end_marker=None):
    """截取从 start_marker 到 end_marker 之间的片段，用于限定断言范围。"""
    i = text.index(start_marker)
    j = text.index(end_marker, i) if end_marker else len(text)
    return text[i:j]


def run():
    app = read("control/app.py")
    obs = read("tools/obs/server.py")
    gateway = read("agents/ssh-gateway/server.js")
    compose = read("docker-compose.yml")

    # 1) 三个端点都有 token 校验
    check("control /ws/ssh validates token",
          "ws_token_ok" in app and "WS_TOKEN" in app)
    ws_ssh_body = section(app, '@sock.route("/ws/ssh")', "@app.")
    check("control /ws/ssh rejects before opening SSH tunnel",
          ws_ssh_body.index("ws_token_ok(") < ws_ssh_body.index("paramiko.SSHClient"))
    check("obs /ws validates token",
          "ws_token_ok" in obs and "query_params.get(\"token\")" in obs)
    obs_ws_body = section(obs, '@app.websocket("/ws")', "@app.get")
    check("obs /ws rejects before accept",
          obs_ws_body.index("ws_token_ok(") < obs_ws_body.index("await manager.connect(websocket)"))
    check("ssh-gateway validates token",
          "tokenOk" in gateway and "searchParams.get('token')" in gateway)
    gateway_conn = section(gateway, "wss.on('connection'", "server.listen")
    check("ssh-gateway rejects before spawning ssh",
          gateway_conn.index("tokenOk(") < gateway_conn.index("spawn('sshpass'"))

    # 2) token 统一来自环境变量，且有默认值兜底
    check("control reads WS_TOKEN from env", "os.environ.get(WS_TOKEN_ENV)" in app)
    check("obs reads WS_TOKEN from env", "os.environ.get(WS_TOKEN_ENV)" in obs)
    check("ssh-gateway reads WS_TOKEN from env", "process.env.WS_TOKEN" in gateway)
    check("WS_TOKEN default falls back to agent",
          'WS_TOKEN_DEFAULT = "agent"' in app
          and 'WS_TOKEN_DEFAULT = "agent"' in obs
          and "|| 'agent'" in gateway)

    # 3) compose 注入 WS_TOKEN
    check("compose injects WS_TOKEN for control", "WS_TOKEN=${WS_TOKEN:-agent}" in compose)
    check("compose injects WS_TOKEN 3 times",
          compose.count("WS_TOKEN=${WS_TOKEN:-agent}") == 3)

    # 4) 前端页面带上 token
    check("ssh terminal page appends token to ws url",
          "&token=' + encodeURIComponent(" in app)
    check("ssh terminal page injects token value",
          "ws_token_js = json.dumps(app.config[\"WS_TOKEN\"])" in app)
    check("obs homepage injects token value",
          "const WS_TOKEN = {ws_token};" in obs)
    check("obs homepage appends token to ws url",
          "/ws?token=${encodeURIComponent(WS_TOKEN)}" in obs)

    # 5) 线上实测
    # 5a) control /ws/ssh
    status, frames = probe(CONTROL_PORT, "/ws/ssh?container=%s" % SSH_CONTAINER)
    check("control /ws/ssh without token is rejected",
          4401 in close_codes(frames) or "403" in status)
    status, frames = probe(CONTROL_PORT, "/ws/ssh?container=%s&token=wrong-token" % SSH_CONTAINER)
    check("control /ws/ssh with wrong token is rejected",
          4401 in close_codes(frames) or "403" in status)
    status, frames = probe(CONTROL_PORT, "/ws/ssh?container=%s&token=agent" % SSH_CONTAINER)
    check("control /ws/ssh with correct token is accepted",
          "101" in status and not close_codes(frames),
          )

    # 5b) obs /ws
    status, frames = probe(OBS_PORT, "/ws")
    check("obs /ws without token is rejected", "403" in status or 4401 in close_codes(frames))
    status, frames = probe(OBS_PORT, "/ws?token=wrong-token")
    check("obs /ws with wrong token is rejected", "403" in status or 4401 in close_codes(frames))
    status, frames = probe(OBS_PORT, "/ws?token=agent")
    check("obs /ws with correct token is accepted",
          "101" in status and any("init" in p for p in text_payloads(frames)))

    # 5c) ssh-gateway
    status, frames = probe(GATEWAY_PORT, "/?port=18081")
    check("ssh-gateway without token is rejected", 4401 in close_codes(frames))
    status, frames = probe(GATEWAY_PORT, "/?port=18081&token=wrong-token")
    check("ssh-gateway with wrong token is rejected", 4401 in close_codes(frames))
    status, frames = probe(GATEWAY_PORT, "/?port=18081&token=agent")
    check("ssh-gateway with correct token is accepted",
          "101" in status and 4401 not in close_codes(frames))


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
