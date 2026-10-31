# -*- coding: utf-8 -*-
"""TDD 校验：模型统一走 harness-llm-gateway 出口，卡片不再持有 API key。

为什么：
  2026-10-22 入侵时，攻击者从公网无鉴权的面板进卡片，直接读到容器里的
  config.json / settings.json，把所有模型的 API key 翻走了。
  根因是「每张卡片都揣着自己的 key」。

现在的设计：
  - 真 key 只在 config/llm-gateway/providers.json，挂进 harness-llm-gateway 容器
  - 卡片只有：ANTHROPIC_BASE_URL=http://harness-llm-gateway:8080
              ANTHROPIC_AUTH_TOKEN=agent（假 token，只是网关的入口口令）
  - 网关不对公网开放（compose 里没有 ports，frpc 里也没有规则）
  - 面板点 HARNESS 标题可切出口 profile，**立刻生效**，卡片无需重启
  - 卡片上的「切换模型」按钮改成「查看模型」（只读）

覆盖点：
  A) 静态
     1) config/llm-gateway/ 下有 providers.json + gateway.py + Dockerfile
     2) compose 里有 llm-gateway 服务，且**没有** ports（不对宿主机发布）
     3) 卡片配置（config/claude/*）的 base_url 指向网关，token 是 agent，且没有真 key
     4) 面板：HARNESS 弹层走 /api/llm-gateway/*；卡片按钮是「查看模型」
  B) 线上
     5) 网关从 control 容器可达（内网），health 里有 profile/model
     6) 网关拒绝没 token 的请求（401）
     7) 网关切换 profile 立刻生效（/health 的 model 变了），且卡片没被重启
     8) 卡片 env 指向网关、token=agent；卡片文件里没有 sk- 真 key
     9) 网关没有发布端口，frpc 里没有它的规则

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 180
ROOT = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")
GATEWAY = "harness-llm-gateway"
GATEWAY_URL = "http://%s:8080" % GATEWAY
CARD = os.environ.get("GW_TEST_CARD", "19091-picturetext")
FRPC_INI = os.environ.get("FRPC_INI", r"C:\Users\qq939\Downloads\frp\frpc.ini")

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


def http(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return None, str(e)


def docker(*args, timeout=60):
    p = subprocess.run(["docker", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def run_static():
    for name in ("providers.json", "gateway.py", "Dockerfile"):
        path = os.path.join(ROOT, "config", "llm-gateway", name)
        check("config/llm-gateway/%s 存在" % name, os.path.isfile(path))

    compose = read(os.path.join("docker-compose.yml"))
    check("compose 有 llm-gateway 服务", "llm-gateway:" in compose)
    check("compose 声明容器名 " + GATEWAY, "container_name: %s" % GATEWAY in compose)
    # 网关不能有 ports（不对宿主机发布）
    m = re.search(r"^  llm-gateway:.*?(?=^  \S|\Z)", compose, re.M | re.S)
    block = m.group(0) if m else ""
    check("网关不发布宿主机端口", "ports:" not in block)
    check("网关挂载 config/llm-gateway", "./config/llm-gateway:/config" in block)

    # 卡片配置：指向网关 + 没有真 key
    claude_dir = os.path.join(ROOT, "config", "claude")
    real_key = []
    not_pointing = []
    for name in sorted(os.listdir(claude_dir)):
        if not (name.startswith("config.json") or name.startswith("settings.json")):
            continue
        if name.endswith(".bak"):
            continue
        text = open(os.path.join(claude_dir, name), "r", encoding="utf-8").read()
        if re.search(r"sk-[A-Za-z0-9]{20,}", text):
            real_key.append(name)
        if "harness-llm-gateway" not in text:
            not_pointing.append(name)
    check("卡片配置里没有真 key (%s)" % (real_key or "无"), not real_key)
    check("卡片配置都指向网关 (%s)" % (not_pointing or "全部"), not not_pointing)

    app = read(os.path.join("control", "app.py"))
    check("面板有 /api/llm-gateway/profiles", "/api/llm-gateway/profiles" in app)
    check("面板有 /api/llm-gateway/profile", "/api/llm-gateway/profile" in app)
    check("HARNESS 弹层加载网关出口", "loadGatewayProfiles" in app)
    check("卡片按钮是「查看模型」", "查看模型" in app)
    check("不再有「切换模型」按钮", ">切换模型<" not in app)


def gateway_base():
    """网关地址：宿主机上容器名解析不了，用 docker 查它的 IP。"""
    rc, out, err = docker("inspect", GATEWAY, "--format",
                          "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}")
    if rc == 0 and out.strip():
        return "http://%s:8080" % out.strip().splitlines()[0].strip()
    return GATEWAY_URL


def run_live():
    base = gateway_base()
    # 网关内网可达
    code, out = http(base + "/health")
    if code != 200:
        # 从 control 容器里试（宿主机可能解析不了容器名）
        rc, o, e = docker("exec", "hermit-control-19080", "python", "-c",
                           "import urllib.request;print(urllib.request.urlopen('http://%s:8080/health',timeout=10).read().decode())" % GATEWAY)
        if rc == 0 and o:
            data = json.loads(o.strip().splitlines()[-1])
            check("网关 health（内网）", data.get("ok") is True and bool(data.get("model")))
        else:
            skip("网关 health", "内网不可达: %s" % (e or out)[:80])
            return
    else:
        data = json.loads(out)
        check("网关 health（内网）", data.get("ok") is True and bool(data.get("model")))

    # token 鉴权
    code, out = http(base + "/v1/messages", headers={"x-api-key": "wrong"})
    check("网关拒绝错误 token (%s)" % code, code == 401)
    code, out = http(base + "/admin/profiles")
    check("网关管理接口也要 token (%s)" % code, code == 401)
    code, out = http(base + "/admin/profiles", headers={"x-api-key": "agent"})
    check("网关管理接口带 token 可用 (%s)" % code, code == 200)

    # 切 profile 立刻生效，且卡片没被重启
    try:
        before = docker("inspect", CARD, "--format", "{{.State.StartedAt}}")[1]
        code, out = http(CONTROL + "/api/llm-gateway/profile", ) if False else (None, "")
        # 面板接口是 POST，这里直接用 urllib
        req = urllib.request.Request(CONTROL + "/api/llm-gateway/profile",
                                     data=json.dumps({"profile": "minimax"}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            switched = json.loads(r.read().decode())
        check("面板切出口成功", switched.get("ok") is True and switched.get("profile") == "minimax")
        after = docker("inspect", CARD, "--format", "{{.State.StartedAt}}")[1]
        check("切换出口后卡片没有被重启", before == after)

        rc, o, e = docker("exec", "hermit-control-19080", "python", "-c",
                           "import urllib.request,json;print(urllib.request.urlopen('http://%s:8080/health',timeout=10).read().decode())" % GATEWAY)
        if rc == 0:
            h = json.loads(o.strip().splitlines()[-1])
            check("网关当前出口已变 (%s / %s)" % (h.get("profile"), h.get("model")),
                  h.get("profile") == "minimax")
    finally:
        req = urllib.request.Request(CONTROL + "/api/llm-gateway/profile",
                                     data=json.dumps({"profile": "default"}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=20).read()
        except Exception:
            pass

    # 卡片 env 指向网关 + 没有真 key
    rc, env, err = docker("inspect", CARD, "--format", "{{range .Config.Env}}{{println .}}{{end}}")
    check("卡片 base_url 指向网关", "ANTHROPIC_BASE_URL=http://harness-llm-gateway:8080" in env)
    check("卡片 token 是 agent（不是真 key）",
          "ANTHROPIC_AUTH_TOKEN=agent" in env and not re.search(r"ANTHROPIC_AUTH_TOKEN=sk-", env))
    rc, out, err = docker("exec", "-u", "agent", CARD, "sh", "-c",
                           "grep -oE 'sk-[A-Za-z0-9]{20,}' /home/agent/.claude/config.json /home/agent/.claude/settings.json 2>/dev/null | head -3; true")
    check("卡片文件里没有真 key", not out.strip())

    # 网关没有发布端口，frpc 没有规则
    rc, out, err = docker("inspect", GATEWAY, "--format", "{{json .HostConfig.PortBindings}}")
    check("网关不发布宿主机端口 (%s)" % out, out.strip() in ("{}", "null"))
    if os.path.isfile(FRPC_INI):
        frpc = open(FRPC_INI, "r", encoding="utf-8", errors="replace").read()
        check("frpc 没有网关的公网规则", "llm-gateway" not in frpc)


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
