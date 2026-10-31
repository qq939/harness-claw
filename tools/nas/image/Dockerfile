# 绿联 NAS 上的 SSH 运维容器（免「远程调试 + 手机验证码」）
# 目的：从 Windows 宿主机直接 ssh -p 2222 root@<NAS IP>
#   1) 容器内挂了 NAS 的 docker.sock 与 /mnt/dm-0，可直接管理容器与存储
#   2) 容器以 --privileged --pid=host 启动、宿主根目录挂到 /host，
#      容器里的 `hostshell` 用 nsenter 直接进宿主机命名空间（等价 UGOS 的 root shell）
FROM python:3.11-slim

ENV TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       openssh-server iproute2 procps util-linux curl ca-certificates \
       tar gzip unzip rsync vim less jq \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/sshd /root/.ssh

# 静态 docker CLI：容器内可直接 docker ps / docker logs，操作 NAS 上的容器
COPY docker /usr/local/bin/docker
RUN chmod +x /usr/local/bin/docker

COPY sshd_config /etc/ssh/sshd_config
COPY entrypoint.sh /entrypoint.sh
COPY hostshell.sh /usr/local/bin/hostshell
RUN chmod +x /entrypoint.sh /usr/local/bin/hostshell

EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]
