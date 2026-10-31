#!/bin/sh
# SSH 运维容器入口：生成 host key、按环境变量/文件设置 root 密码、前台跑 sshd
set -e

mkdir -p /var/run/sshd /root/.ssh /data/hostkeys
chmod 700 /root/.ssh 2>/dev/null || true

# 主机密钥持久化到 /data/hostkeys：容器重建后 ssh 客户端不会报 host key 变了
if ls /data/hostkeys/ssh_host_* >/dev/null 2>&1; then
    cp -f /data/hostkeys/ssh_host_* /etc/ssh/ 2>/dev/null || true
fi
if [ ! -f /etc/ssh/ssh_host_ed25519_key ]; then
    ssh-keygen -A
fi
cp -f /etc/ssh/ssh_host_* /data/hostkeys/ 2>/dev/null || true
chmod 600 /etc/ssh/ssh_host_*key 2>/dev/null || true

# root 密码来源优先级：ROOT_PASSWORD 环境变量 > /data/root_password 文件（推荐，docker inspect 看不到）
PASS="${ROOT_PASSWORD:-${NAS_ROOT_PASSWORD:-}}"
if [ -z "$PASS" ] && [ -f /data/root_password ]; then
    PASS=$(cat /data/root_password)
fi
if [ -n "$PASS" ]; then
    echo "root:${PASS}" | chpasswd
    echo "[entry] root 密码已设置（可用 /data/root_password 文件维护）"
else
    echo "[entry] 未设置 root 密码：只接受 /root/.ssh/authorized_keys 登录"
fi

if [ -f /root/.ssh/authorized_keys ]; then
    chmod 600 /root/.ssh/authorized_keys
fi

echo "[entry] 启动 sshd (22)"
exec /usr/sbin/sshd -D -e
