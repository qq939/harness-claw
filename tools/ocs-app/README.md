# ocs 安卓 App（WebView 壳）

一个只有 OCS 页面的安卓壳：**没有地址栏**，启动即打开 OCS；接收其它 App「分享」过来的文件后批量上传到 OCS。

## 功能

- Chrome 内核（系统 WebView），全屏无地址栏，默认打开 `https://ocs.dimond.top`
- 左上角有一个很淡的小齿轮：点开可切换服务器（预设 ocs.dimond.top / oas.dimond.top / NAS1 / NAS2:5080，或手动输入），记住选择
- **分享目标**：`ACTION_SEND` / `ACTION_SEND_MULTIPLE`，每种常见类型单独声明
  （`image/*`、`video/*`、`audio/*`、`text/*`、`application/*`、`*/*`，各 2 个 action 共 12 个 filter）。
  只写 `*/*` 时小米澎湃OS / 部分 ROM 的分享面板匹配不到，v1.1 起改成显式类型。
- 收到文件后逐个 `PUT <server>/<文件名>?token=agent`，底部进度条 + 完成后刷新页面；
  只分享文字（链接/纯文本）时落成 `share-<时间戳>.txt` 上传
- 网页里的「选择文件 / 上传文件夹」也能用（`onShowFileChooser` + 多选）
- 网页里的下载交给系统 DownloadManager
- 允许明文 http（局域网 NAS 用），返回键 = 网页后退

当前版本：`versionName 1.1`（versionCode 2）

## 构建

没有 Gradle，直接用 SDK 的 aapt2 / javac / d8 / zipalign / apksigner：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/ocs-app/build.ps1
# 产物：tmp/ocs-app/build/ocs.apk（已用 ocs.keystore 自签名）
```

依赖（本机已装）：
- JDK 17：`C:\Users\qq939\android-tools\jdk-17.0.20.1+1`
- Android SDK：`C:\Users\qq939\android-tools\sdk`（platforms;android-34、build-tools;34.0.0）

注意：`javac` 的 `-bootclasspath` 要带上 `build-tools/34.0.0/core-lambda-stubs.jar`，否则 lambda 会报
`cannot find symbol: LambdaMetafactory`。

## 发布

把 `ocs.apk` 放到 OCS 的 upload 目录（`obs/ocs.apk`），首页右上角设置齿轮左边就会出现「app下载」链接
（页面渲染时检查该文件是否存在，不存在就不显示）。四台都放了：

- https://ocs.dimond.top/
- http://192.168.0.201/
- http://192.168.0.202/
- http://8.130.124.108:5080/

## 服务器地址

App 里默认 `https://ocs.dimond.top`；点左上角小齿轮可切到局域网（`http://192.168.0.201`）或
NAS2 公网（`http://8.130.124.108:5080`），也可以自己输。
