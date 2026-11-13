# Lua API 文档入口

客户端提供两套独立的Lua引擎。先按脚本声明选择对应参考，API正文按引擎分别维护：

| 引擎 | 如何选择 | 独立API文档 |
| --- | --- | --- |
| coroutine（协程引擎） | 省略模式，或前导 `-- @mode coroutine` | [Coroutine Lua API](LUA_COROUTINE_API.md)：可让出的动作、状态与领域查询、任务及控制权、按键和旅行函数库 |
| tick（逐次决策引擎） | 前导 `-- @mode tick` | [Tick Lua API](LUA_TICK_API.md)：调用频率档位与预算、跨调用state、只读领域、实体运动观察和player动作槽 |

两套引擎各自拥有Lua状态、调度、控制权和取消生命周期，只在宿主必要的原生I/O边界联合输入，没有API兼容转发。不能把 `game.state()/game.sleep()/game.spawn()` 用到tick，也不能把 `game.character` 领域属性或 `game.player` 状态机用到coroutine。两端的未知事实和未支持能力按各页声明保留，不借另一后端填充。

本页只提供导航，不再混合维护函数签名或执行语义。修改公共API时更新所属引擎的参考；通用入口与传输见 [CLI](CLI.md) 和 [控制协议](CONTROL.md)，脚本维护见 [共享脚本约定](../shared/scripts/AGENTS.md)。
