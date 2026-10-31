#!/bin/sh
# 绿联 NAS 部署：ocs（文件/视频托管）+ nas-shell（SSH 运维容器）+ 可选 frpc
# 位置：/mnt/dm-0/.ugreen_nas/137045/dockerImage/{ocs,nas-shell,frp}
# 说明：UGOS 没有 systemctl、没有 docker compose；自启动靠 --restart=always + dockerd 随系统起。
#
# 用法（默认参数 = NAS1 192.168.0.201，只跑 ocs + nas-shell）：
#   sh deploy.sh
# NAS2（192.168.0.202，额外 frp 到阿里云 5080）：
#   NAS_IP=192.168.0.202 PUBLIC_BASE=http://8.130.124.108:5080 ENABLE_FRP=1 sh deploy.sh
set -e

BASE=/mnt/dm-0/.ugreen_nas/137045/dockerImage
IMPORT="${IMPORT_DIR:-$BASE/_import}"
OCS="$BASE/ocs"
SHELL_DIR="$BASE/nas-shell"
FRP_DIR="$BASE/frp"
NAS_IP="${NAS_IP:-192.168.0.201}"
OCS_PORT="${OCS_PORT:-80}"           # 80 = 浏览器输 IP 就能访问（UGOS 自己的界面在 9999）
OCS_PORT_ALT="${OCS_PORT_ALT:-8080}" # 保留 8080，老链接/习惯用法仍可用
SSH_PORT="${SSH_PORT:-2222}"
ENABLE_FRP="${ENABLE_FRP:-0}"
FRP_REMOTE_PORT="${FRP_REMOTE_PORT:-5080}"
FRP_LOCAL_PORT="${FRP_LOCAL_PORT:-$OCS_PORT}"

if [ "$OCS_PORT" = "80" ]; then
    LAN_URL="http://${NAS_IP}"
else
    LAN_URL="http://${NAS_IP}:${OCS_PORT}"
fi
# 对外地址：有公网映射（frp/反代）时用 PUBLIC_BASE，没有就用局域网地址
PUBLIC_BASE="${PUBLIC_BASE:-$LAN_URL}"
PUBLIC_BASE="${PUBLIC_BASE%/}"

echo "== 1. 载入镜像 =="
docker load -i "$IMPORT/ocs-nas.tar.gz" | tail -2
docker load -i "$IMPORT/nas-shell.tar.gz" | tail -2
if [ "$ENABLE_FRP" = "1" ] && [ -f "$IMPORT/frp.tar.gz" ]; then
    docker load -i "$IMPORT/frp.tar.gz" | tail -1
fi

echo "== 2. 准备目录 =="
mkdir -p "$OCS/obs" "$OCS/hls" "$OCS/logs" "$SHELL_DIR/ssh"
chmod 777 "$OCS" "$OCS/obs" "$OCS/hls" "$OCS/logs"
chmod 700 "$SHELL_DIR/ssh"

# 内容目录（obs）的软链接：/obs（宿主根）与存储卷用户目录根（文件管理器可见）
ln -sfn "$OCS/obs" /obs
ln -sfn "$OCS/obs" /mnt/dm-0/.ugreen_nas/137045/obs

echo "== 3. OCS 容器（${OCS_PORT} -> 8082，另挂 ${OCS_PORT_ALT}）=="
echo "   对外地址: $PUBLIC_BASE   局域网: $LAN_URL"
docker rm -f ocs >/dev/null 2>&1 || true
docker run -d --name ocs --restart=always \
  --log-opt max-size=10m --log-opt max-file=3 \
  -p "${OCS_PORT}:8082" \
  -p "${OCS_PORT_ALT}:8082" \
  -e TZ=Asia/Shanghai \
  -e PORT=8082 \
  -e UPLOAD_DIR=/data/obs \
  -e HLS_DIR=/data/hls \
  -e LOG_DIR=/data/logs \
  -e URL_HEAD="$PUBLIC_BASE" \
  -e OCS_LOCAL_BASE="$LAN_URL" \
  -e OCS_FALLBACK_BASE="$PUBLIC_BASE" \
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

if [ "$ENABLE_FRP" = "1" ]; then
    echo "== 5. frpc 容器（本机 ${FRP_LOCAL_PORT} -> 阿里云 ${FRP_REMOTE_PORT}，host 网络）=="
    mkdir -p "$FRP_DIR"
    chmod 777 "$FRP_DIR"
    if [ ! -f "$FRP_DIR/frpc.ini" ]; then
        echo "  [跳过] $FRP_DIR/frpc.ini 不存在（先把配置放进去再跑）"
    else
        docker rm -f frp >/dev/null 2>&1 || true
        docker run -d --name frp --restart=always \
          --network host \
          --log-opt max-size=10m --log-opt max-file=3 \
          -v "$FRP_DIR:/etc/frp" \
          fatedier/frpc:v0.65.0 -c /etc/frp/frpc.ini
        sleep 3
        docker logs --tail 6 frp 2>&1
    fi
fi

echo "== 6. 状态 =="
sleep 3
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
echo '--- ocs 日志 ---'
docker logs --tail 5 ocs 2>&1
echo '--- 重启策略 ---'
for n in ocs nas-shell frp; do
  docker inspect -f "$n: {{.HostConfig.RestartPolicy.Name}}" "$n" 2>/dev/null || true
done
echo '--- 数据目录 ---'
ls -l "$BASE"
