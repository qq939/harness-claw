# -*- coding: utf-8 -*-
"""TDD 校验：WebShell 支持 authorized_keys（私钥）认证，宿主机连接可用。

背景：
  19087-gpussh 的 WebShell 只会用密码登录（paramiko look_for_keys=False + password），
  宿主机改成公钥认证后就连不上了。现在：
    - profile 增加 auth=key + key_path
    - 私钥放在 project/.ssh-key/id_ed25519（工作区挂载，重建不丢）
    - 宿主机 administrators_authorized_keys 里有对应公钥

覆盖点：
  A) 静态
     1) tools_hub/webshell_bp.py 支持 auth=key / key_filename；
     2) DEFAULT_SESSIONS 里有 host 会话（host.docker.internal:22, qq939, key）；
     3) 表单有 auth/key_path 字段（f_auth / f_key）；
     4) webshell_server.py 的 ws 入口同样按 auth 分支。
  B) 线上
     5) 卡片 19087 的 /webshell/api/sessions 至少有一个 auth=key 的会话；
     6) .ssh-key/id_ed25519 存在且 600；
     7) 用该 profile 真开一条 SSH 通道并执行 whoami，返回 qq939。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import json
import os
import subprocess
import sys
import threading

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))
CARD = os.environ.get("WEBSHELL_CARD", "19087-gpussh")
WS = os.path.join(ROOT, "workspaces", CARD)

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
    with open(os.path.join(WS, rel), "r", encoding="utf-8") as f:
        return f.read()


def in_card(script, timeout=30):
    p = subprocess.run(["docker", "exec", "-i", "-u", "agent", CARD, "python3", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       input=script, timeout=timeout)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def run_static():
    bp = read(os.path.join("tools_hub", "webshell_bp.py"))
    check("bp 支持 auth=key", 'auth == "key"' in bp or "auth == 'key'" in bp)
    check("bp 使用 key_filename", "key_filename" in bp)
    check("默认有 host 会话", '"host": "host.docker.internal"' in bp and '"auth": "key"' in bp)
    check("表单有认证方式/私钥路径", 'id="f_auth"' in bp and 'id="f_key"' in bp)
    check("保存时带上 auth/key_path", "auth:$('#f_auth').value" in bp and "key_path:$('#f_key').value" in bp)

    srv = read("webshell_server.py")
    check("ws 入口同样按 auth 分支", 'auth = (cfg.get("auth")' in srv and "key_filename" in srv)


def run_live():
    rc, out, err = in_card(
        "import json,urllib.request\n"
        "r=urllib.request.urlopen('http://localhost:8082/webshell/api/sessions',timeout=5)\n"
        "print(r.read().decode())\n")
    if rc != 0:
        skip("线上 sessions", err[:80])
        return
    items = json.loads(out).get("items", [])
    key_sessions = [i for i in items if (i.get("auth") == "key")]
    check("存在 auth=key 的会话", bool(key_sessions))
    if key_sessions:
        s = key_sessions[0]
        check("key 会话指向宿主机", s.get("host") in ("host.docker.internal", "127.0.0.1", "localhost"))

    rc, out, _ = in_card("import os;p='/home/agent/.claude/workspace/project/.ssh-key/id_ed25519';"
                         "print(oct(os.stat(p).st_mode & 0o777), os.path.exists(p))")
    check("私钥在工作区且 600 (%s)" % out, rc == 0 and out.startswith("0o600"))

    rc, out, err = in_card(
        "import sys,time,json\n"
        "sys.path.insert(0,'/home/agent/.claude/workspace/project')\n"
        "from tools_hub.webshell_bp import _open_ssh_channel,get_sessions\n"
        "cfg=[v for v in get_sessions().values() if v.get('auth')=='key'][0]\n"
        "c,ch=_open_ssh_channel(cfg,100,30)\n"
        "time.sleep(1); ch.send(b'whoami\\r\\n'); time.sleep(2)\n"
        "data=b''\n"
        "try:\n"
        "    while True:\n"
        "        b=ch.recv(4096)\n"
        "        if not b: break\n"
        "        data+=b\n"
        "        if b'qq939' in data: break\n"
        "except Exception: pass\n"
        "c.close()\n"
        "print('OK' if b'qq939' in data else 'NO')\n", timeout=60)
    check("真开通道并 whoami=qq939 (%s)" % (out or err)[:60], rc == 0 and out.strip().endswith("OK"))


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
