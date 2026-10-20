# -*- coding: utf-8 -*-
"""TDD 校验：GitHub 远程仓库命名规则（必须以 harness 开头）。

背景：
  项目从 hermit 改名 harness 后，GitHub 仓库还叫 hermit-claw，和规则不一致。
  现在约定：任何远程仓库名（owner/repo 的 repo 部分）必须以 harness 开头，
  形如 harness-xxx；新建时照此命名，已有仓库改名后 git remote set-url。

覆盖点：
  A) 规则落到四个地方（缺一个 agent 就可能不照做）
     1) config/rules/CLAUDE.md（平台级提示词，所有卡片都读）
     2) config/rules/systemreadme.md（四、Git 规范）
     3) config/claude/skills/harness-git/SKILL.md（提交规范 skill）
     4) github skill（config/claude/skills/github 与 tools/github 两份）
  B) github skill 里不能再有别人机器上的硬编码路径 /Users/jimjiang
  C) 线上
     5) 本仓库 origin 的 repo 名以 harness 开头
     6) tools/github/scripts/check_repo_name.sh 对本仓库返回 0
     7) 对不合规的临时仓库返回 1（反向用例）

超时机制：整个校验在守护线程中执行，主线程 join(timeout)，超时判失败。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

TIMEOUT_SECONDS = 90
ROOT = os.path.dirname(os.path.abspath(__file__))

failures = []

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check(name, ok):
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)
    if not ok:
        failures.append(name)


def read(rel):
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as f:
        return f.read()


def remote_repo_name(url):
    name = url.strip().rstrip("/").split("/")[-1]
    return name[:-4] if name.endswith(".git") else name


def run_static():
    claude_md = read(os.path.join("config", "rules", "CLAUDE.md"))
    check("CLAUDE.md 写明 harness 开头", "远程仓库名必须以 `harness` 开头" in claude_md)

    readme = read(os.path.join("config", "rules", "systemreadme.md"))
    check("systemreadme 有命名规则", "must" not in readme and "必须以 `harness` 开头" in readme)
    check("systemreadme 有自检命令", "git remote get-url origin" in readme and "grep -q '^harness'" in readme)

    git_skill = read(os.path.join("config", "claude", "skills", "harness-git", "SKILL.md"))
    check("harness-git skill 有命名规则", "远程仓库命名（硬性）" in git_skill and "harness-新名" in git_skill)

    for rel in (os.path.join("config", "claude", "skills", "github", "SKILL.md"),
                os.path.join("tools", "github", "SKILL.md")):
        text = read(rel)
        check("%s 有命名规则" % rel, "远程仓库名必须以 `harness` 开头" in text)
        check("%s 无硬编码他人路径" % rel, "/Users/jimjiang" not in text)
        check("%s load_env 用可移植路径" % rel, "GITHUB_SKILL_DIR" in text)

    check("检查脚本存在", os.path.isfile(os.path.join(ROOT, "tools", "github", "scripts", "check_repo_name.sh")))


def bash_exe():
    """Windows 上 bash 常被 WSL 抢走（路径会被转成 C:Users...），优先 Git Bash。"""
    for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"):
        if os.path.isfile(p):
            return p
    return shutil.which("bash") or "bash"


def posix(path):
    return path.replace("\\", "/") if os.name == "nt" else path


def run_live():
    url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT,
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20).stdout.strip()
    name = remote_repo_name(url)
    check("origin 以 harness 开头 (%s)" % name, name.startswith("harness"))

    script = os.path.join(ROOT, "tools", "github", "scripts", "check_repo_name.sh")
    bash = bash_exe()
    p = subprocess.run([bash, posix(script)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    check("check_repo_name.sh 对本仓库通过", p.returncode == 0)
    if p.returncode != 0:
        print("   -> %s%s" % (p.stdout, p.stderr), flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=False)
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/acme/legacy-proj.git"],
                       cwd=tmp, check=False)
        p2 = subprocess.run([bash, posix(script)], cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        check("check_repo_name.sh 对不合规仓库返回 1", p2.returncode == 1)


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
    print("ALL CHECKS PASSED", flush=True)
    sys.exit(0)
