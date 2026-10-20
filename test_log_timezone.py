# -*- coding: utf-8 -*-
"""TDD 校验：容器卡片的日志时间统一北京时间（+08:00）。

背景：
  卡片镜像默认 UTC，run_claude.js 用 toISOString() 写日志，
  面板里看到的时间戳比北京时间慢 8 小时。

修法（三层，缺一层就会出现"有的日志对、有的不对"）：
  1) run_claude.js 用 Intl.DateTimeFormat(Asia/Shanghai) 生成时间戳，
     不依赖容器 tzdata，也不受 TZ 是否设置影响；
  2) 新建/重建卡片时注入 TZ=Asia/Shanghai，卡片内 date/应用日志跟着对；
  3) control 自己也在 compose 里设 TZ，面板侧时间一致。

覆盖点：
  A) 静态：上面三处配置都在。
  B) 线上：control 与运行中的卡片 date 偏移都是 +0800；
     卡片里 node 的 Intl 时间与北京时间同小时。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))
CARDS = os.environ.get("TZ_CHECK_CARDS", "19091-picturetext,19085-git,19081-hub").split(",")

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


def docker(*args, timeout=30):
    p = subprocess.run(["docker", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def run_static():
    js = read(os.path.join("config", "rules", "run_claude.js"))
    check("run_claude 有 LOG_TZ", "LOG_TZ" in js)
    check("run_claude 默认 Asia/Shanghai", "Asia/Shanghai" in js)
    check("run_claude 用 Intl 格式化", "Intl.DateTimeFormat" in js)
    check("run_claude 不再直接用 toISOString 当时间戳",
          "const timestamp = new Date().toISOString()" not in js)

    app = read(os.path.join("control", "app.py"))
    tz_injections = len(re.findall(r'env_vars = \{"TZ": "Asia/Shanghai"\}', app))
    check("create/recreate 都注入 TZ（%d 处）" % tz_injections, tz_injections >= 2)

    compose = read(os.path.join("docker-compose.yml"))
    check("compose control 设了 TZ", re.search(r"^\s*-\s*TZ=Asia/Shanghai", compose, re.M) is not None)


def run_live():
    rc, out, _ = docker("exec", "hermit-control-19080", "date", "+%z")
    check("control 时区 +0800 (%s)" % out, rc == 0 and out == "+0800")

    for card in CARDS:
        rc, out, err = docker("exec", card, "date", "+%z")
        if rc != 0:
            skip("卡片 %s 时区" % card, err[:60] or "not running")
            continue
        check("卡片 %s 时区 +0800 (%s)" % (card, out), out == "+0800")

        rc, out, _ = docker("exec", "-u", "agent", card, "node", "-e",
                            "console.log(new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',"
                            "year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',"
                            "minute:'2-digit',second:'2-digit',hour12:false}).format(new Date()))")
        if rc != 0:
            skip("卡片 %s node 时间" % card, "node unavailable")
            continue
        bj = datetime.now(timezone(timedelta(hours=8)))
        try:
            got = datetime.strptime(out[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            check("卡片 %s node 时间格式 (%r)" % (card, out), False)
            continue
        delta = abs((got - bj.replace(tzinfo=None)).total_seconds())
        check("卡片 %s node 时间与北京时间一致（差 %.0fs）" % (card, delta), delta < 120)


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
