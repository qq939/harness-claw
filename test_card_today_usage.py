# -*- coding: utf-8 -*-
"""TDD 校验：面板每张卡片显示「今日花费」（人民币，按 DeepSeek 分时价折算）。

为什么这样做：
  面板以前完全看不到 token 花在哪，只能事后钻进容器数 jsonl。
  现在 control 起一个后台线程（每 5 分钟）在卡片容器里扫今天的会话 usage，
  按官方分时价折算成人民币，塞进 /api/agents 的 today_cost，卡片标题行显示。

价格（官方页，元/百万 tokens）：
  输入·缓存命中 0.02(谷)/0.04(峰)；输入·未命中 1(谷)/2(峰)；输出 4(谷)/8(峰)
  峰时 = 北京时间周一至周五 9:00-12:00、14:00-18:00

覆盖点：
  A) 静态
     1) control/app.py 有 USAGE_SCAN_JS / scan_card_usage / _usage_refresh_loop；
     2) 价格常量齐全（0.02/0.04/1/2/4/8）；
     3) format_item 输出 today_cost；前端有 cost-badge 与「今日 ¥」；
     4) 扫描脚本只读不写（不含 writeFile / unlink / rm）。
  B) 线上
     5) /api/agents 每张卡都带 today_cost 字段（None 或数字）；
     6) 花费落在价格区间内：fresh*1+cached*0.02+out*4 <= cost*1e6 <= fresh*2+cached*0.04+out*8；
     7) 与容器内直接跑同一段脚本的结果一致（±0.05 元）；
     8) 今天确实有流量的卡（19091）cost > 0，否则 SKIP 不算失败。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request

TIMEOUT_SECONDS = 180
ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(ROOT, "control", "app.py")
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:19080")
ACTIVE_CARD = os.environ.get("USAGE_CARD", "19091-picturetext")

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


def extract_js(src):
    m = re.search(r'USAGE_SCAN_JS = r"""(.*?)"""', src, re.S)
    return m.group(1) if m else ""


def http_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def run_static():
    src = read(os.path.join("control", "app.py"))
    js = extract_js(src)
    check("USAGE_SCAN_JS exists", len(js) > 500)
    check("scan_card_usage defined", "def scan_card_usage(" in src)
    check("refresh loop defined", "_usage_refresh_loop" in src and "USAGE_REFRESH_SECONDS" in src)
    check("loop started as daemon thread", "threading.Thread(target=_usage_refresh_loop, daemon=True)" in src)
    check("format_item exposes today_cost", '"today_cost"' in src)
    check("frontend badge rendered", 'cost-badge' in src and '今日 ¥' in src)
    for price in ("0.02", "0.04", "?2:1", "?8:4"):
        check("price present: %s" % price, price in js)
    check("scan script is read-only", not re.search(r"writeFile|unlink|rmSync|appendFile", js))
    check("scan skips files not touched today", "mtimeMs<dayStart" in js)


def run_live():
    items = http_json(CONTROL + "/api/agents").get("items") or []
    check("agents returned", len(items) > 0)
    check("every card carries today_cost key", all("today_cost" in it for it in items))

    bad = []
    for it in items:
        u = it.get("today_usage")
        if not u or not it.get("today_cost"):
            continue
        fresh, cached, out, cost = u.get("fresh", 0), u.get("cached", 0), u.get("out", 0), it["today_cost"]
        lo = (fresh * 1 + cached * 0.02 + out * 4) / 1e6
        hi = (fresh * 2 + cached * 0.04 + out * 8) / 1e6
        if not (lo - 0.01 <= cost <= hi + 0.01):
            bad.append((it["container_name"], cost, round(lo, 2), round(hi, 2)))
    check("cost stays within peak/idle price band", not bad)
    if bad:
        print("   -> %r" % bad, flush=True)

    card = next((it for it in items if it["container_name"] == ACTIVE_CARD), None)
    if card is None:
        skip("active card present", ACTIVE_CARD + " not found")
        return
    api_cost = card.get("today_cost")

    js = extract_js(read(os.path.join("control", "app.py")))
    p = subprocess.run(["docker", "exec", "-i", "-u", "agent", ACTIVE_CARD, "node", "-"],
                       capture_output=True, input=js.encode("utf-8"), timeout=90)
    out = p.stdout.decode("utf-8", "replace").strip().splitlines()
    direct = None
    for line in reversed(out):
        try:
            direct = json.loads(line)
            break
        except Exception:
            continue
    check("container-side scan returns JSON", isinstance(direct, dict) and "cost" in (direct or {}))

    if isinstance(direct, dict) and api_cost is not None:
        delta = abs(float(direct["cost"]) - float(api_cost))
        check("API cost matches container-side scan (delta %.2f)" % delta, delta <= 0.05)
    if direct:
        if direct["turns"] > 0:
            check("active card spent money today", float(direct["cost"]) > 0)
        else:
            skip("active card spent money today", "no traffic today")


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
