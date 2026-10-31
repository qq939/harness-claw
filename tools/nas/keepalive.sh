#!/bin/sh
# 容器自愈（NAS 上由 root crontab 每分钟调用一次；见 install_keepalive.sh）
# 为什么需要：UGOS 的 dockerd 在容器自己退出（崩溃 / docker kill）后不会按 --restart=always 重启，
#            只有 dockerd 重新起来时才会把容器带回来。cron 兜底可以做到 ~1 分钟内恢复。
# 停用：在 dockerImage 目录下建 .no-keepalive 文件
B=/mnt/dm-0/.ugreen_nas/137045/dockerImage
[ -f "$B/.no-keepalive" ] && exit 0

for n in ocs nas-shell; do
    if ! docker inspect -f '{{.State.Running}}' "$n" 2>/dev/null | grep -q true; then
        docker start "$n" >/dev/null 2>&1 || true
        echo "$(date '+%F %T') start $n" >> "$B/keepalive.log"
    fi
done

if [ -f "$B/keepalive.log" ]; then
    tail -n 500 "$B/keepalive.log" > "$B/keepalive.log.tmp" 2>/dev/null && mv "$B/keepalive.log.tmp" "$B/keepalive.log"
fi
