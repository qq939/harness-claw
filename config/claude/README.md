# config/claude —— 模型与端点配置

这个目录决定「卡片里的 Claude Code 连哪个端点、用哪个模型、用哪把 key」。

## 文件怎么配

一套配置 = 两个文件，同名对应：

| 文件 | 谁读 | 作用 |
|------|------|------|
| `settings.json` | 平台（建卡时注入容器进程 env） | Claude Code 的运行参数：端点、模型、key、思考档位、超时 |
| `config.json` | Claude Code 自己 | provider 定义：模型 id ↔ 端点 ↔ 展示名 |

后缀即 profile 名，例如 `settings.json.deepseek-flash` + `config.json.deepseek-flash`
构成 profile `deepseek-flash`（面板「切换模型」里可选）。

## 目录内容

```
config.json                        默认配置（当前：DeepSeek Flash）
config.json.deepseek               profile: deepseek
config.json.deepseek-flash         profile: deepseek-flash
config.json.localqwen              profile: localqwen（本地 llama.cpp）
config.json.minimax                profile: minimax
config.json.minimax-m2.7-highspeed profile: minimax-m2.7-highspeed
config.json.webqwen                profile: webqwen
settings.json …                    与上面一一对应的 settings
examples/                          脱敏模板（key 是假的），照着复制即可
```

> 带真 key 的 `config.json*` / `settings.json*` 已在 `.gitignore` 里，**不要提交**。
> `examples/*.bak` 是脱敏模板，会进仓库。

## 怎么加一个新模型

```bash
cp config/claude/examples/config.json.my-model.bak  config/claude/config.json.my-model
cp config/claude/examples/settings.json.my-model.bak config/claude/settings.json.my-model
# 编辑这两个文件：
#   settings.json → env.ANTHROPIC_BASE_URL / ANTHROPIC_MODEL / ANTHROPIC_AUTH_TOKEN
#   config.json   → claude.providers.<uuid>.settingsConfig.env.* 同上三项
```

要点：

1. `ANTHROPIC_BASE_URL` 必须是 **Anthropic 兼容** 端点。
2. `ANTHROPIC_MODEL` 填服务端真实模型 id；`ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL` 一般填同一个，
   否则 Claude Code 会拿别名去请求不存在的模型。
3. 卡片里访问宿主机用 `host.docker.internal`（不是 `localhost`）。
4. 建卡时用的是 `config.json`（无后缀）那一套；换 profile 由面板写入容器。

## 思考档位

`settings.json` 里：

```json
"CLAUDE_CODE_EFFORT_LEVEL": "high"     // low | medium | high
```

- 必须是**单数** `..._LEVEL`，写成复数 `..._LEVELS` CLI 不认（会静默失效）。
- 面板左上角「思考 高/中/低」改的就是这个值；改完 **卡片重启后生效**（进程 env 在创建时注入）。

## 改完何时生效

| 场景 | 是否立即生效 |
|------|--------------|
| 新建卡片 | 是 |
| 已有卡片改配置 | 否，需要「重建」卡片（`docker restart` 不会重新注入 env） |
| 面板切模型 | 会写文件并重启卡片 |

## 安全

- 真 key 只存在本机 `config/claude/` 里；仓库里只有 `examples/*.bak`（假 key）。
- key 进过公开仓库历史 = 泄漏，必须去控制台吊销 + 换新，删文件没用。
- 建议给所有公网暴露的面板/WebShell 加鉴权，见根目录 README「安全须知」。
