# 绿联 NAS（192.168.0.201）上的 OCS

在这台 UGOS NAS 上跑了两个容器，都自启动、都不做 frp 穿透：

| 容器 | 端口 | 数据目录（`/mnt/dm-0/.ugreen_nas/137045/dockerImage/`） |
|---|---|---|
| `ocs` | **80 → 8082**（另挂 8080 → 8082） | `ocs/`（`obs/` 文件、`hls/` 切片、`logs/` 日志） |
| `nas-shell` | 2222 → 22 | `nas-shell/`（`ssh/authorized_keys`、`root_password`） |

- `ocs`：就是卡片里跑的 `src/obs/server.py`，用 `ocs-nas` 镜像；对外地址通过
  `URL_HEAD` / `OCS_LOCAL_BASE` / `OCS_FALLBACK_BASE` 三个环境变量指到 `http://192.168.0.201`。
  挂在 80 上是为了「浏览器直接输 IP」——UGOS 自己的管理界面在 **9999**，80/443 都空着。
- `nas-shell`：给宿主机自己用的 SSH 入口，**替代「远程调试 + 手机验证码」**。里面挂了
  `/var/run/docker.sock`（容器里能直接 `docker ps/logs/exec`）和 `/mnt/dm-0`（直接读写 20T 存储）。

内容目录做了两个软链接（都指向 `dockerImage/ocs`，也就是里面的 `obs/` 文件、`hls/`、`logs/`）：

- `/ocs` —— 宿主根目录，`ssh nas hostshell` 后直接 `cd /ocs`
- `/mnt/dm-0/.ugreen_nas/137045/ocs` —— 存储卷用户目录根，UGOS 文件管理器里能直接看到

## 访问

```bash
# OCS：不用输端口（浏览器默认就是 http://IP 走 80）
http://192.168.0.201/
http://192.168.0.201:8080/     # 备用，老链接仍可用

# SSH：容器 shell（里面有 docker CLI、/mnt/dm-0、宿主根目录在 /host）
ssh nas
ssh nas "docker ps"

# 真正进 NAS 宿主机（nsenter，等价 UGOS「远程调试」拿到的 root shell）
ssh nas hostshell
ssh nas hostshell        # 交互
echo 'tail -1 /etc/crontabs/root' | ssh nas hostshell   # 一行式

# 等价的显式写法
ssh -p 2222 root@192.168.0.201
# 密码登录：密码见 NAS 上 dockerImage/nas-shell/root_password
```

`nas-shell` 用 `--privileged --pid=host` 起，所以容器里的 `hostshell` 能
`nsenter -t 1 -m -u -i -n -p` 进宿主命名空间；容器重建不影响，宿主机密钥持久化在
`dockerImage/nas-shell/hostkeys/`（不会每次重建都报 host key 变了）。

## 一开始为什么「所有端口都不通」

`192.168.0.0/24` 的路由被 Tailscale 的子网路由器劫持了（`NextHop` 是 `100.100.100.100`，
而那个广播该网段的 peer 已经离线 120 天），包全进隧道，NAS 看起来完全不可达。
修法（本机 Windows）：

```powershell
tailscale set --accept-routes=false
```

## 自启动

- UGOS 没有 `systemctl`，`dockerd` 由 `/etc/init.d/dockerd` 拉起；容器统一加 `--restart=always`，
  dockerd 随系统起时会把它们带回来（实测重启 dockerd 后两个容器都自动恢复）。
- 不再加额外的 cron 看门狗：NAS 上 dockerd 很稳，需要时手动 `docker start ocs nas-shell` 即可。

## 重新部署 / 升级镜像（NAS 上不了 GitHub 和 Docker Hub）

NAS 完全拉不到外网镜像，只能离线导入。**顺序：本地构建 → `docker save -o` → Python 压缩 → scp → NAS `docker load`**。

```powershell
cd C:\Users\qq939\Downloads\hermitclaw

# 1) 拉最新代码并构建（第一次先 git clone 到 tmp/nas-ocs）
git -C tmp/nas-ocs pull --ff-only
docker build -t ocs-nas:latest -f tmp/nas-ocs/Dockerfile.nas tmp/nas-ocs

# 2) 导出（不要用 PowerShell 的 docker save | gzip > x，`>` 是文本管道会写坏二进制！）
docker save -o tmp/ocs-nas.tar ocs-nas:latest
py -3 -c "import gzip,shutil,os;src,dst='tmp/ocs-nas.tar','tmp/ocs-nas.tar.gz';os.path.exists(dst) and os.remove(dst);fi=open(src,'rb');fo=gzip.open(dst,'wb',compresslevel=1);shutil.copyfileobj(fi,fo,8<<20);fo.close();fi.close();os.remove(src)"

# 3) 传 + 部署
$env:NAS_PASS='<NAS root 密码>'
py -3 tools/nas/upload_images.py
py -3 tools/nas/remote.py put tools/nas/deploy.sh /mnt/dm-0/.ugreen_nas/137045/dockerImage/_import/deploy.sh
py -3 tools/nas/remote.py run "sh /mnt/dm-0/.ugreen_nas/137045/dockerImage/_import/deploy.sh"
```

`nas-shell` 镜像（`tmp/nas-shell/`，Dockerfile + sshd_config + entrypoint + 静态 docker CLI）
同法构建成 `nas-shell:latest` 后一起传。

## 文件清单

- `image/` — 两个镜像的构建文件
  - `Dockerfile.ocs`：OCS（python:3.11-slim + ffmpeg，跑 `src/obs/server.py`）
  - `Dockerfile` + `sshd_config` + `entrypoint.sh` + `hostshell.sh`：SSH 运维容器
- `build_images.sh` — 一键构建两个镜像并导出 `tmp/*.tar.gz`
- `deploy.sh` — 载入镜像 + 建目录 + 起两个容器（幂等，可重复跑）
- `remote.py` — 走 922 的 SSH 远程执行 / 传文件（paramiko）
- `upload_images.py` — 批量传镜像 tar.gz
- `rev-tunnel.sh` — 可选：把 NAS 的这个容器反向打到跳板机（不用 frp）

## 其它坑

1. UGOS 是 OpenWrt 风格：`ash` + `opkg`，**没有** `systemctl` / `docker compose` / `bash`，脚本别用 bash 语法。
2. `dockerImage` 目录默认不存在，要自己建并 `chmod 777`（UGOS 文件管理器用的是 `jiang` 用户）。
3. dockerd 实际配置在 `/tmp/dockerd/daemon.json`（`--config-file`），不是 `/etc/docker/daemon.json`；
   data-root = `/mnt/dm-0/.ugreen_nas/6`，storage driver = overlay2，daemon 20.10.16。
4. NAS 自己有定时关机任务（`/etc/crontabs/root` 里周一~周五 05:50 关机 + rtcwake 10 分钟后唤醒）。
5. 关于 **443**：OCS 本身是纯 HTTP，挂 443 得配 TLS 证书（自签证书浏览器每次都会警告），
   所以默认只挂 80。真要 `https://192.168.0.201`，得再起一个 TLS 终止（Caddy/nginx + 自签证书），
   或者把 OCS 反代进 UGOS 自己 9999 的 nginx——后者会动 UGOS 的配置，不建议。
