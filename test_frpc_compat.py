# -*- coding: utf-8 -*-
"""TDD 校验：control 创建容器卡片时 frpc 规则同步兼容 frp / frpc 两种目录。

覆盖点：
  1) control/app.py 兼容 frp 与 frpc 两种配置目录（FRPC_PATH / FRPC_ALT_PATH）。
  2) control/app.py 提供 resolve_frpc_config_path 动态探测实际存在的 frpc.ini。
  3) add_frpc_rule 每次写入前动态解析路径，不再依赖固定 FRPC_CONFIG_PATH。
  4) docker-compose.yml 同时挂载 ../frpc 与 ../frp 两个目录。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
import subprocess

TIMEOUT_SECONDS = 60
ROOT = os.path.dirname(os.path.abspath(__file__))

failures = []


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def read(rel):
    p = os.path.join(ROOT, rel)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def run():
    app = read("control/app.py")
    compose = read("docker-compose.yml")

    # 1) 兼容两种目录
    check("control FRPC_PATH frpc dir", 'FRPC_PATH = "/Users/jimjiang/Downloads/frpc"' in app)
    check("control FRPC_ALT_PATH frp dir", 'FRPC_ALT_PATH = "/Users/jimjiang/Downloads/frp"' in app)

    # 2) 动态探测函数
    check("control has resolve_frpc_config_path", "def resolve_frpc_config_path" in app)
    check("control resolve probes frpc.ini", 'os.path.join(d, "frpc.ini")' in app)

    # 3) add_frpc_rule 动态解析，不再依赖固定 FRPC_CONFIG_PATH
    check("control no fixed FRPC_CONFIG_PATH", "FRPC_CONFIG_PATH" not in app)
    check("control add_frpc_rule uses cfg_path", "cfg_path = resolve_frpc_config_path()" in app)

    # 3b) 19095 事故：section 已存在时**不能**连"重启 frpc"一起跳过
    #     （"配置里写了" ≠ "frps 上生效"：端口复用留下的旧条目会让新卡片的映射永远建不起来）
    body = app.split("def add_frpc_rule")[1].split("\n    def ")[0]
    check("add_frpc_rule no early-return on existing section", "already configured, skipping" not in body)
    check("add_frpc_rule always restarts frpc",
          'containers.get("frpc")' in body and "container.restart()" in body)
    check("add_frpc_rule rewrites stale section", "rewrote" in body and "new_content" in body)

    # 4) docker-compose 同时挂载两种目录
    #    注意：路径已从 ${PWD}/../frpc 改成相对路径 ../frpc —— compose 的相对路径按
    #    compose 文件所在目录解析，跟执行 compose 的 shell 的 ${PWD} 无关，更可靠。
    check("compose mounts ../frpc", "../frpc:/Users/jimjiang/Downloads/frpc" in compose)
    check("compose mounts ../frp", "../frp:/Users/jimjiang/Downloads/frp" in compose)
    active = [l for l in compose.splitlines() if not l.strip().startswith("#")]
    check("compose has no active ${PWD} dependency", all("${PWD}" not in l for l in active))

    # 5) 线上不变量：frpc 载入的配置不能比 frpc.ini 旧
    #    （否则就是"改了配置文件但没让 frpc 加载"——19095 公网被拒绝就是这个原因）
    run_live_freshness()


def _parse_iso(s):
    s = (s or "").strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "." in s:
        head, rest = s.split(".", 1)
        for sep in ("+", "-"):
            if sep in rest:
                frac, tz = rest.split(sep, 1)
                tz = sep + tz
                break
        else:
            frac, tz = rest, ""
        s = head + "." + frac[:6] + tz
    return datetime.fromisoformat(s)


def run_live_freshness():
    """frpc.StartedAt 必须 >= frpc.ini 的 mtime（否则配置改了没加载）。"""
    ini = None
    for cand in (os.path.join(os.path.expanduser("~"), "Downloads", "frpc", "frpc.ini"),
                 os.path.join(os.path.expanduser("~"), "Downloads", "frp", "frpc.ini")):
        if os.path.isfile(cand):
            ini = cand
            break
    if not ini:
        print("[SKIP] frpc freshness (本机找不到 frpc.ini)", flush=True)
        return
    try:
        p = subprocess.run(["docker", "inspect", "frpc", "--format", "{{.State.StartedAt}}"],
                           capture_output=True, timeout=30)
        started = _parse_iso((p.stdout or b"").decode("utf-8", "replace"))
    except Exception as e:
        print("[SKIP] frpc freshness (docker 不可用: %s)" % e, flush=True)
        return
    mtime = datetime.fromtimestamp(os.path.getmtime(ini), tz=timezone.utc)
    # 给几秒余量：同一秒内的写入/重启不该误报
    check("frpc loaded config no older than frpc.ini", started >= mtime - timedelta(seconds=5))
    print("   -> frpc started %s / frpc.ini mtime %s" % (started.isoformat(), mtime.isoformat()), flush=True)


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
    print("ALL CHECKS PASSED", flush=True)
    sys.exit(0)
