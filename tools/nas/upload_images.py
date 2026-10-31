#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把本地构建好的镜像 tar.gz 传到 NAS（走 922 的 SSH，局域网 ~90MB/s）。

用法（在仓库根目录）：
    py -3 tools/nas/upload_images.py                 # 传 tmp/ocs-nas.tar.gz 和 tmp/nas-shell.tar.gz
    py -3 tools/nas/upload_images.py --only ocs     # 只传一个
"""
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remote import connect  # noqa: E402

REMOTE_DIR = os.environ.get("NAS_IMPORT_DIR", "/mnt/dm-0/.ugreen_nas/137045/dockerImage/_import")
IMAGES = {"ocs": "tmp/ocs-nas.tar.gz", "shell": "tmp/nas-shell.tar.gz", "frp": "tmp/frpc.tar.gz"}


def upload(sftp, local, remote):
    size = os.path.getsize(local)
    t0 = time.time()
    last = [0.0]

    def cb(done, total):
        now = time.time()
        if now - last[0] < 2 and done < total:
            return
        last[0] = now
        mb = done / 1048576.0
        print(f"  {os.path.basename(local)}: {done*100.0/total:5.1f}%  {mb:.1f}/{total/1048576:.1f} MB  "
              f"{mb/max(now-t0,0.001):.1f} MB/s", flush=True)

    print(f"上传 {local} -> {remote} ({size/1048576:.1f} MB)", flush=True)
    sftp.put(local, remote, callback=cb, confirm=True)
    print("  完成", flush=True)


def main():
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    c = connect()
    try:
        sftp = c.open_sftp()
        sftp.get_channel().settimeout(120)
        for key, local in IMAGES.items():
            if only and only != key:
                continue
            if not os.path.exists(local):
                print(f"跳过（不存在）：{local}")
                continue
            upload(sftp, local, f"{REMOTE_DIR}/{os.path.basename(local)}")
        sftp.close()
    finally:
        c.close()


if __name__ == "__main__":
    main()
