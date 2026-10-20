# -*- coding: utf-8 -*-
"""TDD 校验：项目内 hermit 品牌已改名为 harness，且基础设施标识未被误改。

背景与边界（用户明确要求「只改源码配置文档，容器名与镜像名保留」）：
  运行中的容器、镜像、compose 项目名、docker label、域名、日志挂载路径
  都是"活"标识，改了会立刻打断正在跑的服务，所以必须原样保留。

判定方法（避免"删掉保护词再搜"这种会误判的做法）：
  1) 先找出文本里所有受保护 token 的字符区间；
  2) 再找出所有 hermit（不分大小写）的位置；
  3) 任何一个 hermit 落不在受保护区间内 → 算未改名，报 FAIL。
  这样 harness-agent-types 不会被 hermit-agent-claude 的保护区间误判放过。

覆盖点：
  1) 全仓库（排除运行产物）不存在"裸露"的 hermit。
  2) 受保护的基础设施标识仍在（容器名/镜像名/项目名/label/域名/网络/日志路径）。
  3) 含 hermit 的文件与目录已改名，旧路径不复存在。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import re
import sys
import threading

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))

# 本文件自身要列出旧路径（改名映射），会被误判，故跳过自扫。
SELF_NAME = os.path.basename(os.path.abspath(__file__))

# 运行产物 / 依赖 / VCS，不参与扫描
SKIP_DIRS = {".git", "logs", "workspaces", "node_modules", "__pycache__", ".venv", "venv", "tmp"}

# 必须原样保留的基础设施标识（会打断运行中服务或指向不存在的资源）
PROTECTED = [
    "hermit-control-19080",              # 运行中的控制面板容器名
    "hermit-ssh-gateway",                # 运行中的 SSH 网关容器名
    "hermit-agent-claude",               # 镜像名（agent 模板）
    "hermit-agent-ollama",               # 镜像名
    "hermit-agent-openclaw-2026.2.9",    # 镜像名
    "hermit-claw",                       # compose 项目名 / 网络名前缀 / 仓库名
    "hermitclaw",                        # 本地目录名
    "hermit.dimond.top",                 # 线上域名（反代入口）
    "hermit.local",                      # SSH 用户 host
    "hermit.managed",                    # docker label：容器归属
    "hermit.agent_type",                 # docker label：agent 类型
    "hermit.service_port",               # docker label
    "hermit.host_port",                  # docker label
    "hermit.tool",                       # docker label：工具容器
    "hermit-tool-",                      # 工具容器名前缀（hub 注册表按它剥离）
    "logs/hermit",                       # 日志挂载路径
]

# 期望完成的改名（旧 -> 新）
RENAMES = [
    ("agents/claude/hermit-watchdog.sh", "agents/claude/harness-watchdog.sh"),
    ("config/hermit_settings.json", "config/harness_settings.json"),
    ("config/rules/hermit-container-debugging-guide.md",
     "config/rules/harness-container-debugging-guide.md"),
    ("test-hermit.mjs", "test-harness.mjs"),
] + [
    ("config/claude/skills/hermit-%s/SKILL.md" % n, "config/claude/skills/harness-%s/SKILL.md" % n)
    for n in ("agent-types", "ask-image", "ask-server", "config", "env", "git", "init",
              "logging", "paths", "ports", "supabase", "tools-hub", "user", "workflow")
]

HERMIT_RE = re.compile(r"hermit", re.I)

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


def protected_spans(text):
    spans = []
    for tok in PROTECTED:
        start = 0
        while True:
            i = text.find(tok, start)
            if i < 0:
                break
            spans.append((i, i + len(tok)))
            start = i + 1
    return spans


def naked_hermits(text):
    """返回未被受保护区间覆盖的 hermit 命中（行号, 原文片段）。"""
    spans = protected_spans(text)
    lines = text.splitlines()
    out = []
    for m in HERMIT_RE.finditer(text):
        i = m.start()
        if any(a <= i < b for a, b in spans):
            continue
        line_no = text.count("\n", 0, i) + 1
        line = lines[line_no - 1] if line_no - 1 < len(lines) else ""
        out.append((line_no, line.strip()[:120]))
    return out


def iter_text_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn == SELF_NAME:
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    yield path, f.read()
            except (UnicodeDecodeError, OSError):
                continue


def run():
    # 1) 全仓库不留裸露的 hermit
    offenders = []
    scanned = 0
    for path, text in iter_text_files():
        scanned += 1
        hits = naked_hermits(text)
        if hits:
            rel = os.path.relpath(path, ROOT)
            offenders.append("%s:%s %s" % (rel, hits[0][0], hits[0][1]))
    check("no naked hermit left (%d files scanned, %d offenders)"
          % (scanned, len(offenders)), not offenders)
    for o in offenders[:20]:
        print("   -> %s" % o, flush=True)
    if len(offenders) > 20:
        print("   -> ... and %d more" % (len(offenders) - 20), flush=True)

    # 2) 受保护标识仍在
    for rel, tokens in (
        ("docker-compose.yml", ["container_name: hermit-control-19080",
                                "container_name: hermit-ssh-gateway",
                                "image: hermit-agent-claude:latest",
                                "name: hermit-claw"]),
        ("control/app.py", ['"hermit.managed"', '"hermit.agent_type"',
                            'image": "hermit-agent-claude:latest']),
    ):
        p = os.path.join(ROOT, rel)
        text = open(p, encoding="utf-8").read() if os.path.isfile(p) else ""
        for t in tokens:
            check("%s keeps %s" % (rel, t), t in text)

    # 3) 改名已落地
    for old_rel, new_rel in RENAMES:
        old_p, new_p = os.path.join(ROOT, old_rel), os.path.join(ROOT, new_rel)
        check("old path gone: %s" % old_rel, not os.path.exists(old_p))
        check("new path exists: %s" % new_rel, os.path.exists(new_p))


if __name__ == "__main__":
    def guarded():
        # 守护线程里的未捕获异常会让 join() 提前返回且 failures 为空 → 假绿，必须兜住。
        try:
            run()
        except Exception:
            import traceback
            traceback.print_exc()
            failures.append("unhandled exception in test thread")

    t = threading.Thread(target=guarded, daemon=True)
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
