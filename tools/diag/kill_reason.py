#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判断某张卡片上次是被「超时杀」还是「OOM 杀」（或外部 kill）。

用法：
    py -3 tools/diag/kill_reason.py 19109-19109-html-viewer
    py -3 tools/diag/kill_reason.py 19109              # 前缀也行

判据（三条互相印证）：
    1. 卡片日志 logs/agent_tui.log
         [TIMEOUT] ... after Nh（已运行 Xs）  → 超时杀（X ≈ N 小时）
         [OOM] / [KILLED] ...                → 新版本 run_claude.js 写的取证行
         只有光秃秃一行 "Killed"             → 老版本没取证，需要看下面两条
    2. 容器 cgroup：/sys/fs/cgroup/memory.events 的 oom_kill 计数
         >0 → 容器内存超限（通常是 mem_limit 到顶）
    3. docker inspect：State.OOMKilled / ExitCode
         true / 137 → 容器级 OOM
        false 且 cgroup oom_kill=0 且 memory.max=max（无限制）→ 不是容器 OOM，
        多半是宿主机内存不足被内核杀，或有人 kill -9
"""
import json
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def sh(args, timeout=30):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def find_container(prefix):
    rc, out = sh(["docker", "ps", "-a", "--format", "{{.Names}}"])
    names = [n.strip() for n in out.splitlines() if n.strip()]
    for n in names:
        if n == prefix:
            return n
    for n in names:
        if n.startswith(prefix):
            return n
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    name = find_container(sys.argv[1])
    if not name:
        print(f"找不到容器：{sys.argv[1]}")
        return 1
    print(f"容器：{name}")

    rc, out = sh(["docker", "inspect", name, "--format",
                  "oom={{.State.OOMKilled}} exit={{.State.ExitCode}} "
                  "started={{.State.StartedAt}} restarts={{.RestartCount}} "
                  "mem={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}}"])
    print("inspect:", out.strip())

    rc, cg = sh(["docker", "exec", name, "sh", "-c",
                 "cat /sys/fs/cgroup/memory.events 2>/dev/null; "
                 "echo '--- peak ---'; cat /sys/fs/cgroup/memory.peak 2>/dev/null; "
                 "echo '--- max ---'; cat /sys/fs/cgroup/memory.max 2>/dev/null"])
    oom_kill = 0
    m = re.search(r"^oom_kill\s+(\d+)", cg, re.M)
    if m:
        oom_kill = int(m.group(1))
    peak = re.search(r"--- peak ---\s*(\S+)", cg)
    limit = re.search(r"--- max ---\s*(\S+)", cg)
    print(f"cgroup: oom_kill={oom_kill} peak={peak.group(1) if peak else '?'} limit={limit.group(1) if limit else '?'}")

    rc, log = sh(["docker", "exec", name, "sh", "-c",
                  "tail -400 /home/agent/.claude/workspace/project/logs/agent_tui.log 2>/dev/null"])
    timeouts = re.findall(r"^\[TIMEOUT\].*$", log, re.M)
    ooms = re.findall(r"^\[OOM\].*$", log, re.M)
    killed = re.findall(r"^\[KILLED\].*$", log, re.M)
    bare = re.findall(r"^Killed\s*$", log, re.M)

    print("\n--- 日志取证 ---")
    if timeouts:
        print("TIMEOUT:", timeouts[-1].strip())
    if ooms:
        print("OOM    :", ooms[-1].strip())
    if killed:
        print("KILLED :", killed[-1].strip())
    if bare:
        print(f"裸 Killed 行: {len(bare)} 次（老版本没有取证行）")

    # 时间间隔：找最后一条 "$ 消息" 的时间戳与随后的 Killed 之间差多久
    stamps = re.findall(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] \$ ", log, re.M)
    print(f"最后一条消息时间：{stamps[-1] if stamps else '(无)'}")

    print("\n--- 结论 ---")
    verdict = "证据不足：日志里没有 TIMEOUT/OOM/KILLED 行，容器也没重启记录"
    if timeouts:
        verdict = "超时杀（日志有 [TIMEOUT]，且已运行时长 ≈ 配置的超时时间）"
    elif ooms:
        verdict = "容器 OOM 杀（cgroup oom_kill 增长）"
    elif oom_kill > 0:
        verdict = f"容器 OOM 杀（cgroup oom_kill={oom_kill}）"
    elif killed or bare:
        if "max" in (limit.group(1) if limit else "") or "0" == (limit.group(1) if limit else ""):
            verdict = ("非容器 OOM：cgroup oom_kill=0 且容器没有内存上限 → "
                       "多半是宿主机内存不足被内核杀，或外部 kill -9（要定死请看宿主机 dmesg）")
        else:
            verdict = "非超时 SIGKILL，但 cgroup 没记 oom_kill → 优先怀疑宿主机 OOM / 外部 kill"
    print(verdict)

    # 卡片 app 自带的硬超时（常见于 server.js / app.py 里 setTimeout+kill）
    rc, app = sh(["docker", "exec", name, "sh", "-c",
                  "cd /home/agent/.claude/workspace/project 2>/dev/null && "
                  "grep -nE \"kill\\('SIGKILL'\\)|[0-9]+ \\* 60 \\* 1000\" *.js *.py 2>/dev/null | head -10"])
    if app.strip():
        print("\n--- 卡片 app 自带的强杀点（小于 48h 的都要改）---")
        for line in app.strip().splitlines():
            print(" ", line.strip())

    # 宿主机侧补充信息
    print("\n--- 宿主机侧 ---")
    rc, info = sh(["docker", "info", "--format", "{{.MemTotal}}"])
    if rc == 0:
        try:
            print(f"Docker VM 内存: {int(info.strip())/1024/1024/1024:.1f} GB")
        except Exception:
            print("Docker VM 内存:", info.strip())
    rc, ev = sh(["docker", "events", "--since", "24h", "--until", "1s",
                 "--filter", "event=oom", "--filter", f"container={name}", "--format", "{{.Time}} {{.Action}}"],
                timeout=20)
    print("docker oom 事件(24h):", ev.strip() or "(无)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
