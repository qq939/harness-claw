# HARNESS · 容器卡片控制平面

把每张「容器卡片」当成一个独立的小项目来跑：一个 Docker 容器 + 一个 Claude Code 代理 + 一个面板入口。
面板负责建卡、切模型、下发指令、看日志、看花费；卡片负责真正干活。

- 面板：<http://dimond.top:19080/>
- 容器内固定端口 **8082**（卡片自己的 web app / `/ask/claude`）
- 卡片端口从 **19081** 递增，容器名格式 `<端口>-<名字>`，例如 `19091-picturetext`
- 远端域名 `hermit.dimond.top` / `dimond.top` 指向同一台机器（frp 内网穿透）

---

## 一、30 秒跑起来

```bash
git clone https://github.com/qq939/harness-claw.git
cd harness-claw

# 1) 写配置（见第二节）：至少要有 config/claude/config.json + settings.json
cp config/claude/examples/config.json.bak      config/claude/config.json
cp config/claude/examples/settings.json.bak    config/claude/settings.json
# 编辑上面的文件，把 ANTHROPIC_AUTH_TOKEN 换成你自己的 key

# 2) 起控制平面
docker compose -f docker-compose.yml up -d control-19080

# 3) 打开面板建卡
#    http://localhost:19080/
```

Windows 下用 `.\docker-compose.ps1 up -d control-19080`（脚本会把 `PWD` 设成自身目录再调 compose，
避免相对挂载路径解析错）。

---

## 二、怎么配配置文件（重点）

所有跟模型、端点、密钥有关的配置都在 **`config/claude/`** 下，一套配置 = **两个文件**：

| 文件 | 作用 | 关键字段 |
|------|------|----------|
| `settings.json` | 注入到容器进程的环境变量（决定 Claude Code 连谁、用什么模型） | `env.ANTHROPIC_BASE_URL`、`env.ANTHROPIC_MODEL`、`env.ANTHROPIC_AUTH_TOKEN`、`env.CLAUDE_CODE_EFFORT_LEVEL` |
| `config.json` | Claude Code 自己的 provider 定义（决定「模型名 → 端点」的映射与展示名） | `claude.providers.<id>.settingsConfig.env.*` |

### 2.1 现成的模板

`config/claude/examples/` 里放的是**脱敏后的 `.bak` 模板**（key 是假的），可以直接复制改名：

```
config.json.bak                        ← 默认配置（DeepSeek Flash）
config.json.deepseek.bak
config.json.deepseek-flash.bak
config.json.localqwen.bak              ← 本地 llama.cpp（http://host.docker.internal:8000）
config.json.minimax.bak
config.json.minimax-m2.7-highspeed.bak
config.json.webqwen.bak
settings.json.bak
settings.json.<profile>.bak            ← 与上面一一对应
```

复制方式（例：加一个新模型 `my-model`）：

```bash
cp config/claude/examples/config.json.my-model.bak  config/claude/config.json.my-model
cp config/claude/examples/settings.json.my-model.bak config/claude/settings.json.my-model
```

> **注意**：`.bak` 文件不会被平台加载，平台只读 `config.json*` / `settings.json*`（无后缀，或 `.deepseek` 等 profile 后缀）。
> 把 `.bak` 改名成正式文件才是生效路径。

### 2.2 一个 provider 长什么样

`config.json` 里 `claude.providers` 的每一项就是一个「模型档位」：

```json
{
  "claude": {
    "providers": {
      "7ba4c425-...": {
        "name": "DeepSeek-V4.1-Flash",
        "settingsConfig": {
          "env": {
            "ANTHROPIC_AUTH_TOKEN": "sk-你的key",
            "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
            "ANTHROPIC_MODEL": "deepseek-flash",
            "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-flash",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-flash",
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-flash"
          }
        },
        "websiteUrl": "https://platform.deepseek.com",
        "category": "cn_official"
      }
    }
  }
}
```

必填三件套：

1. `ANTHROPIC_BASE_URL` —— 端点（Anthropic 兼容格式）
   - DeepSeek：`https://api.deepseek.com/anthropic`
   - MiniMax：`https://api.minimax.cn/anthropic`
   - 本地 llama.cpp：`http://host.docker.internal:8000`（卡片里用 `host.docker.internal` 指宿主机）
2. `ANTHROPIC_MODEL` —— 模型 id（服务端真实模型名）
3. `ANTHROPIC_AUTH_TOKEN` —— 你的 key

另外三个 `ANTHROPIC_DEFAULT_*_MODEL` 是给 Claude Code 的「子模型别名」，一般和主模型填同一个即可
（否则 Claude Code 内部会拿别名去请求服务端不存在的模型）。

### 2.3 `settings.json` 里能调什么

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
    "ANTHROPIC_MODEL": "deepseek-flash",
    "ANTHROPIC_AUTH_TOKEN": "sk-你的key",
    "API_TIMEOUT_MS": "3000000",
    "CLAUDE_CODE_EFFORT_LEVEL": "high",          // low | medium | high（思考档位）
    "CLAUDE_CODE_TRUST_ALL": "true",
    "CLAUDE_CODE_SKIP_ONBOARDING": "true",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  },
  "permissions": { "defaultMode": "bypassPermissions" },
  "systemPrompts": { "override": "本项目非回合对话模式……" }
}
```

| 键 | 说明 |
|----|------|
| `ANTHROPIC_*` | 见上 |
| `CLAUDE_CODE_EFFORT_LEVEL` | 思考档位 `low` / `medium` / `high`。**必须是单数**，写成 `..._LEVELS`（复数）CLI 不认 |
| `API_TIMEOUT_MS` | 请求超时（毫秒），长任务建议调大 |
| `CLAUDE_CODE_TRUST_ALL` / `SKIP_ONBOARDING` | 免掉交互式引导 |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | 关掉遥测类请求 |
| `systemPrompts.override` | 覆盖系统提示词（平台级，注入每张卡） |

### 2.4 profile（多模型切换）

后缀就是 profile 名：

```
config.json.deepseek-flash   +  settings.json.deepseek-flash   → profile "deepseek-flash"
config.json.minimax          +  settings.json.minimax          → profile "minimax"
```

面板卡片上的「切换模型」按钮会把你选中的 profile 这一对文件写进容器，然后**重启卡片**生效。
新增一个 profile 就是在 `config/claude/` 下加一对同名文件即可。

### 2.5 改完怎么生效

- **新建卡片**：直接生效。
- **已有卡片**：改 `config.json*` / `settings.json*` 后需要**重建**卡片（面板「重建」按钮）。
  原因：容器进程环境变量是**创建时**注入的，`docker restart` 不会重新注入。
- 面板右上角的「思考 高/中/低」也是同一套机制：写配置 → 卡片重启后生效。

### 2.6 安全提醒

- `config/claude/config.json*` 与 `settings.json*` **已被 `.gitignore` 忽略**，不要把带真 key 的文件提交到仓库。
- 仓库里只提供 `config/claude/examples/*.bak`（key 是假的）作为模板。
- key 一旦进过公开仓库的历史，**删除文件不等于失效**，必须去控制台吊销并换新 key。

---

## 三、目录结构

```
control/app.py            面板（Flask）：建卡/切模型/下发指令/日志/花费/思考档位
config/rules/             平台级注入：CLAUDE.md（约定）、systemreadme.md（项目说明）、run_claude.js（唯一调用入口）
config/claude/            模型配置（settings.json / config.json + examples 模板）
agents/claude/            卡片镜像（sshd + Claude Code + watchdog）
agents/ssh-gateway/       网页版 SSH 网关
tools/                    挂进每张卡片的工具（hub / email / obs / github / localqwen …）
workspaces/<卡片名>/       卡片工作目录（宿主机挂载，重建不丢）
logs/<卡片名>/             卡片日志
test_*.py                 端到端校验脚本（直接 `py -3 test_xxx.py` 跑）
```

## 四、常用命令

```bash
# 起 / 更新控制平面
docker compose -f docker-compose.yml build control-19080
docker compose -f docker-compose.yml up -d control-19080

# 看某张卡的状态与今天花了多少钱
curl -s http://localhost:19080/api/agents | python -m json.tool | head -40

# 跑全部自检
for f in test_*.py; do echo "== $f"; py -3 "$f"; done
```

## 五、约定

- **建卡必须同时具备 webapp（人用的页面）和 api（程序调用的接口）**，缺一不算完成：
  `GET /` 是能操作的 HTML 页面，`GET /api/...` 是结构化 JSON 接口，页面按钮直接调同一套 api；
  `GET /health` 返回 `{"ok": true}`；写操作带 token（默认 `agent`）。
- 远程仓库名必须以 `harness` 开头（`harness-xxx`）。
- 每张卡片的项目目录必须是 git 仓库，每次对话后提交。
- 每张卡片的对外能力注册到 **19081 Hub**，供别的卡片调用。
- 卡片对外接口统一走 `http://dimond.top:<卡片端口>`。

## 六、安全须知（重要）

面板与卡片端口都通过 frp 暴露在公网，**默认没有任何鉴权**。这意味着：

- 面板能读所有卡片日志、能给任意卡片下发指令（等于在卡片里执行命令）。
- 面板的「SSH 终端」(`/ws/ssh?container=<卡片>`) 会用内置的 `agent/agent` 直接登进卡片。
- 网页版 WebShell（19087）同理。

建议：

1. 给面板 / WebShell 加一层 Basic Auth 或反向代理鉴权。
2. 把卡片 sshd 的 `PasswordAuthentication` 关掉，只用公钥（`authorized_keys`）。
3. 定期检查 `docker logs hermit-control-19080` 里的访问记录与卡片里的 `~/.bash_history`。
