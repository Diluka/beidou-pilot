# Lua API 文档入口

客户端提供 tick 引擎（逐次决策）。脚本无需声明引擎，入口按会话频率档位到期调用 `main(context)`，以 `context.state` 保存跨调用状态，通过只读领域观察并使用 `game.player` 状态机提交动作意图。

[Tick Lua API](LUA_TICK_API.md) 是唯一的 Lua API 参考：调用频率档位与预算、跨调用 state、只读领域、实体运动观察和 player 动作槽。脚本统一按 tick 引擎执行，前导注释按需写 `@tick.*`。

通用入口与传输见 [CLI](CLI.md) 和 [控制协议](CONTROL.md)，脚本维护见 [共享脚本约定](../shared/scripts/AGENTS.md)。
