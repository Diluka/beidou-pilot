# 共享 Lua 脚本

这里保存随客户端镜像固定的复合策略和 API 示例，供 headless 与 GUI 客户端使用。各脚本用途和当前入口见下表；后端实际支持范围仍以当前能力声明和 [Lua API](../../docs/LUA_API.md) 为准。

这些策略仍是初步脚手架，现有阈值、时序和流程会按真实游戏行为调整，后续可能重写或替换。“当前使用”只说明有现行调用入口，不代表策略已经成熟。标为“弃用”的脚本保留现有调用，新脚本不推荐依赖，后续可能改写或移除。

## 旅行：`travel/`

| 文件 | 作用 | 当前入口与限制 |
| --- | --- | --- |
| [move_to.lua](travel/move_to.lua) | 根据位置反馈移动到当前层的目标 X，停止后再次确认到达。 | CLI `move X`；只做同层横向对齐，不规划跨层或跨图路线。 |
| [climb_to.lua](travel/climb_to.lua) | 靠近并对齐单根绳梯，向目标 Y 攀爬，检查最终位置。 | CLI `climb X --to-y Y`；单次局部攀爬，无法确认时停止。 |
| [enter_portal.lua](travel/enter_portal.lua) | 接近单个门户，只发送一次进入动作，再观察换图或同图传送结果。 | CLI `portal NAME`；门户需在当前可接近层，不负责前往其他层。 |
| [_route.lua](travel/_route.lua) | 普通 Lua 函数在同一预算内组合已知同层移动、落层和相邻地图门户，按阶段核对身份与到达。 | `script run/start --library travel`；接口见 [Lua API](../../docs/LUA_API.md#可选旅行函数库)。 |
| [_common.lua](travel/_common.lua) | 旅行脚本共用的身份、场景、生命值检查，以及横向反馈对齐。 | 内部辅助文件，由装载器自动拼接到旅行脚本前，不单独执行。 |

## 战斗：`combat/`

| 文件 | 作用 | 状态与入口 |
| --- | --- | --- |
| [hunt.lua](combat/hunt.lua) | 在当前场景连续寻找可达怪物，结合静态地形换平台、爬绳梯、跨有限台阶或落层；可在移动时普攻或使用指定技能。 | 当前连续狩猎优先入口：CLI `hunt [MOB\|all]`，支持限时或明确的 `--continuous`。 |
| [fight.lua](combat/fight.lua) | 在指定同层范围内接近怪物、普攻、低血量用药，按需尝试近距拾取，结束阶段尝试退回锚点。 | **弃用，新狩猎不推荐**；现有 CLI `fight MOB` 仍调用它。 |

`hunt.lua` 绑定启动时的实例、角色、地图和场景代次，不穿门户，也不在换图后续跑。它支持范围、停级和生命下限；补给只尝试使用调用方明确指定的药品。无法确认进展、地形不可达或场景变化时停止，攻击尝试次数不代表命中。

[island_supply.lua](examples/island_supply.lua) 是首轮已知路线消费者，`--library island-supply` 显式装载旅行函数和这一示例。调用 `island_supply.to_town()` 从50000东上层经东侧落层及门户进入1000000；`to_field()` 从城镇西入口返回50000东下层。坐标作为该示例明确提供的已知地形事实，通行仍由当前原生位置确认。它不探索其他地图、不隐式补给，也不改变养成计划；支持起点、结果和真实验收范围见 Lua API 与对应 PR。

启动位置接近已知绳梯时，先在总预算内尝试到达狩猎范围内的已知安全端点，并通过离开绳轴的实际横移和平台位置复采确认恢复，再继续找怪；中途失去平台时也可使用同一恢复。坐标只表示候选，不公开或伪造原生攀爬状态。没有安全端点、候选不唯一、恢复无进展或超出预算时以 `hunt_rope_recovery_*` 原因停止，不自动抢回被接管的控制权。不覆盖未知绳梯或任意空中位置恢复。

`fight.lua` 是旧的同层战斗脚手架，内置固定距离、等待时间和药品选择，补给没有逐次核对库存消耗与恢复效果。不建议把这些固定流程作为新策略的依赖。新连续狩猎优先使用 `hunt`；`hunt` 尚不包含 `fight` 的 `--loot` 拾取和退回 `retreat_x` 锚点行为，迁移时需单独处理这些需求。

## 恢复：`recovery/`

| 文件 | 作用 | 当前入口与限制 |
| --- | --- | --- |
| [recover.lua](recovery/recover.lua) | 按次数或 HP/MP 目标用药，逐次核对库存恰减一及适用的恢复效果；达到目标、已满或预算用尽时结束。 | CLI `use ITEM --count N`、`--until-hp N`、`--until-mp N` 的原生用物路径；物品属性和参数由调用方提供，不操作 GUI 槽位。 |

明确的仅消费模式只确认库存变化；是否恢复仍需另看 HP/MP。单次 `use_item ID` 的原生尝试与本脚本的重复消费、效果确认流程不同，具体物品分类和参数限制见 [CLI](../../docs/CLI.md#动作与-lua)。

## 示例：`examples/`

示例不由正式策略自动加载，阅读或试用时按用途选择。

| 文件 | 演示内容 | 使用边界 |
| --- | --- | --- |
| [read-state.lua](examples/read-state.lua) | 使用 `game.state()` 做只读分支和短循环，检查角色就绪、地图及存活状态。 | 只读，不发送动作。 |
| [read-domains.lua](examples/read-domains.lua) | 使用 `game.observe()` 按需读取场景、装备、任务和 UI，保留不可用及不支持状态。 | 只读，适合学习分领域观察。 |
| [common-basic.lua](examples/common-basic.lua) | 顺序调用移动、朝向、跳跃、攻击、拾取，并在低血量时尝试使用固定药品。 | 会实际移动、攻击和消耗物品；仅演示动作串联，不作为战斗、恢复或效果验收策略。 |

## 调用与维护

六个仍由 CLI 消费的旅行、战斗和恢复策略都声明 `main(context)` 与 `@option`；`script describe FILE` 可查看参数，`script run FILE` 可按同一声明传值。旅行策略的 `_common.lua` 由策略装载器按内置文件路径自动组合，其他辅助库和函数库示例仍按各自用途加载。Python 命令适配器继续负责解析游戏目录资料、预检用户输入并映射现有参数；Lua 入口从 `context.options` 取运行配置，从 `context.scene` 取身份锚点和可用静态地形。策略预算字段使用 `budget_seconds`，与 CLI 控制整个原生脚本生命周期的 `--seconds` / `--continuous` 分开。普通 Lua chunk、`--code` 与示例函数库仍保持原始语义。

内置策略随镜像位于 `/opt/beidou-pilot/shared/scripts/`，可以通过通用入口直接查看和调用，例如：

```bash
beidou-pilot script describe /opt/beidou-pilot/shared/scripts/travel/move_to.lua
beidou-pilot script run /opt/beidou-pilot/shared/scripts/travel/move_to.lua \
  --x 400 --budget-seconds 20 --seconds 21
```

自定义策略放工作台的 `scripts/`，在容器内对应 `/work/scripts/`，通过统一宿主入口提交：

```bash
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --seconds 20
```

内置脚本随镜像版本固定，修改仓库文件不会更新已有容器。执行中断或等待失败只结束等待；先用 `script status` 查看已有会话，需要取消时明确执行 `script cancel --session SCRIPT_ID`，并核对终态及放键。

编写脚本查 [Lua API](../../docs/LUA_API.md)，装载、控制权和取消规则查 [控制协议](../../docs/CONTROL.md)，维护本目录前阅读 [AGENTS.md](AGENTS.md)。脚本返回、动作派发或离线测试通过均不能替代实际到达、消耗、恢复或战斗效果确认。
