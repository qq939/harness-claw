#!/bin/sh
# 在 NAS 上安装 keepalive 与 cron（只需执行一次；deploy.sh 之后跑）
set -e
B=/mnt/dm-0/.ugreen_nas/137045/dockerImage

chmod +x "$B/keepalive.sh"

if grep -q 'keepalive.sh' /etc/crontabs/root 2>/dev/null; then
    echo '(cron 已存在)'
else
    echo '* * * * * sh /mnt/dm-0/.ugreen_nas/137045/dockerImage/keepalive.sh >/dev/null 2>&1' >> /etc/crontabs/root
    echo '(cron 已添加)'
fi
/etc/init.d/cron restart >/dev/null 2>&1 || killall -HUP crond 2>/dev/null || true
sleep 1
tail -1 /etc/crontabs/root
