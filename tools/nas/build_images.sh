#!/bin/sh
# 在 Windows/Linux 开发机上构建两个 NAS 用的镜像并打包成可离线导入的 tar.gz
# 产物：tmp/ocs-nas.tar.gz、tmp/nas-shell.tar.gz（tools/nas/upload_images.py 负责传到 NAS）
set -e

REPO=$(cd "$(dirname "$0")/../.." && pwd)
IMG="$REPO/tools/nas/image"
TMP="$REPO/tmp"
mkdir -p "$TMP"

# nas-shell 需要静态 docker CLI（容器里直接管理 NAS 上的容器）
if [ ! -f "$IMG/docker" ]; then
    echo "下载静态 docker CLI ..."
    curl -sSL -o "$TMP/docker-static.tgz" https://download.docker.com/linux/static/stable/x86_64/docker-27.3.1.tgz
    tar -xzf "$TMP/docker-static.tgz" -C "$TMP" docker/docker
    cp "$TMP/docker/docker" "$IMG/docker"
    rm -rf "$TMP/docker" "$TMP/docker-static.tgz"
fi

# OCS 源码（与卡片同一份）
if [ ! -d "$TMP/nas-ocs/src" ]; then
    git clone -q -b ocs --depth 1 https://github.com/qq939/obs.git "$TMP/nas-ocs"
else
    git -C "$TMP/nas-ocs" pull -q --ff-only || true
fi

echo "== 构建 ocs-nas =="
docker build -t ocs-nas:latest -f "$IMG/Dockerfile.ocs" "$TMP/nas-ocs"

echo "== 构建 nas-shell =="
docker build -t nas-shell:latest -f "$IMG/Dockerfile" "$IMG"

# 导出：必须用 docker save -o（不要走 | gzip > 的文本管道，二进制会被写坏）
py -3 - <<'PY'
import gzip, os, shutil, subprocess
for name in ("ocs-nas", "nas-shell"):
    tar = f"tmp/{name}.tar"
    gz = f"tmp/{name}.tar.gz"
    subprocess.check_call(["docker", "save", "-o", tar, f"{name}:latest"])
    if os.path.exists(gz):
        os.remove(gz)
    with open(tar, "rb") as fi, gzip.open(gz, "wb", compresslevel=1) as fo:
        shutil.copyfileobj(fi, fo, 8 << 20)
    os.remove(tar)
    print(name, os.path.getsize(gz) // 1048576, "MB")
PY
