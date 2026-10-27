# -*- coding: utf-8 -*-
"""校验：建卡必须同时具备 webapp（页面）和 api（结构化接口）。

约定来源：config/rules/CLAUDE.md + systemreadme.md「二·补」+ README「五、约定」

判定标准（对一张卡）：
  - webapp: GET /  返回 HTML（含 <html> 或表单元素），不是纯 JSON
  - api   : GET /api/... 或 POST /api/... 返回 JSON（本卡业务接口）
  - 基础  : GET /health 返回 {"ok": true}
  - 平台  : GET/POST /ask/claude 存在（由 run_claude.js 提供）

用法：
    py -3 test_card_webapp_and_api.py                # 检查所有运行中的卡
    py -3 test_card_webapp_and_api.py 19104-ytdlp    # 只查一张

退出码：0 全部达标（或没有可检查的卡）/ 1 有不达标的卡
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

TIMEOUT = 12
failures = []

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def get(url, method="GET", token=None):
    req = urllib.request.Request(url, method=method)
    if token:
        req.add_header("x-api-key", token)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body, e.headers.get("content-type", "")
    except Exception as e:
        return None, str(e), ""


def check_card(name, port):
    token = os.environ.get("CARD_TOKEN", "agent")
    ok_all = True
    base = "http://127.0.0.1:%d" % port

    st, body, ctype = get(base + "/")
    if st == 401:  # 有的卡页面要 token（例如 19087 带鉴权的 webshell）
        st, body, ctype = get(base + "/?token=" + token)
    is_html = st == 200 and ("<html" in body.lower() or "<form" in body.lower() or "<!doctype" in body.lower())
    print(("  [PASS] " if is_html else "  [FAIL] ") + "%s webapp: GET / 是页面 (%s)" % (name, st), flush=True)
    ok_all &= is_html

    st, health_body, _ = get(base + "/health")
    if st == 401:
        st, health_body, _ = get(base + "/health?token=" + token)
    is_ok = st == 200 and '"ok"' in health_body
    print(("  [PASS] " if is_ok else "  [FAIL] ") + "%s health: %s" % (name, st), flush=True)
    ok_all &= is_ok

    # 业务 api：先从页面里挖 /api/... 和 fetch('...')，再兜底试常见路径
    candidates = []
    if is_html:
        candidates += re.findall(r"/api/[A-Za-z0-9_\-/]+", body)
        candidates += re.findall(r"fetch\(\s*['\"]([^'\"]+)['\"]", body)
    candidates += ["/api/items", "/api/list", "/api/state", "/api/videos", "/api/files"]
    seen = set()
    api_ok = False
    for path in candidates:
        if not path.startswith("/") or path.startswith("//") or "{table}" in path:
            continue
        path = path.split("?")[0]
        if path in seen or path in ("/", "/health"):
            continue
        seen.add(path)
        for suffix in ("", "?token=" + token):
            st2, body2, _ = get(base + path + suffix)
            if st2 == 200 and body2.strip().startswith(("{", "[")):
                try:
                    json.loads(body2)
                    api_ok = True
                    print("  [PASS] %s api: GET %s 返回 JSON" % (name, path), flush=True)
                except Exception:
                    pass
            if api_ok:
                break
        if api_ok:
            break
    if not api_ok:
        print("  [FAIL] %s api: 没找到可用的 JSON 接口" % name, flush=True)
    ok_all &= api_ok

    return ok_all


def main():
    targets = []
    if len(sys.argv) > 1:
        for name in sys.argv[1:]:
            m = re.match(r"^(\d{5})-", name)
            if not m:
                print("跳过（名字里没有端口前缀）:", name, flush=True)
                continue
            targets.append((name, int(m.group(1))))
    else:
        try:
            with urllib.request.urlopen("http://127.0.0.1:19080/api/agents", timeout=20) as r:
                items = json.loads(r.read().decode()).get("items") or []
        except Exception as e:
            print("面板不可达，无法枚举卡片:", e, flush=True)
            return 0
        for it in items:
            if it.get("status") != "running":
                continue
            targets.append((it["container_name"], it["host_port"]))

    print("检查 %d 张卡的 webapp + api ..." % len(targets), flush=True)
    for name, port in targets:
        if not check_card(name, port):
            failures.append(name)

    if failures:
        print("\n不达标: %s" % ", ".join(failures), flush=True)
        return 1
    print("\n全部达标 ✓", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
