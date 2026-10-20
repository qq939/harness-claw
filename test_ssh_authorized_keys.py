# -*- coding: utf-8 -*-
"""TDD 校验：平台公钥写进卡片的 ~/.ssh/authorized_keys（免密 SSH）。

背景：
  卡片里原本只有密码登录（agent/agent），没有 authorized_keys。
  现在把平台公钥放在 config/ssh/authorized_keys，新建/重建卡片时合并进容器，
  运行中的卡片也已补写。

  坑：sshd 是 StrictModes yes —— 目录 700、文件 600、属主 agent，
  任何一项不对都会静默忽略（不报错，只是登不上）。

覆盖点：
  A) 静态
     1) config/ssh/authorized_keys 存在且是合法公钥行；
     2) control 有 ensure_authorized_keys，并在 scp_rules_to_container 里被调用
        （新建/重建/修复都会走到这个入口）。
  B) 线上
     3) 抽查运行中的卡片：~/.ssh 700、authorized_keys 600、属主 agent；
     4) 文件里包含平台公钥；ssh-keygen -l 能解析出指纹（格式合法）。

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import re
import subprocess
import sys
import threading

TIMEOUT_SECONDS = 120
ROOT = os.path.dirname(os.path.abspath(__file__))
CARDS = os.environ.get("SSH_CHECK_CARDS", "19091-picturetext,19085-git,19081-hub").split(",")
KEY_FILE = os.path.join(ROOT, "config", "ssh", "authorized_keys")

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


def docker(*args, timeout=30):
    p = subprocess.run(["docker", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def platform_keys():
    with open(KEY_FILE, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def run_static():
    check("平台公钥文件存在", os.path.isfile(KEY_FILE))
    keys = platform_keys() if os.path.isfile(KEY_FILE) else []
    check("公钥行格式合法", bool(keys) and all(re.match(r"^(ssh-ed25519|ssh-rsa|ecdsa-)", k) for k in keys))

    app = open(os.path.join(ROOT, "control", "app.py"), "r", encoding="utf-8").read()
    check("control 有 ensure_authorized_keys", "def ensure_authorized_keys(" in app)
    check("在 scp_rules_to_container 里被调用",
          re.search(r"def scp_rules_to_container\([^)]*\):\s*\n(?:.*\n){0,6}?\s*ensure_authorized_keys\(", app) is not None)
    check("权限按 StrictModes 设置", "chmod 700 ~/.ssh" in app and "chmod 600 ~/.ssh/authorized_keys" in app)


def run_live():
    keys = platform_keys() if os.path.isfile(KEY_FILE) else []
    if not keys:
        skip("线上公钥检查", "no platform key")
        return
    ident = " ".join(keys[0].split()[:2])

    for card in CARDS:
        rc, out, err = docker("exec", "-u", "agent", card, "stat", "-c", "%a %U", "/home/agent/.ssh")
        if rc != 0:
            skip("卡片 %s" % card, err[:60] or "not running")
            continue
        check("%s .ssh 700 agent (%s)" % (card, out), out == "700 agent")

        rc, out, _ = docker("exec", "-u", "agent", card, "stat", "-c", "%a %U", "/home/agent/.ssh/authorized_keys")
        check("%s authorized_keys 600 agent (%s)" % (card, out), out == "600 agent")

        rc, out, _ = docker("exec", "-u", "agent", card, "grep", "-cF", ident, "/home/agent/.ssh/authorized_keys")
        check("%s 含平台公钥" % card, rc == 0 and out.strip() == "1")

        rc, out, _ = docker("exec", "-u", "agent", card, "ssh-keygen", "-l", "-f", "/home/agent/.ssh/authorized_keys")
        check("%s 指纹可解析 (%s)" % (card, out[:48]), rc == 0 and "SHA256:" in out)


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
