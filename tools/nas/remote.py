#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绿联 NAS 运维小工具（paramiko）：run/put/get。

用法：
    py -3 tools/nas/remote.py run "docker ps"
    py -3 tools/nas/remote.py put 本地文件 /远程路径
    py -3 tools/nas/remote.py get /远程文件 本地路径

连接参数走环境变量：
    NAS_HOST=192.168.0.201  NAS_PORT=922  NAS_USER=root  NAS_PASS=...
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import paramiko

HOST = os.environ.get("NAS_HOST", "192.168.0.201")
PORT = int(os.environ.get("NAS_PORT", "922"))
USER = os.environ.get("NAS_USER", "root")
PASS = os.environ.get("NAS_PASS", "")


def connect(timeout=15):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS,
              timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
              look_for_keys=False, allow_agent=False)
    return c


def run(cmd, timeout=600):
    c = connect()
    try:
        _in, stdout, stderr = c.exec_command(cmd, timeout=timeout, get_pty=False)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        return rc, out, err
    finally:
        c.close()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    if action == "run":
        rc, out, err = run(sys.argv[2] if len(sys.argv) > 2 else "true")
        sys.stdout.write(out)
        if err:
            sys.stderr.write(err)
        print(f"\n[exit {rc}]")
        return rc
    if action in ("put", "get"):
        c = connect()
        try:
            sftp = c.open_sftp()
            src, dst = sys.argv[2], sys.argv[3]
            if action == "put":
                sftp.put(src, dst)
            else:
                sftp.get(dst, src)
            sftp.close()
            print(f"{action} ok: {src} -> {dst}")
            return 0
        finally:
            c.close()
    print("unknown action", action)
    return 2


if __name__ == "__main__":
    sys.exit(main())
