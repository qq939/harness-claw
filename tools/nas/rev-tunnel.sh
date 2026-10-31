#!/bin/sh
# 可选：把 NAS 上这个容器的 22 端口反向打到一台跳板机（例如你的 Windows 宿主机）
# 用途：出门在外时，通过跳板机间接进 NAS，不需要在绿联云上做 frp 穿透。
# 用法：
#   1) 先准备好到跳板机的免密登录（把本机公钥加到跳板机）：
#        ssh-keygen -t ed25519 -f /data/ssh/jump_key -N ''
#        ssh-copy-id -i /data/ssh/jump_key.pub <user>@<跳板机IP>
#   2) 改下面三行，然后：
#        nohup sh /data/rev-tunnel.sh >> /data/rev-tunnel.log 2>&1 &
#   3) 在跳板机上：ssh -p 2222 root@127.0.0.1  ——  2222 是跳板机上要占用的端口
set -e

JUMP_USER="${JUMP_USER:-root}"
JUMP_HOST="${JUMP_HOST:-192.168.0.209}"     # 跳板机（你的 Windows 宿主机）
JUMP_PORT="${JUMP_PORT:-22}"
LISTEN_PORT="${LISTEN_PORT:-2222}"          # 跳板机上对外开放的端口
KEY="${KEY:-/data/ssh/jump_key}"

exec ssh -N -T \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    -i "$KEY" \
    -R "0.0.0.0:${LISTEN_PORT}:127.0.0.1:22" \
    -p "$JUMP_PORT" "${JUMP_USER}@${JUMP_HOST}"
