#!/bin/sh
# 绿联 NAS（192.168.0.201）部署：ocs（文件/视频托管）+ nas-shell（SSH 运维容器）
# 位置：/mnt/dm-0/.ugreen_nas/137045/dockerImage/{ocs,nas-shell}
# 说明：UGOS 没有 systemctl、没有 docker compose；自启动靠 --restart=always + dockerd 随系统起，
#       再用 keepalive.sh（cron 每分钟）兜底，因为 UGOS 的 dockerd 不会在容器自己退出后按策略重启。
set -e

BASE=/mnt/dm-0/.ugreen_nas/137045/dockerImage
IMPORT="$BASE/_import"
OCS="$BASE/ocs"
SHELL_DIR="$BASE/nas-shell"
NAS_IP="${NAS_IP:-192.168.0.201}"
OCS_PORT="${OCS_PORT:-8080}"
SSH_PORT="${SSH_PORT:-2222}"
BASE_URL="http://${NAS_IP}:${OCS_PORT}"

echo "== 1. 载入镜像 =="
docker load -i "$IMPORT/ocs-nas.tar.gz" | tail -2
docker load -i "$IMPORT/nas-shell.tar.gz" | tail -2

echo "== 2. 准备目录 =="
mkdir -p "$OCS/obs" "$OCS/hls" "$OCS/logs" "$SHELL_DIR/ssh"
chmod 777 "$OCS" "$OCS/obs" "$OCS/hls" "$OCS/logs"
chmod 700 "$SHELL_DIR/ssh"

echo "== 3. OCS 容器（${OCS_PORT} -> 8082）=="
docker rm -f ocs >/dev/null 2>&1 || true
docker run -d --name ocs --restart=always \
  --log-opt max-size=10m --log-opt max-file=3 \
  -p "${OCS_PORT}:8082" \
  -e TZ=Asia/Shanghai \
  -e PORT=8082 \
  -e UPLOAD_DIR=/data/obs \
  -e HLS_DIR=/data/hls \
  -e LOG_DIR=/data/logs \
  -e URL_HEAD="$BASE_URL" \
  -e OCS_LOCAL_BASE="$BASE_URL" \
  -e OCS_FALLBACK_BASE="$BASE_URL" \
  -v "$OCS:/data" \
  -v /etc/localtime:/etc/localtime:ro \
  ocs-nas:latest

echo "== 4. SSH 运维容器（${SSH_PORT} -> 22）=="
# --privileged --pid=host：容器里的 hostshell 用 nsenter 进宿主命名空间（等价 UGOS 的 root shell）
docker rm -f nas-shell >/dev/null 2>&1 || true
docker run -d --name nas-shell --restart=always \
  --privileged --pid=host \
  --log-opt max-size=10m --log-opt max-file=3 \
  -p "${SSH_PORT}:22" \
  -e TZ=Asia/Shanghai \
  -v "$SHELL_DIR:/data" \
  -v "$SHELL_DIR/ssh:/root/.ssh" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /:/host \
  -v /mnt/dm-0:/mnt/dm-0 \
  -v /etc/localtime:/etc/localtime:ro \
  nas-shell:latest

echo "== 5. 状态 =="
sleep 4
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
echo '--- ocs 日志 ---'
docker logs --tail 6 ocs 2>&1
echo '--- nas-shell 日志 ---'
docker logs --tail 4 nas-shell 2>&1
echo '--- 重启策略 ---'
for n in ocs nas-shell; do
  echo "$n: $(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' $n)"
done
