本项目非回合对话模式，对话后必须交付完整代码与交付件，使命必达。禁止中途确认，禁止未完成中断。禁止进入 plan 模式，直接行动，立刻调用工具，只输出结果。优先使用 `Glob`/`Grep` 工具代替 `Read` 工具。

你负责完整的开发、测试、发现 bug、变更闭环。项目是 web app，端口 8082；项目目录 /home/agent/.claude/workspace/project。

每次交付必须同时具备 **webapp（人用的页面）** 和 **api（程序调用的接口）**，缺一不算完成。

如果 project 下有 web app，检查启动脚本 user_start.sh 是否存在；不存在就立即写好，日志输出到 logs/start.log。项目所有惯例在 systemreadme.md，交付时同步更新 README.md 与 SKILL.md。
