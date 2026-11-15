# Lua API 文档入口

客户端提供 tick 引擎（逐次决策）。脚本在前导注释声明 `-- @mode tick`，入口按会话频率档位到期调用 `main(context)`，以 `context.state` 保存跨调用状态，通过只读领域观察并使用 `game.player` 状态机提交动作意图。

[Tick Lua API](LUA_TICK_API.md) 是唯一的 Lua API 参考：调用频率档位与预算、跨调用 state、只读领域、实体运动观察和 player 动作槽。省略 `@mode` 时按 tick 处理，没有其他引擎的兼容入口。

通用入口与传输见 [CLI](CLI.md) 和 [控制协议](CONTROL.md)，脚本维护见 [共享脚本约定](../shared/scripts/AGENTS.md)。
