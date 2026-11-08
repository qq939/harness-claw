# remote —— 盲操作遥控卡片（键鼠 → 宿主机）

网页是一片纯黑，没有任何文字；打开后键盘、鼠标、触摸板的操作会转发到**宿主机**的桌面上。
没有画面回传（盲操作），只有一个 2×2 像素的绿点表示 WebSocket 已连上。

## 链路

```
浏览器  ──WS──▶  卡片 19111-remote（remote_app.py，纯标准库）
                        │ ssh（host.docker.internal:22，密钥 .ssh/remote_card）
                        ▼
                  宿主机 Git Bash 会话（session 0）
                        │ python pipe_relay.py（stdin ← 帧流）
                        ▼
                  \\.\pipe\hermit_remote_input
                        ▼
                  注入代理 host_input_agent.py（session 1，SendInput）
```

为什么这么绕：Windows 的 SSH 会话落在 **session 0**，`SendInput` 在 session 0 里发不到用户桌面（桌面在
session 1）。所以真正注入的进程必须跑在交互式会话：用计划任务 `HermitRemoteInput`（“仅在用户登录时运行”）
在连接时拉起，管道把事件递过去。任务不是开机自启，只在有人连页面时 `schtasks /run` 启动。

## 页面用法（无画面，靠手感）

| 操作 | 效果 |
| --- | --- |
| 按住拖动 | 移动鼠标（相对位移） |
| 单击 / 轻点 | 左键单击 |
| 右键 / 双指轻点 | 右键单击 |
| 滚轮 / 双指上下滑 | 滚动 |
| 键盘 | 直接转发（物理键位 → Windows VK） |

## 已知边界

- **管理员窗口（UIPI）**：注入进程是普通权限，UAC 弹窗、以管理员运行的程序收不到输入。
- **安全桌面**：锁屏、Ctrl+Alt+Del、UAC 提权界面无法操作。
- **浏览器吞掉的组合键**：`Alt+Tab`、`Win`、`Ctrl+W`、`F11` 等，页面收不到 keydown。
- 断线/切后台会补发 keyup，避免“某个键一直按着”。

## 文件

| 文件 | 作用 |
| --- | --- |
| `host_input_agent.py` | 注入代理，跑在 session 1，读命名管道，`SendInput` |
| `pipe_relay.py` | SSH 会话里的中继，stdin 帧流 → 命名管道 |
| `add_key_elevated.ps1` | 把卡片公钥追加进宿主机 `administrators_authorized_keys`（需提权） |
| `test_inject.py` | 本地自测：起 relay，发 10 次相对移动，比对光标坐标 |

卡片侧代码在 `workspaces/19111-remote/`：`remote_app.py`（HTTP+WS，纯标准库）、`user_start.sh`（容器启动钩子，watchdog 会看护）、`test_ws.py`（端到端自测）。

## 部署 / 重装步骤

1. 卡片容器内生成密钥：`ssh-keygen -t ed25519 -f .ssh/remote_card -N ''`
2. 宿主机提权执行 `add_key_elevated.ps1`（追加公钥 + 修 ACL）
3. 宿主机创建任务（当前用户，交互式）：
   ```powershell
   schtasks /create /tn HermitRemoteInput /tr "\"<pythonw.exe>\" \"<host_input_agent.py>\"" /sc once /st 00:00 /it /f
   ```
4. 卡片容器里 `./user_start.sh`（或重启容器，`start.sh` 会自动调它）
5. 打开 `http://dimond.top:19111`，首次/空闲 10 分钟会要求输入密码 `agent`；接口侧用 `?token=agent`

## 安全

页面是密码保护（默认 `agent`，`REMOTE_PASSWORD` 可改），空闲 10 分钟（`REMOTE_IDLE_SECONDS`）后重新验证；接口必须带 `?token=agent`（`REMOTE_TOKEN` 可改）。**密码/URL 泄露等于交出宿主机控制权**，不要外发。
改密码/令牌：设置环境变量 `REMOTE_PASSWORD` / `REMOTE_TOKEN` 后重启卡片里的 `remote_app.py`；会话签名密钥在卡片 `.secret`（自动生成）。
