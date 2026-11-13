# MEMORY.md

## 输出规范（用户要求，长期有效）
给用户看任何信息（状态、诊断结果、结论、报错）时，**必须同时把实际执行的命令原样展示出来**，方便用户学习。
包括：PowerShell 命令、docker / ssh / curl 命令、脚本内容、文件路径。
只给结论不给命令 = 不合格。

## 环境要点
- 宿主机：Windows（用户 qq939），SSH 入口 `dimond.top:19022`（密钥 `~/.ssh/hermit_agent`）；
  另一台 hermit 机器在 `dimond.top:18022`（Windows OpenSSH，需自备公钥）。
- 控制面板 19080；卡片 19xxx-*；网关容器 `harness-llm-gateway`（配置 `config/llm-gateway/providers.json`，改完不用重启）。
- OCS 四个入口：`ocs.dimond.top` / `192.168.0.201` / `192.168.0.202` / `oas.dimond.top`。
- Windows 上 `.ps1` 必须 UTF-8 **带 BOM**；Git Bash 默认 shell 要加 `MSYS_NO_PATHCONV=1` 防路径转换。
## 设备：Mac mini M1（通过 GLKVM 远程操作）

- KVM 地址：`https://192.168.0.200/#/login`（自签证书，浏览器要允许继续）
- KVM 管理员密码：`Black_gl00`
- 进入 KVM 画面后：**在画面中央双击鼠标**，激活 HDMI 显示（不双击是黑屏）
- macOS 登录：用户名 `jiang`，密码 `jiang`
- 用途：这台 Mac 是独立环境，需要 macOS 上做事时走这条链路；操作之后记得退出/断开 KVM 会话
## 脚本存放约定（用户要求，长期有效）
- **我写的任何脚本一律放到用户桌面**：Windows `C:\Users\qq939\Desktop\`；Mac `~/Desktop/`。
- 系统必须放在固定位置的（LaunchAgent plist、shell 配置、dsh profile 等）照旧放原位置，但**必须在桌面留一份可读副本 + 说明**，避免用户找不到。
## Mac mini 上的 dsh 宠物（大肥鱼）
- 机器：Mac mini M1，内网固定 `192.168.0.208`，SSH `jiang/jiang`（我的公钥已装）
- **固定入口**：`http://192.168.0.208:3080`（**反向代理，浏览器完全不用 token/cookie**，代理自己持有 dsh 的 cookie 并在 401 时自动换新）
- dsh 本体：`http://192.168.0.208:3081/?token=…`（token 每次启动随机变，没有固定开关）
- 代理要点：转发时把 `origin`/`referer` 改写成 `http://192.168.0.208:3081`，否则 WebSocket 被 dsh 判来源不符 → 界面一直“重新连接中”、会话列表空白（这个坑已修）
- 人设：社恐小鱼 / 摸鱼搭子，启动时 50/50 随机（`PERSONA=shy|slack` 可强制），文本在 `~/.dsh/persona-*.txt`
- 自启：LaunchAgent `com.harness.dshpet`（宠物本体，KeepAlive）+ `com.harness.dshtoken`（3080 反向代理，KeepAlive）
- 脚本：`~/start-dsh-pet.sh`、`~/.dsh/launch-at-login.sh`、`~/.dsh/dsh-token-proxy.js`；桌面 `启动dsh宠物.command` 和 `dsh-宠物配置/` 有副本
- 宿主机已关睡眠：`pmset sleep 0 disksleep 0 displaysleep 0 powernap 0 womp 1`
- 豆包 `2.35.8` 已装 `/Applications/Doubao.app`；豆包没有公开 API，派任务走 KVM 界面自动化

## OCS 投屏（AirPlay）需求与结论（2026-11-12）

**用户需求（原话）**：不管用。我 iPhone 镜像播放的时候，切到 OCS 的时候，手机应该播放适应手机屏幕，AirPlay 应该适应显示器。

**目标**：手机竖屏里视频按手机屏幕适配；AirPlay 到 16:9 显示器时视频铺满显示器。即抖音/TikTok 的「扩展播放」（媒体移交），不是镜像。

**现状**：不管用。仍是镜像 —— 手机整屏被复制到显示器，视频在中间被缩两次。

**已尝试与结论**
- `x-webkit-airplay` + `webkitShowPlaybackTargetPicker()`：Safari 26 已失效。macOS 26 Safari 实测点击后无任何设备列表弹出（KVM 截图确认按钮被按下）。
- 原生控制条兜底：Safari 下 `video.controls = true` 常开，已部署到 19082（提交 `25563d9`）。手机端待验证。
- pyatv：能发现并配对 Apple TV 4K（`192.168.0.100`，model `AppleTV14,1` / tvOS 27.2，蓝牙名 `MateView-28-3663`），配对成功（PIN 已用）；但 `play_url` 在 `/playback-info` 报 `not authenticated` —— pyatv 只支持 AirPlay 1 老设备推流，AirPlay 2 推不了；该版本也没有 `screenshot` 命令。
- 判断口径：**镜像 ≠ 移交**。电视上能看到 Safari 地址栏/页面 UI = 镜像；只有视频 = 移交。

**关键结论**
- 网页触发移交的唯一入口：系统播放器控制条上的 AirPlay 图标（YouTube / B站网页的做法）。
- 抖音的「扩展播放中 · 关闭」角标是原生 App UI（AVRoutePickerView），网页无对应 API，不可复刻。

**代码状态（19082 / ocs.dimond.top，均未推送）**
```
25563d9 feat(video): Safari 下常开系统控制条（AirPlay 唯一入口）
bc7cbd3 fix(video): AirPlay 改走原生控制条
6442a11 fix(video): iOS 上改用原生播放器触发 AirPlay
68484d0 feat(video): AirPlay 移交投屏（方案 B）
9ca02b1 chore: 同步工作区既有改动（改动前基线）
```

**下一步（未做，按用户要求暂停）**
1. 手机上确认：播放后底部有没有出现系统控制条、控制条里有没有 AirPlay 图标。
2. 若控制条不出现：改为 iOS 下强制 `webkitEnterFullscreen()`，或整页做成原生全屏。
3. 推送：OCS 仓库 `ocs` 分支 ahead 5；`hermitclaw` 仓库 ahead 9（我 2 个 + 卡片 agent 8 个），推送前需审计后 8 个提交。
**2026-11-12 晚：已全部撤销。** 用户决定放弃 AirPlay 方案，上述 4 个提交（`68484d0`/`6442a11`/`bc7cbd3`/`25563d9`）已从 `ocs` 分支移除并推送到远端（`3eb38b3..9ca02b1`，快进，无需 force）。`src/obs/video_static/*` 已还原到改动前状态（线上 `/video` 已确认无 airplayBtn / v-airplay / x-webkit-airplay）。
**2026-11-13 收尾：功能验证通过。** 用户确认 iPhone 上投屏 + 切视频 + 进度条同步全部正常。最终实现为「双播放器」方案：
- 主播放器（手机显示）+ 隐藏的 tvVideo（负责 AirPlay 移交），tvVideo 在第三页「速」下方有入口按钮。
- 主播放器设 x-webkit-airplay=deny，避免系统路由是电视时把主画面也接管（切视频黑屏的根因）。
- 同步闸门 tvSyncable()：wireless && currentPage !== 0 && playbackRate > 0；第一页是 -3x 倒放，负速率 AirPlay 播不了。
- 移交后 500ms 轮询 + 多重方式退出原生全屏，避免整页被黑屏挡住。
- 进度条时长兜底：video.duration 为 NaN 时用列表里的 duration。
- 三处已部署：19082 / 192.168.0.201 / oas.dimond.top。
- 顺带修复 NAS2 的 nas-shell SSH：/root/.ssh/authorized_keys 属主是 1370450000（UGOS 用户），
  sshd StrictModes 静默拒绝；entrypoint 里的 chown 带 || true 且只在启动时跑，没兜住。
## OCS 测试环境约定（用户要求，长期有效）

- **测 OCS 一律用 `https://ocs.dimond.top`（即 19082 卡片），不要用 192.168.0.201 / oas。**
- 用户原话：「永远记住：你要用ocs来测试，而不是201」。
- 2026-11-13 又强调了一次（我当时为了验 Range 往 201 投了一次屏）：「你不要用201测试！」
- 所以：**201 只部署、不测试**——不往它投屏、不在它上面放测试文件、不为验证去点它的按钮。
  别的实例（oas / ods）也一样：验证只走 ocs；要验证「别的实例也能投」这种场景，
  最多读一下它们接口的返回（`/api/tv/presence`、`/api/cast/status`），不要真的让它播起来。
- 部署仍然三处都同步（19082 / 201 / 202），但**验证和调试只看 ocs.dimond.top**。

## ocs 家族（用户 2026-11-13 明确）

要一起维护、一起升级的四个实例：

| 名字 | 入口 | 跑在哪 |
|---|---|---|
| ocs | `https://ocs.dimond.top` | 本机 19082 卡片 |
| oas | `https://oas.dimond.top` | NAS2 = 192.168.0.202 |
| ods | `http://dimond.top:19086` | 本机 19086-obsvideo 卡片（代码在 `obs_ref/src/obs/`，CWD=project，URL_HEAD 就是上面这个） |
| （没别名） | `http://192.168.0.201` | NAS1 |

**obs 不是家族成员**：老机器，不更新、不用管。改动只同步这四台。

## 域名 / 设备对照（实测确定，2026-11-13）

- `ocs.dimond.top` = 本机 19082 卡片；`192.168.0.201` = NAS1 的 ocs 容器；
  `oas.dimond.top` = `192.168.0.202` = NAS2 的 ocs 容器（用 /api/cast/status 的 seq/age 比对确认）。
- 极米 M1 投影仪 = **192.168.0.116**（从 NAS2 容器日志里 `/api/cast/current` 的来源 IP 抓到）。
  LAN 上没有开 5555，无法 adb 远程改配置；`116:8080` 是 Android Debug Database 页面，不是 adb。
- ocs-tv App 的服务器地址存在 SharedPreferences，只能遥控器 MENU 里改；换机/换域名要手动切一次。
- TV 端可观测性：`GET /api/cast/status` 的 `tv_online/age` 就是「电视现在连的是哪台服务器」的探针。

## 投屏 v1.4：电视上报地址，服务器直推（2026-11-13）

旧模型只有单行道：电视每 3 秒轮询「它配置的那一台」服务器，所以手机在别的实例上点投屏永远够不着它
（`tv_online=false`，按钮只能藏起来）。用户原话：「电视上的传送他自己的一个局域网地址就行了」。

- App 侧：`TvHttpServer`（18099 端口，`/ping`、`/play`、`/stop`）+ `Announcer`（每 10 秒上报 `{ip,port,name}`
  给当前服务器和内置默认 `ocs.dimond.top`）；`PlayerActivity.finishAll` 支撑 `/stop`。
- 服务端：`POST /api/tv/announce`、`GET /api/tv/presence`；`/api/cast` 有登记就直接
  `POST http://<ip>:18099/play?file=&base=&seq=`，`pushed` 只代表电视收到了，播起来才算数（仍看 ack）。
- 真机验证（小米 MIX Flip 装 1.4 当电视）：`/ping` → `192.168.0.107:18099`；从 ocs 推 → `acked=3`；
  从 `192.168.0.202` 推同一台（它轮询的是 ocs）→ `acked=2`，说明确实不依赖轮询。
- 极米（192.168.0.116）还装着 1.3，需要装一次 `ocstv.apk` 才有接收端；装完就不用再改它的服务器地址。
- 模拟器/手机通过 ADB 安装时，MIUI 会弹「USB 安装提示」，必须 `input tap` 点「继续安装」，7 秒不点自动拒绝。

## 投屏现状（2026-11-13 收尾，v1.8）

- 四台都是同一套代码 + `ocstv.apk 1.8`；极米已升到 1.8，四台的 `/api/tv/presence` 都是
  `192.168.0.116:18099 source=probe`。
- 电视地址存成**列表**（`logs/tv_address.json` 的 `hosts[]`）：只存一台的话，测试用的手机一上报就把投影仪顶掉。
- **`/obs/` 必须支持 Range（206）**：uvicorn 直连的部署（201、ods）以前对 `Range:` 回 200 整文件，
  Android MediaPlayer 会一直卡在 0:00 不出画面（nginx 前面的 ocs/oas 没暴露这个问题）。
  已在 server.py 里手写 `_parse_byte_range` + 206 StreamingResponse。
- 播放器还有个坑：`normalize()` 曾把非 IP 的 http 一律升级成 https，`http://dimond.top:19086`
  就永远连不上（不报错、不超时）。1.8 起显式非 80 端口保持 http，并加了 12 秒换协议兜底。
- 同步：网页投屏中每 0.5 秒 `POST /api/cast/ctl {pos,paused,rate}` → 服务端转 `http://<tv>:18099/ctl`；
  极米实测 seek 30 → 29.35、2x → 5 秒走 9.8 秒。
- 调试端点：`GET http://<tv>:18099/state`（pos/paused/rate/name）、`/ping`（含 ver）。