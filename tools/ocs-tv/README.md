# ocs TV（电视/盒子版）

给 Android TV / 投影 / 盒子用的壳，和手机版是两个独立包名（`com.harness.ocs.tv`），可以同时装。

## 和手机版的区别

| | 手机版 `ocs` | 电视版 `ocs TV` |
|---|---|---|
| 包名 | `com.harness.ocs` | `com.harness.ocs.tv`（可共存） |
| 启动器 | LAUNCHER | **LEANBACK_LAUNCHER** + LAUNCHER（电视首页会出现大图标 + banner） |
| 触摸屏 | 需要 | **不要求**（`touchscreen required=false`），只能遥控器操作 |
| 屏幕 | 跟随系统 | 强制横屏、全屏沉浸（隐藏状态栏/导航栏） |
| 操作 | 手指 | **遥控器**：方向键 / OK / 返回 / 菜单 |
| 视频播放 | WebView 内播 | **原生播放器**（极米 M1 等投影仪 WebView 解码弱，会崩渲染进程） |
| 字号 | 100% | 130%（沙发距离看得清） |
| 默认服务器 | `https://ocs.dimond.top` | `https://ocs.dimond.top` |
| 分享接收 | 有（SEND / SEND_MULTIPLE） | 无（电视一般不用分享） |

## 遥控器映射（`shim.js`，注入到页面里）

- **文件/首页**：方向键做「空间焦点导航」——当前元素描蓝框，OK = 点击；左右键只在同一水平带内移动（不会乱跳到上面的排序栏）
- **`/video` 播放页**：方向键直接派发 `ArrowUp/Down/Left/Right` 给页面（页面原本就支持：上下切视频、左右翻页），OK = 空格（播放/暂停）
- **菜单键 / INFO 键**：打开服务器切换列表（电视上没法输网址，这是唯一入口，也可手动输入）
- **返回键**：先网页后退，退到底则弹「退出 ocs TV？」

## 构建

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/ocs-tv/build.ps1
# 产物：tmp/ocs-tv/build/ocs-tv.apk（复用手机版的 ocs.keystore 签名）
```

`build.ps1` 会把 `shim.js` 转成 Java 字符串常量（`ShimJs.java`）再编译，避免手写转义。
依赖同手机版：JDK 17 + Android SDK（build-tools 34 / android-34）。

## 发布

放到 OCS 的 upload 目录 `ocstv.apk`，首页右上角（设置齿轮左边）会自动多出一个「TV版」链接；
没有这个文件就不显示。三处都放同一份：

- `https://ocs.dimond.top/ocstv.apk`
- `http://192.168.0.201/ocstv.apk`
- `http://oas.dimond.top/ocstv.apk`（= `192.168.0.202`）

## 视频不走 WebView（v1.2）

极米 M1 这类投影仪 WebView 解码能力弱，点标题进 `/video`、或点列表里的视频文件都会让渲染进程崩溃（表现为闪退）。

v1.2 起 WebView 只负责文件列表：

- 点标题（`/video`）→ 原生视频列表 `VideoListActivity`（拉 `/videos` 接口，遥控器上下选、OK 播）
- 点视频文件 / `/preview/<视频>` → 原生播放器 `PlayerActivity`（`VideoView`，OK 播放暂停、左右快退快进 10s、返回退出）
- 播放失败会提示「这台设备播不了这个格式」，不再影响页面

## 301 跳转（v1.3）

站点默认地址是 `http://`，nginx 会 301 到 https。原生取列表/播放都不一定自动跟随：

- `VideoListActivity` 手动跟 301/302/303/307/308（最多 5 跳）
- `PlayerActivity` 对非 IP/localhost 的 `http://` 直接升级成 `https://`，播放失败还会换协议重试一次

## 上报局域网地址，服务器直接推（v1.4）

v1.3 及以前只有一条路：电视每 3 秒去问**它配置的那一台**服务器「有要播的吗」。所以换域名、换实例，
都得到电视上按菜单键改地址——投屏能力和「电视连的是谁」绑死了。

v1.4 改成双向：

- 电视在 `18099` 端口常驻一个最小 HTTP 服务：`GET /ping` 报身份，`POST /play?file=&base=&seq=` 播片，`POST /stop` 退出
- 每 10 秒把自己的**局域网地址**上报给服务器（当前配置的那台 + 内置默认 `ocs.dimond.top`），`POST /api/tv/announce`
- 服务器记住这份地址，手机点「投屏」时直接 `POST http://<电视IP>:18099/play`，不必等它轮询，
  也不再要求「手机用的那台 = 电视连的那台」
- 回执仍然是播放器 `onPrepared` 时的 `/api/cast/ack`：推过去只代表电视收到了指令，真播起来才显示「已投屏」

代价：电视和服务器之间必须有 IP 可达（同网段，或服务器能路由到电视的局域网地址）。

## 崩溃处理（v1.1）

点首页标题会跳到 /video 视频页，电视上的 WebView 渲染进程容易在这类重页面上崩（内存小 / 解码不支持）。

v1.1 起接管了 WebViewClient.onRenderProcessGone：渲染进程挂掉时不再连带杀掉 App，而是提示一句、重建 WebView 并退回文件列表；/video 连续崩两次就直接回首页。加载失败会显示一个深色错误页（提示用「菜单」键换服务器）。

## 已知限制

- 还是 WebView 壳，页面本身不是为电视设计的；焦点框靠 JS 描边，个别元素（如纯文字）不可点
- 视频播放依赖设备自带的 H.264/HLS 解码能力；个别盒子播不了 mkv
- 没在真机上验证过遥控器手感（这台机器没有 TV/模拟器），逻辑用 Chromium + 真实页面模拟按键验证过
