# -*- coding: utf-8 -*-
"""TDD 校验：云端 api key 只存在于 hermit-llm-gateway，卡片侧只带本地口令。

背景：
  以前每张卡片容器里都存着一份云端 api key（config/claude/settings.json.<p> 等），
  密钥散落在几十个容器里，任何一张卡被拉起来就等于泄露一次。
  现在改成：
    - 真实 key 只在 config/llm-gateway/upstreams.json（.gitignore 排除，不入库）
    - 卡片一律指向 http://hermit-llm-gateway:8083/<profile>，口令是 agent
    - hermit-llm-gateway 不发布宿主机端口，也就不在 frpc 里暴露

覆盖点：
  A) 静态
     1) gateway 服务文件存在（server.js / Dockerfile）。
     2) docker-compose 里有 hermit-llm-gateway，且**没有** ports（不映射宿主机端口）。
     3) 真实 key 文件被 .gitignore 排除（git check-ignore 命中，且 git 未跟踪）。
     4) 卡片侧配置里没有任何云端 key：只有 agent 口令 + 网关地址。
     5) gateway 源码里鉴权在业务之前，且转发时把两个鉴权头都换成真 key。
  B) 线上
     1) gateway 容器在跑，且未发布宿主机端口（docker inspect Ports 里没有 8083 映射）。
     2) 宿主机连 127.0.0.1:8083 连不上（内网服务）。
     3) 网关内 /health 免鉴权可通。
     4) /ask/claude 无 token / 错 token 一律 401，正确 token 返回内容。
     5) Anthropic 协议透传（/<profile>/v1/messages）带 token 能真实返回上游结果。
     6) 卡片容器内既没有进程 env 里的云端 key，文件里也没有。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading

TIMEOUT_SECONDS = 180
ROOT = os.path.dirname(os.path.abspath(__file__))
GATEWAY_DIR = os.path.join(ROOT, "agents", "llm-gateway")
UPSTREAMS_FILE = os.path.join(ROOT, "config", "llm-gateway", "upstreams.json")
COMPOSE_FILE = os.path.join(ROOT, "docker-compose.yml")
CLAUDE_DIR = os.path.join(ROOT, "config", "claude")
OPENCLAW_DIR = os.path.join(ROOT, "config", "openclaw")

GATEWAY_CONTAINER = "hermit-llm-gateway"
GATEWAY_URL = "http://hermit-llm-gateway:8083"
# 探针用的卡片容器（需要与 gateway 同一个 docker 网络）
PROBE_CARDS = [os.environ.get("PROBE_CARD_1", "18081-hub"),
               os.environ.get("PROBE_CARD_2", "18115-minimax")]

failures = []
skips = []

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(name, ok, extra=""):
    print(("[PASS] " if ok else "[FAIL] ") + name + ((" -> " + extra) if extra else ""), flush=True)
    if not ok:
        failures.append(name)


def skip(name, why):
    print("[SKIP] %s (%s)" % (name, why), flush=True)
    skips.append(name)


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def sh(args, timeout=60):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return "EXC:%r" % (e,)


def in_card(cmd, container=None, timeout=90):
    """在卡片容器里执行 shell 命令（容器与 gateway 同网）。"""
    target = container or PROBE_CARDS[0]
    return sh(["docker", "exec", target, "sh", "-lc", cmd], timeout=timeout).strip()


def compose_service_block(text, service):
    """截出 compose 里某个 service 的整段（按两空格缩进）。"""
    lines = text.splitlines()
    out = []
    inside = False
    for line in lines:
        if re.match(r"^  %s:\s*$" % re.escape(service), line):
            inside = True
            out.append(line)
            continue
        if inside:
            if re.match(r"^  \S", line):
                break
            out.append(line)
    return "\n".join(out)


# ------------------------------------------------------------------ 静态检查
def run_static():
    server_path = os.path.join(GATEWAY_DIR, "server.js")
    dockerfile_path = os.path.join(GATEWAY_DIR, "Dockerfile")
    check("gateway server.js exists", os.path.isfile(server_path))
    check("gateway Dockerfile exists", os.path.isfile(dockerfile_path))
    if not os.path.isfile(server_path):
        return

    server = read(server_path)
    compose = read(COMPOSE_FILE)
    gitignore = read(os.path.join(ROOT, ".gitignore"))

    # 2) compose：不发布宿主机端口
    block = compose_service_block(compose, "hermit-llm-gateway")
    check("compose declares hermit-llm-gateway", bool(block.strip()))
    check("gateway service publishes no host port", "ports:" not in block, block)
    check("gateway joins openclaw-network", "openclaw-network" in block)
    check("gateway token comes from env with default agent",
          "LLM_GATEWAY_TOKEN=${LLM_GATEWAY_TOKEN:-agent}" in block)
    check("gateway mounts upstream config read-only",
          "./config/llm-gateway:/agent-config:ro" in block)

    # 3) 真实 key 文件不入库
    check("upstreams.json exists", os.path.isfile(UPSTREAMS_FILE))
    ignored = sh(["git", "check-ignore", "-v", "config/llm-gateway/upstreams.json"], timeout=30).strip()
    tracked = sh(["git", "ls-files", "--error-unmatch", "config/llm-gateway/upstreams.json"],
                 timeout=30).strip()
    check("upstreams.json is git-ignored", ".gitignore" in ignored, ignored)
    check("upstreams.json is not tracked by git", "did not match any file" in tracked, tracked[:120])
    check("gitignore ignores config/*", re.search(r"^config/\*", gitignore, re.M) is not None)

    # 4) 卡片侧配置：只有 agent 口令 + 网关地址，没有任何云端 key
    files = []
    for name in sorted(os.listdir(CLAUDE_DIR)):
        if name.startswith("settings.json") or name.startswith("config.json"):
            files.append(os.path.join(CLAUDE_DIR, name))
    for base, _dirs, names in os.walk(OPENCLAW_DIR):
        for name in names:
            if name.endswith(".json"):
                files.append(os.path.join(base, name))

    key_re = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
    bad_keys = []
    bad_token = []
    bad_url = []
    for path in files:
        text = read(path)
        if key_re.search(text):
            bad_keys.append(os.path.relpath(path, ROOT))
        for token in re.findall(r'"(?:ANTHROPIC_AUTH_TOKEN|apiKey|access)"\s*:\s*"([^"]*)"', text):
            if token in ("agent", "ollama", "ollama-local", ""):
                continue
            if key_re.search(token):
                bad_token.append("%s -> %s" % (os.path.relpath(path, ROOT), token))
        for url in re.findall(r'"(?:ANTHROPIC_BASE_URL|baseUrl)"\s*:\s*"([^"]*)"', text):
            if url.startswith("http://") and "hermit-llm-gateway" not in url \
                    and "11434" not in url and "192.168.0.209" not in url:
                bad_url.append("%s -> %s" % (os.path.relpath(path, ROOT), url))
    check("card configs carry no cloud api key", not bad_keys, "; ".join(bad_keys))
    check("card configs only use the local gateway token", not bad_token, "; ".join(bad_token))
    check("card configs only point at the gateway", not bad_url, "; ".join(bad_url))

    # 5) gateway 源码：鉴权在业务之前 + 转发时换真 key
    check("gateway reads token from env", "process.env.LLM_GATEWAY_TOKEN" in server)
    check("gateway token default is agent", "|| 'agent'" in server)
    check("gateway compares token in constant time", "timingSafeEqual" in server)
    handler = server[server.index("const server = http.createServer"):]
    check("gateway rejects unauthorized before routing",
          handler.index("tokenOk(") < handler.index("handleAsk("))
    check("gateway serves /ask/claude", "'/ask/claude'" in server)
    check("gateway forwards anthropic protocol", "/v1/" in server)
    check("gateway replaces both auth headers with the real key",
          "'x-api-key': def.api_key" in server
          and "'authorization': 'Bearer ' + def.api_key" in server)
    check("gateway never forwards the local token upstream",
          not re.search(r"authorization':\s*'Bearer '\s*\+\s*token", server, re.I))


# ------------------------------------------------------------------ 线上检查
def run_live():
    # 1) 容器在跑 + 没有发布宿主机端口
    status = sh(["docker", "inspect", GATEWAY_CONTAINER, "--format",
                 "{{.State.Status}}"], timeout=30).strip()
    check("gateway container is running", status == "running", status)
    # NetworkSettings.Ports 里每个端口的映射值都是 null（= 没发布到宿主机）
    ports = sh(["docker", "inspect", GATEWAY_CONTAINER, "--format",
                "{{json .NetworkSettings.Ports}}"], timeout=30).strip()
    published = []
    try:
        for _port, bindings in (json.loads(ports) or {}).items():
            if bindings:
                published.append("%s->%s" % (_port, bindings))
    except Exception:
        published = ["unparsable:%s" % ports]
    check("gateway publishes no host port", not published, ports)

    # 2) 宿主机连不上（内网服务，frpc 也连不到）
    reachable = True
    try:
        s = socket.create_connection(("127.0.0.1", 8083), timeout=5)
        s.close()
    except Exception:
        reachable = False
    check("host cannot reach gateway on 8083", not reachable)

    # 3~6) 都要在同网络的容器里测
    probe = PROBE_CARDS[0]
    if "No such container" in in_card("true", container=probe):
        skip("live gateway probes", "probe card %s not available" % probe)
        return

    health = in_card("curl -s -m 15 %s/health" % GATEWAY_URL)
    check("gateway /health reachable without token", '"ok":true' in health.replace(" ", ""), health[:120])

    no_token = in_card("curl -s -m 15 -o /dev/null -w '%%{http_code}' '%s/ask/claude?q=hi'" % GATEWAY_URL)
    check("gateway /ask/claude without token is rejected", no_token.strip() == "401", no_token)
    bad_token = in_card("curl -s -m 15 -o /dev/null -w '%%{http_code}' '%s/ask/claude?q=hi&token=wrong'"
                        % GATEWAY_URL)
    check("gateway /ask/claude with wrong token is rejected", bad_token.strip() == "401", bad_token)

    ask = in_card("curl -s -m 90 '%s/ask/claude?q=reply%%20with%%20exactly%%3A%%20OK&token=agent&upstream=minimax'"
                  % GATEWAY_URL, timeout=120)
    check("gateway /ask/claude with correct token answers", "OK" in ask, ask[:160])

    body = json.dumps({"model": "MiniMax-M3.1-Flash", "max_tokens": 16,
                       "messages": [{"role": "user", "content": "reply with exactly: OK"}]})
    import base64
    b64 = base64.b64encode(body.encode()).decode()
    proto = in_card(
        "printf '%%s' %s | base64 -d > /tmp/gw_probe.json; "
        "curl -s -m 90 -X POST '%s/minimax/v1/messages' "
        "-H 'content-type: application/json' -H 'anthropic-version: 2023-06-01' "
        "-H 'x-api-key: agent' --data-binary @/tmp/gw_probe.json | head -c 400" % (b64, GATEWAY_URL),
        timeout=120)
    check("gateway forwards anthropic protocol to the real upstream",
          "OK" in proto and "content" in proto, proto[:200])

    # 卡片容器内不得残留云端 key（进程 env + 文件）
    for card in PROBE_CARDS:
        env = in_card("env | grep -i anthropic || true", container=card)
        if "No such container" in env:
            skip("card %s env check" % card, "container not available")
            continue
        check("card %s env has no cloud api key" % card,
              not re.search(r"sk-[A-Za-z0-9_\-]{8,}", env), env.replace("\n", " ")[:200])
        check("card %s env points at the gateway" % card,
              GATEWAY_URL in env, env.replace("\n", " ")[:200])
        check("card %s env token is agent" % card, "ANTHROPIC_AUTH_TOKEN=agent" in env)

        files = in_card("grep -rEo 'sk-[A-Za-z0-9_-]{8,}' /home/agent/.claude/settings.json "
                        "/home/agent/.claude/config.json 2>/dev/null | head -5 || true", container=card)
        check("card %s files carry no cloud api key" % card,
              "sk-" not in files, files[:160])


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
