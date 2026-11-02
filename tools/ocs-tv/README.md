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
| 字号 | 100% | 130%（沙发距离看得清） |
| 默认服务器 | `https://ocs.dimond.top` | `http://oas.dimond.top` |
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

放到 OCS/oas 的 upload 目录 `ocstv.apk`，首页右上角（设置齿轮左边）会自动多出一个「TV版」链接；
没有这个文件就不显示。当前放在 **oas**：

- `https://oas.dimond.top/ocstv.apk`
- `http://192.168.0.202/ocstv.apk`
- `http://8.130.124.108:5080/ocstv.apk`

## 已知限制

- 还是 WebView 壳，页面本身不是为电视设计的；焦点框靠 JS 描边，个别元素（如纯文字）不可点
- 视频播放依赖设备自带的 H.264/HLS 解码能力；个别盒子播不了 mkv
- 没在真机上验证过遥控器手感（这台机器没有 TV/模拟器），逻辑用 Chromium + 真实页面模拟按键验证过
