# -*- coding: utf-8 -*-
"""TDD 校验：面板右上角「思考程度」高/中/低，改完不立刻生效，重启卡片后生效。

背景：
  CLI 只认 CLAUDE_CODE_EFFORT_LEVEL（单数，low|medium|high）；
  settings.json 里原来的 CLAUDE_CODE_EFFORT_LEVELS（复数）是无效键。
  容器每次启动会把 /agent-config（宿主机 config/claude/）复制到 ~/.claude/，
  所以「写宿主机 settings.json* → 重启卡片」即可换档，不需要重建。

  但绝不能把它注入容器进程 env：进程 env 优先于 settings.json，
  一旦在创建容器时冻住，重启也换不了档。这也是本次的关键约束。

覆盖点：
  A) 静态
     1) 三个档位 high/medium/low 与中文标签 高/中/低；
     2) create/recreate 两处都 pop 掉 EFFORT_LEVEL（否则重启不生效）；
     3) GET/PUT /api/thinking-level 存在；
     4) 前端有 thinkingLevel 选择器 + 三个 option。
  B) 线上
     5) GET 返回 level ∈ {high,medium,low}，含 levels/labels/pending；
     6) PUT low → 200，GET 变 low，宿主机 settings.json 与所有变体都写入；
     7) 旧的复数键被清掉；
     8) 非法档位 → 400；
     9) 测完恢复原档位（不留副作用）。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(ROOT, "control", "app.py")
CLAUDE_DIR = os.path.join(ROOT, "config", "claude")
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")

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


def request(path, method="GET", body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(CONTROL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def settings_variants():
    return [os.path.join(CLAUDE_DIR, n) for n in sorted(os.listdir(CLAUDE_DIR))
            if n == "settings.json" or n.startswith("settings.json.")]


def run_static():
    src = read(os.path.join("control", "app.py"))
    check("three levels declared", 'THINKING_LEVELS = ("high", "medium", "low")' in src)
    check("labels 高/中/低", all(x in src for x in ('"high": "高"', '"medium": "中"', '"low": "低"')))
    check("env key is singular", 'THINKING_LEVEL_ENV = "CLAUDE_CODE_EFFORT_LEVEL"' in src)
    pops = len(re.findall(r"env_vars\.pop\(THINKING_LEVEL_ENV, None\)", src))
    check("both create+recreate strip it from env (found %d)" % pops, pops >= 2)
    check("legacy plural key removed", 'env.pop("CLAUDE_CODE_EFFORT_LEVELS", None)' in src)
    check("GET endpoint", '@app.get("/api/thinking-level")' in src)
    check("PUT endpoint", '@app.put("/api/thinking-level")' in src)
    check("frontend selector", 'id="thinkingLevel"' in src)
    check("frontend options", all(v in src for v in ('<option value="high">高</option>',
                                                     '<option value="medium">中</option>',
                                                     '<option value="low">低</option>')))
    check("hint says restart", '重启卡片后生效' in src)


def run_live():
    status, data = request("/api/thinking-level")
    check("GET 200", status == 200)
    original = data.get("level")
    check("level is valid", original in ("high", "medium", "low"))
    check("levels list", set(data.get("levels") or []) == {"high", "medium", "low"})
    check("labels returned", (data.get("labels") or {}).get("medium") == "中")
    check("pending is a list", isinstance(data.get("pending"), list))
    if not original:
        skip("live round-trip", "no level returned")
        return

    try:
        status, saved = request("/api/thinking-level", "PUT", {"level": "low"})
        check("PUT low → 200", status == 200 and saved.get("ok") is True)
        status, now = request("/api/thinking-level")
        check("GET reflects low", status == 200 and now.get("level") == "low")

        ok_all = True
        for path in settings_variants():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    env = (json.load(f) or {}).get("env") or {}
            except Exception:
                ok_all = False
                continue
            if env.get("CLAUDE_CODE_EFFORT_LEVEL") != "low" or "CLAUDE_CODE_EFFORT_LEVELS" in env:
                ok_all = False
                print("   -> %s env=%r" % (os.path.basename(path), env.get("CLAUDE_CODE_EFFORT_LEVEL")), flush=True)
        check("all settings.json* carry the level, legacy key gone", ok_all)

        status, _ = request("/api/thinking-level", "PUT", {"level": "ultra"})
        check("invalid level rejected with 400", status == 400)
    finally:
        status, _ = request("/api/thinking-level", "PUT", {"level": original})
        check("restored original level (%s)" % original, status == 200)
        status, after = request("/api/thinking-level")
        check("level back to original", after.get("level") == original)


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
