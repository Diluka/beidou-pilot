# 项目导航与边界

- 本项目首先是**游戏客户端自动化工具**：宿主 `workbenches/workbench` 选择角色，容器内 `beidou-pilot` 观察、提交 tick Lua、装载/取消脚本并核对结果。伴游机器人是建立在该工具之上的**应用层**，设计见 `docs/COMPANION_BOT.md`，不是客户端内置策略，也不是已交付能力。
- 文档按类别阅读：产品与使用、接口契约、设计与路线、研究记录、维护流程；入口是 `docs/README.md`。当前能力以 `docs/ARCHITECTURE.md`、`docs/CLI.md`、`docs/LUA_TICK_API.md` 和当前 `capabilities` 为准；研究记录（如 `docs/V17_*`）不是产品契约。
- 旧 Issue/PR 是当时记录，不是当前路线图。需要长期保留的结论应整理进分层文档；不要从历史讨论推断现状，也不要把旧单勾选当作能力证明。
- `AGENTS.md` 是维护约定入口：分区/授权/工作台/验证/合并/记忆维护。`docs/business-map/README.md` 按客户端领域导航；伴游机器人不单独作为客户端领域。
- 运行实例由 Docker 容器拥有；Lua 动作返回/取消保持实例，`close` 独立结束容器。实例关闭与动作锁分别管理，活动 Lua 期间仍可正常关闭。
- `shared/lua-runtime/TickRuntime.*` 是唯一 Lua 引擎（逐次决策）。脚本统一按 tick 执行、无需声明引擎；多会话共享客户端唯一 `player` 状态机，后写覆盖。入口与契约以 `docs/LUA_API.md`、`docs/LUA_TICK_API.md`、`docs/CONTROL.md` 为准，不在记忆复制 API。
- 伴游机器人的当前边界：客户端只保留原版 GUI 后端；玩家私聊/自然语言、队伍、NPC 交互、运行时跨图路线、交易和手动 AP 仍是缺口。机器人包迁移到 GUI 尚未完成。未交付能力不得写成已支持。
- Serena 保存稳定开发知识；游戏资产、账号与运行数据保留在所属环境。环境与依赖入口见 `mem:tech_stack`；常用命令见 `mem:suggested_commands`；易误改约束见 `mem:conventions`；验证范围见 `mem:task_completion`；记忆维护见 `mem:memory_maintenance`。
