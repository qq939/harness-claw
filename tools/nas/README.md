# 绿联 NAS 上的 OCS（两台）

两台 UGOS NAS 跑同一套容器（`ocs` + `nas-shell`），NAS2 多一个 `frpc` 做公网映射。

| NAS | 地址 | 容器 | 端口 | 数据目录（`/mnt/dm-0/.ugreen_nas/137045/dockerImage/`） |
|---|---|---|---|---|
| NAS1 | 192.168.0.201 | `ocs` | **80 → 8082**（另挂 8080） | `ocs/`（`obs/` 文件、`hls/`、`logs/`） |
| | | `nas-shell` | 2222 → 22 | `nas-shell/`（`ssh/`、`root_password`、`hostkeys/`） |
| NAS2 | 192.168.0.202 | `ocs` | **80 → 8082**（另挂 8080） | `ocs/` |
| | | `nas-shell` | 2222 → 22 | `nas-shell/` |
| | | `frp`（frpc v0.65.0，host 网络） | 本机 **80** → 阿里云 **5080** | `frp/frpc.ini`（挂到容器 `/etc/frp`） |

- `ocs`：就是卡片里跑的 `src/obs/server.py`，用 `ocs-nas` 镜像。对外地址由三个环境变量决定：
  `URL_HEAD`（服务端生成的链接）、`OCS_LOCAL_BASE`（前端优先连的地址）、`OCS_FALLBACK_BASE`（前端回退）。
  挂在 80 上是为了「浏览器直接输 IP」——UGOS 自己的管理界面在 **9999**，80/443 都空着。
- `nas-shell`：给宿主机自己用的 SSH 入口，**替代「远程调试 + 手机验证码」**。挂了
  `/var/run/docker.sock`（容器里直接 `docker ps/logs/exec`）、`/mnt/dm-0`、宿主根目录 `/`（到 `/host`），
  并以 `--privileged --pid=host` 起，所以容器里的 `hostshell` 能用 nsenter 进宿主命名空间。
- `frp`：`fatedier/frpc:v0.65.0`，`--network host`，配置就是 harness 那份 common 段 + 一条
  `[nas202-ocs]`（local 80 → remote 5080）。

内容目录 `obs/` 做了两个软链接（两台一样）：

- `/obs` —— 宿主根目录，`ssh nas hostshell` 后直接 `cd /obs`
- `/mnt/dm-0/.ugreen_nas/137045/obs` —— 存储卷用户目录根，UGOS 文件管理器里能直接看到

## 访问

```bash
# NAS1
http://192.168.0.201/                 # OCS（不用输端口）
http://192.168.0.201:8080/            # 备用
ssh nas                               # 容器 shell（带 docker CLI、/mnt/dm-0、/host）
ssh nas hostshell                     # 真·NAS 宿主 root shell（nsenter）

# NAS2
http://192.168.0.202/                 # 局域网
http://8.130.124.108:5080/            # 公网（frp）
ssh nas2
ssh nas2 hostshell
```

`~/.ssh/config` 里已经配好 `nas` / `nas2` 两个别名，用的是同一个密钥 `~/.ssh/nas_shell`；
密码登录的密码见各 NAS 上 `dockerImage/nas-shell/root_password`。

## 部署 / 重新部署

```powershell
# NAS1（只有局域网）
$env:NAS_PASS='<密码>'
py -3 tools/nas/remote.py put tools/nas/deploy.sh /mnt/dm-0/.ugreen_nas/137045/dockerImage/_import/deploy.sh
py -3 tools/nas/remote.py run "sh /mnt/dm-0/.ugreen_nas/137045/dockerImage/_import/deploy.sh"

# NAS2（带公网地址 + frp）
$env:NAS_HOST='192.168.0.202'; $env:NAS_PASS='<密码>'
py -3 tools/nas/remote.py put tools/nas/deploy.sh /mnt/dm-0/.ugreen_nas/137045/dockerImage/_import2/deploy2.sh
py -3 tools/nas/remote.py run "NAS_IP=192.168.0.202 PUBLIC_BASE=http://8.130.124.108:5080 ENABLE_FRP=1 IMPORT_DIR=/mnt/dm-0/.ugreen_nas/137045/dockerImage/_import2 sh /mnt/dm-0/.ugreen_nas/137045/dockerImage/_import2/deploy2.sh"
```

环境变量：`NAS_IP`、`OCS_PORT`(默认 80)、`OCS_PORT_ALT`(8080)、`SSH_PORT`(2222)、
`PUBLIC_BASE`(对外地址，默认=局域网地址)、`ENABLE_FRP`、`FRP_REMOTE_PORT`(5080)、`IMPORT_DIR`。

## 升级镜像（NAS 上不了 GitHub 和 Docker Hub）

**顺序：本地构建 → `docker save -o` → Python 压缩 → scp → NAS `docker load`**。

```powershell
sh tools/nas/build_images.sh          # 构建 ocs-nas / nas-shell 并导出 tmp/*.tar.gz
docker save -o tmp/frpc.tar fatedier/frpc:v0.65.0      # frpc 只需要导一次
py -3 -c "import gzip,shutil,os;src,dst='tmp/frpc.tar','tmp/frpc.tar.gz';os.path.exists(dst) and os.remove(dst);fi=open(src,'rb');fo=gzip.open(dst,'wb',compresslevel=1);shutil.copyfileobj(fi,fo,8<<20);fo.close();fi.close();os.remove(src)"
$env:NAS_HOST='192.168.0.202'; $env:NAS_PASS='<密码>'
$env:NAS_IMPORT_DIR='/mnt/dm-0/.ugreen_nas/137045/dockerImage/_import2'
py -3 tools/nas/upload_images.py     # 传 ocs / shell / frp 三个 tar.gz
```

**坑**：不要用 PowerShell 的 `docker save | gzip > x.tar.gz`，`>` 是文本管道会把二进制写坏，
NAS 上 `docker load` 会报 `archive/tar: invalid tar header`。必须先 `docker save -o` 再用 Python 压缩。

## 自启动

- UGOS 没有 `systemctl`，`dockerd` 由 `/etc/init.d/dockerd` 拉起；容器统一 `--restart=always`，
  dockerd 随系统起时会把它们带回来（实测重启 dockerd 后容器都自动恢复）。
- 不加额外 cron 看门狗：NAS 上 dockerd 很稳，需要时手动 `docker start ocs nas-shell frp`。

## 文件清单

- `image/` — 镜像构建文件（`Dockerfile.ocs`、`Dockerfile`、`sshd_config`、`entrypoint.sh`、`hostshell.sh`）
- `build_images.sh` — 一键构建两个镜像并导出 `tmp/*.tar.gz`
- `deploy.sh` — 载入镜像 + 建目录 + 起容器（幂等；`ENABLE_FRP=1` 时连 frpc 一起）
- `remote.py` — 走 922 的 SSH 远程执行 / 传文件（paramiko）
- `upload_images.py` — 批量传镜像 tar.gz（ocs / shell / frp）
- `rev-tunnel.sh` — 可选：把 NAS 的这个容器反向打到跳板机（不用 frp 时）

## 其它坑

1. UGOS 是 OpenWrt 风格：`ash` + `opkg`，**没有** `systemctl` / `docker compose` / `bash`，脚本别用 bash 语法。
2. `dockerImage` 目录默认不存在，要自己建并 `chmod 777`（UGOS 文件管理器用的是 `jiang` 用户）。
3. dockerd 实际配置在 `/tmp/dockerd/daemon.json`（`--config-file`），不是 `/etc/docker/daemon.json`；
   data-root = `/mnt/dm-0/.ugreen_nas/6`，storage driver = overlay2，daemon 20.10.16。
4. NAS 自己有定时关机任务（`/etc/crontabs/root` 里周一~周五 05:50 关机 + rtcwake 10 分钟后唤醒）。
5. 从 Windows 访问 NAS 时，若 `192.168.0.0/24` 的路由被 Tailscale 子网路由器抢走（`Find-NetRoute`
   显示 NextHop `100.100.100.100`），NAS 会表现为「所有端口都不通」。修法：`tailscale set --accept-routes=false`。
6. 关于 **443**：OCS 本身是纯 HTTP，挂 443 得配 TLS 证书（自签浏览器每次警告），所以默认只挂 80。
