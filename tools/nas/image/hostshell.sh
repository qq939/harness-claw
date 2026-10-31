#!/bin/sh
# 进入绿联 NAS 宿主机的命名空间（等价 UGOS 的 root shell）
# 依赖：容器以 --privileged --pid=host 启动
# 用法：ssh nas hostshell            → 交互式宿主 shell
#       ssh nas hostshell -c "cmd"   → 直接在宿主上跑命令
set -e

if [ "$1" = "-c" ]; then
    shift
    exec nsenter --target 1 --mount --uts --ipc --net --pid -- /bin/sh -c "$*"
fi

exec nsenter --target 1 --mount --uts --ipc --net --pid -- /bin/sh "$@"
