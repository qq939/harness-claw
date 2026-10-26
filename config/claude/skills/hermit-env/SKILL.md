# 八、Claude Code 环境变量

容器内已预设以下 Claude Code 相关环境变量：

  CLAUDE_CODE_TRUST_ALL=true
  CLAUDE_CODE_SKIP_ONBOARDING=true
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

ollama 类型额外预设：
  ANTHROPIC_BASE_URL=http://192.168.0.209:11435
  ANTHROPIC_AUTH_TOKEN=ollama
  OLLAMA_MODEL=qwen3.5

claude 类型可在 /agent-config/settings.json 和 config.json 中配置：
  settings.json 的 env 字段
  config.json 的 providers[].settingsConfig.env.ANTHROPIC_AUTH_TOKEN

## 大模型出口：hermit-llm-gateway

云端 api key 不再放在卡片里。卡片统一把 ANTHROPIC_BASE_URL 指向网关，
ANTHROPIC_AUTH_TOKEN 填网关口令 agent，由网关换上真正的 key 转发。

  ANTHROPIC_BASE_URL=http://hermit-llm-gateway:8083/minimax
  ANTHROPIC_AUTH_TOKEN=agent

网关只在 openclaw-network 内网可达，不发布宿主机端口、不进 frpc。
真实 key 全部集中在一处（config/llm-gateway/upstreams.json），该文件已被 .gitignore 排除。
改 key 只需改那一个文件，网关会自动热加载，不必重建卡片。
