
## 待办 · 卡片指示灯状态管理（计划 2026-10-28 19:00 开始）

需求：
1. 容器卡片指示灯：**绿灯 = 无 agent 任务在跑；红灯 = 有 agent 任务在跑**。
2. 若状态**刚好从红变绿**，自动点击该卡片的「刷新日志」一次（等价于自动刷新该卡日志）。

现状备注：
- 卡片已有一个 status-light（idle/thinking/done 三态配色），需改成红/绿两态语义。
- agent_states 由 control 维护：send-message 时置 thinking，SessionEnd 钩子置 done，reset-state 置 idle。
  → 红/绿映射建议：thinking → 红；idle/done → 绿。
- 自动刷新：检测到 red→green 跳变时，对该卡执行一次日志刷新（前端 fetch logs 或复用 #card=<name> 逻辑）。

先不动手，19:00 再开始。