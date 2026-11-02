#!/bin/sh
# 绿联 NAS 部署：ocs（文件/视频托管）+ nas-shell（SSH 运维容器）+ 可选 frpc
# 数据位置：<数据卷>/.ugreen_nas/137045/dockerImage/{ocs,nas-shell,frp}
# 说明：UGOS 没有 systemctl、没有 docker compose；自启动靠 --restart=always + dockerd 随系统起。
#
# 重要：UGOS 的 /mnt/dm-0、/mnt/dm-1 会随插拔/新建存储池**互换**（实测 NAS2 加了新盘后
# 数据卷从 dm-0 变成了 dm-1，容器还绑在 dm-0 就变成空目录，表现为"文件都不见了"）。
# 所以这里默认按 /mnt/media_rw/<卷UUID> 找「已经有 ocs 数据的那个卷」，不再写死 dm-0。
# 需要强制指定时传 DATA_ROOT=/mnt/media_rw/<uuid>/.ugreen_nas/137045
#
# 用法（默认参数 = NAS1 192.168.0.201，只跑 ocs + nas-shell）：
#   sh deploy.sh
# NAS2（192.168.0.202，额外 frp 到阿里云 5080）：
#   NAS_IP=192.168.0.202 PUBLIC_BASE=https://oas.dimond.top SITE_NAME=oas ENABLE_FRP=1 sh deploy.sh
set -e

DATA_ROOT="${DATA_ROOT:-}"
if [ -z "$DATA_ROOT" ]; then
    # 在 /mnt/media_rw/*/.ugreen_nas/137045 里挑「ocs 数据最多的那个卷」
    _best=""
    _best_n=-1
    for _d in /mnt/media_rw/*/.ugreen_nas/137045; do
        [ -d "$_d/dockerImage/ocs" ] || continue
        _n=$(ls -1 "$_d/dockerImage/ocs/obs" 2>/dev/null | wc -l)
        if [ "$_n" -gt "$_best_n" ]; then _best="$_d"; _best_n="$_n"; fi
    done
    if [ -n "$_best" ]; then
        DATA_ROOT="$_best"
    else
        DATA_ROOT=/mnt/dm-0/.ugreen_nas/137045
    fi
fi
echo "== 0. 数据卷: $DATA_ROOT =="

BASE="$DATA_ROOT/dockerImage"
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
SITE_NAME="${SITE_NAME:-文件托管服务}"

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
ln -sfn "$OCS/obs" "$DATA_ROOT/obs"

echo "== 3. OCS 容器（${OCS_PORT} -> 8082，另挂 ${OCS_PORT_ALT}）=="
echo "   对外地址: $PUBLIC_BASE   局域网: $LAN_URL   站点名: $SITE_NAME"
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
  -e SITE_NAME="$SITE_NAME" \
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
