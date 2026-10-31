# 绿联 NAS（192.168.0.201）上的 OCS

在这台 UGOS NAS 上跑了两个容器，都自启动、都不做 frp 穿透：

| 容器 | 端口 | 数据目录（`/mnt/dm-0/.ugreen_nas/137045/dockerImage/`） |
|---|---|---|
| `ocs` | 8080 → 8082 | `ocs/`（`obs/` 文件、`hls/` 切片、`logs/` 日志） |
| `nas-shell` | 2222 → 22 | `nas-shell/`（`ssh/authorized_keys`、`root_password`） |

- `ocs`：就是卡片里跑的 `src/obs/server.py`，用 `ocs-nas` 镜像；对外地址通过
  `URL_HEAD` / `OCS_LOCAL_BASE` / `OCS_FALLBACK_BASE` 三个环境变量指到 `http://192.168.0.201:8080`。
- `nas-shell`：给宿主机自己用的 SSH 入口，**替代「远程调试 + 手机验证码」**。里面挂了
  `/var/run/docker.sock`（容器里能直接 `docker ps/logs/exec`）和 `/mnt/dm-0`（直接读写 20T 存储）。

## 访问

```bash
# OCS
http://192.168.0.201:8080/

# SSH（Windows 上已配好别名 + 密钥，直接 ssh nas 即可）
ssh nas
ssh -p 2222 root@192.168.0.201          # 等价写法
# 密码登录：密码见 NAS 上 dockerImage/nas-shell/root_password
```

## 一开始为什么「所有端口都不通」

`192.168.0.0/24` 的路由被 Tailscale 的子网路由器劫持了（`NextHop` 是 `100.100.100.100`，
而那个广播该网段的 peer 已经离线 120 天），包全进隧道，NAS 看起来完全不可达。
修法（本机 Windows）：

```powershell
tailscale set --accept-routes=false
```

## 自启动（UGOS 的坑）

- UGOS 没有 `systemctl`，`dockerd` 由 `/etc/init.d/dockerd` 拉起；容器加 `--restart=always`
  **只在 dockerd 重启时生效**——容器自己崩掉 / 被 `docker kill` 后，UGOS 的 dockerd 不会按策略重启它。
- 所以额外加了兜底：`keepalive.sh` + root crontab 每分钟检查一次，没跑就 `docker start`（实测 ~25s 恢复）。
  停用：在 `dockerImage/` 下建 `.no-keepalive`。

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

- `deploy.sh` — 载入镜像 + 建目录 + 起两个容器（幂等，可重复跑）
- `keepalive.sh` — 容器自愈（NAS 上 cron 每分钟调用）
- `install_keepalive.sh` — 一次性把 keepalive 装进 crontab
- `remote.py` — 走 922 的 SSH 远程执行 / 传文件（paramiko）
- `upload_images.py` — 批量传镜像 tar.gz
- `rev-tunnel.sh` — 可选：把 NAS 的这个容器反向打到跳板机（不用 frp）

## 其它坑

1. UGOS 是 OpenWrt 风格：`ash` + `opkg`，**没有** `systemctl` / `docker compose` / `bash`，脚本别用 bash 语法。
2. `dockerImage` 目录默认不存在，要自己建并 `chmod 777`（UGOS 文件管理器用的是 `jiang` 用户）。
3. dockerd 实际配置在 `/tmp/dockerd/daemon.json`（`--config-file`），不是 `/etc/docker/daemon.json`；
   data-root = `/mnt/dm-0/.ugreen_nas/6`，storage driver = overlay2，daemon 20.10.16。
4. NAS 自己有定时关机任务（`/etc/crontabs/root` 里周一~周五 05:50 关机 + rtcwake 10 分钟后唤醒）。
