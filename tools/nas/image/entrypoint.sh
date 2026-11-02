#!/bin/sh
# SSH 运维容器入口：生成 host key、按环境变量/文件设置 root 密码、前台跑 sshd
set -e

mkdir -p /var/run/sshd /root/.ssh /data/hostkeys

# 数据卷上的目录可能是 UGOS 用户（jiang / 1370450000）建的，sshd 的 StrictModes 会拒绝
# 非 root 属主，导致 "Authentication refused: bad ownership or modes"。这里统一纠正。
chown root:root /root/.ssh 2>/dev/null || true
chmod 700 /root/.ssh 2>/dev/null || true
chown -R root:root /data/hostkeys 2>/dev/null || true

# 宿主根目录的 /obs 软链接自愈：UGOS 升级/重置根分区后可能丢失，容器每次启动都补一次。
# 多块存储卷时按「obs 里文件最多」挑，避免指到新插的空盘上。
_best=""
_best_n=-1
for _obs in /host/mnt/media_rw/*/.ugreen_nas/137045/dockerImage/ocs/obs; do
    [ -d "$_obs" ] || continue
    _n=$(ls -1 "$_obs" 2>/dev/null | wc -l)
    if [ "$_n" -gt "$_best_n" ]; then
        _best="$_obs"
        _best_n="$_n"
    fi
done
if [ -n "$_best" ]; then
    ln -sfn "${_best#/host}" /host/obs 2>/dev/null || true
    # 容器内也放一个同名入口，ssh 进来直接 ls /obs 就能看到（容器根是它自己的 overlay）
    ln -sfn /host/obs /obs 2>/dev/null || true
    echo "[entry] /obs -> ${_best#/host} ($_best_n 个文件)"
fi

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
    chown root:root /root/.ssh/authorized_keys 2>/dev/null || true
    chmod 600 /root/.ssh/authorized_keys
fi

echo "[entry] 启动 sshd (22)"
exec /usr/sbin/sshd -D -e
