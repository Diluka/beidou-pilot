# 共享 Lua 脚本维护约定

## 当前定位

本目录随客户端镜像固定保存两类 Lua 资产：

- `examples/`：tick 示例，用于演示 `main(context)`、`context.state` 跨调用状态、只读领域观察和 `player` 动作槽。示例不是正式策略，不承诺完整玩法流程。
- `tick/travel/`：通用跨图旅行策略包（目录脚本包），由 CLI `travel` 查询路线并注入 `context.route/context.goal` 后执行单图规划、逐边执行、低血自保与任务相位。它随镜像固定维护，但阶段能力与边界以 [Tick Lua API](../../docs/LUA_TICK_API.md#跨图旅行脚本包travel) 为准，不承诺所有地图可通行。

真实业务策略与个人角色流程仍写在工作台的 `/work/scripts`，由调用方通过 `script run/start` 或 `travel` 显式提交。`tick/travel/` 是参考实现与固定包，不是自动加载的内置策略，也不要求用户直接修改镜像内文件。

## API 文档入口

写脚本查 [Tick Lua API](../../docs/LUA_TICK_API.md)：入口、`@tick.*` 配置、上下文、只读领域、运动观察、动作槽语义和旅行注入形状都在该页维护。CLI 命令与旅行用法查 [CLI](../../docs/CLI.md)，控制、取消与放键规则查[控制协议](../../docs/CONTROL.md)。公共 API 有新增、删除或语义变化时同步更新 tick 文档；Serena 只保存入口和易误改约束，不复制另一份 API 全集。

## 职责边界

- `examples/` 只做演示，由调用方显式加载；固定角色、地图或验收流程写在测试目录。
- `tick/travel/` 是目录脚本包：`main.lua` 为入口，其余模块用相对包根的原生 `require` 装载（如 `require("terrain")`）；不在模块里写绝对路径，不改镜像内其他文件。
- 旅行包只消费调用方注入的 `context.route/context.goal`，不解析世界门户模型、不在运行中算路或改道；没有注入时明确失败，不伪造路线。
- 旅行包各层顺序固定为 `safety → combat → locomotion → travel_core`；`combat` 当前只是未启用的 M4 骨架，不产生攻击/技能输入，也不声称清怪。
- 脚本使用 tick 引擎的只读领域和 `context.game.player` 动作槽，不使用阻塞动作、`game.sleep()`、任务控制或旧按键接口；需要调整调度或预算时只在前导注释声明 `@tick.*`。
- 方向和动作意图只设置一次，由原生消费者保持；脚本结束时由 Runtime 确认停止所属持续输入并放键，脚本不轮询内部握手。
- 未知状态保持未知：缺失库存、地形、路线或目标按未知处理，不补零、不借用另一后端。未知只阻断依赖该事实的操作；换图或场景代次变化后重新读取并丢弃旧缓存。
- 需要新示例或新共享包时按真实能力增加，不恢复已退役的引擎或函数库；包的能力边界同时更新 README 与 API 文档。

## 迭代与验证

- `examples/` 只保留能说明公共契约、实际失败或效果确认的必要示例；`tick/travel/` 的模块边界、失败原因或注入形状变化同时更新 `docs/CLI.md`、`docs/LUA_TICK_API.md` 与本目录 README。
- CLI 合同测试放 `cli/test/`（如 `test_travel_command.py`），并加入 `tools/format.py` 白名单；Lua 模块的纯函数与模拟运行测试放任务开发目录 `tmp/<任务>/`，不随镜像或仓库提交。
- 通过条件以实际游戏结果为准，精度只取业务所需；位置偏移、随机掉落、伤害、时序等优先采用有界真实冒烟和采样。保留失败与未覆盖事实，再按影响范围回归。整体调试与验收边界见[项目约定](../../AGENTS.md#验收方式)。
