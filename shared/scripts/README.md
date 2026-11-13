# 共享 Lua 脚本

这里保存随客户端镜像固定的复合策略和 API 示例，供 headless 与 GUI 客户端使用。各脚本用途和当前入口见下表；后端实际支持范围仍以当前能力声明和 [Lua API](../../docs/LUA_API.md) 为准。

这些策略仍是初步脚手架，现有阈值、时序和流程会按真实游戏行为调整，后续可能重写或替换。“当前使用”表示有现行调用入口。标为“弃用”的脚本保留现有调用，新脚本不推荐依赖，后续可能改写或移除。

## 旅行：`travel/`

| 文件 | 作用 | 当前入口与限制 |
| --- | --- | --- |
| [move_to.lua](travel/move_to.lua) | 根据位置反馈移动到当前层的目标 X，停止后再次确认到达。 | CLI `move X`；负责同层横向对齐，跨层与跨图路线由旅行函数库组合。 |
| [climb_to.lua](travel/climb_to.lua) | 靠近并对齐单根绳梯，向目标 Y 攀爬，检查最终位置。 | CLI `climb X --to-y Y`；单次局部攀爬，确认失败时停止。 |
| [enter_portal.lua](travel/enter_portal.lua) | 接近单个门户，只发送一次进入动作，再观察换图或同图传送结果。 | CLI `portal NAME`；门户需在当前可接近层。 |
| [walk_to.lua](travel/walk_to.lua) | 按静态地形图把角色移动到当前地图的目标坐标：走、跳台、落层、绳底跳抓；竖直墙把平台切成不同区间。 | CLI `move X --to-y Y`；每段执行后重新采样再规划，执行失败的边本次会话禁用；失败信息带地图、坐标、阶段与原因。 |
| [_route.lua](travel/_route.lua) | 普通 Lua 函数在同一预算内组合已知同层移动、落层和相邻地图门户，按阶段核对身份与到达。 | `script run/start --library travel`；接口见 [Lua API](../../docs/LUA_API.md#可选旅行函数库)。 |
| [_common.lua](travel/_common.lua) | 旅行脚本共用的身份、场景、生命值检查，以及横向反馈对齐。 | 内部辅助文件，由装载器自动拼接到旅行脚本前。 |
| [navigate.lua](travel/navigate.lua) | 按 CLI 打包的静态路线逐段换图：场景内寻路到门户、按上进门、核对落点与地图。 | CLI `navigate MAP_ID`；跨图路线由 Python 侧从本地门户资料计算，本策略不选路。 |
| [_move.lua](travel/_move.lua) | `walk_to` 与 `navigate` 共用的单地图执行器：逐边执行走、跳台、落层、绳梯，失败边禁用并重规划。 | 内部辅助文件，由装载器拼接到两者之前。 |
| [_terrain.lua](travel/_terrain.lua) | 单地图静态地形图：把 footholds/ropes 构建成平台区间、竖直墙与可执行边（走、跳台、落层、绳梯），并提供最短路径搜索。 | 由装载器拼接给 `walk_to.lua` 与 `combat/hunt.lua` 共用；地形规则只在这里维护。 |

## 战斗：`combat/`

| 文件 | 作用 | 状态与入口 |
| --- | --- | --- |
| [hunt.lua](combat/hunt.lua) | 在当前场景连续寻找可达怪物，结合静态地形换平台、爬绳梯、跨有限台阶或落层；可在移动时普攻或使用指定技能。 | 当前连续狩猎优先入口：CLI `hunt [MOB\|all]`，支持限时或明确的 `--continuous`。 |

`hunt.lua` 绑定启动时的实例、角色、地图和场景代次，门户与换图由独立操作处理。它支持范围、停级和生命下限；补给只尝试使用调用方明确指定的药品。无法确认进展、地形不可达或场景变化时停止，命中以实际战斗结果为准。

[island_supply.lua](examples/island_supply.lua) 是首轮已知路线消费者，`--library island-supply` 显式装载旅行函数和这一示例。调用 `island_supply.to_town()` 从50000东上层经东侧落层及门户进入1000000；`to_field()` 从城镇西入口返回50000东下层。坐标作为该示例明确提供的已知地形事实，通行仍由当前原生位置确认。它覆盖这两段已知路线，补给与养成计划由调用方决定；支持起点、结果和真实验收范围见 Lua API 与对应 PR。

启动位置接近已知绳梯时，先在总预算内尝试到达狩猎范围内的已知安全端点，并通过离开绳轴的实际横移和平台位置复采确认恢复，再继续找怪；中途失去平台时也可使用同一恢复。坐标只表示候选，原生攀爬状态按本端事实判断。没有安全端点、候选不唯一、恢复无进展或超出预算时以 `hunt_rope_recovery_*` 原因停止，被接管的控制权按现状交接。未知绳梯与任意空中位置恢复属于后续能力。

旧的 `fight` 策略及命令已移除，连续狩猎使用 `hunt`。`hunt` 不提供旧策略的近距拾取、结束时退回锚点或自动选择药品功能；需要这些行为时由调用方另行处理。

## 恢复：`recovery/`

| 文件 | 作用 | 当前入口与限制 |
| --- | --- | --- |
| [recover.lua](recovery/recover.lua) | 按次数或 HP/MP 目标用药，逐次核对库存恰减一及适用的恢复效果；达到目标、已满或预算用尽时结束。 | CLI `use ITEM --count N`、`--until-hp N`、`--until-mp N` 的原生用物路径；物品属性和参数由调用方提供，直接按物品 ID 使用。 |

明确的仅消费模式只确认库存变化；恢复效果另看 HP/MP。单次 `use_item ID` 的原生尝试与本脚本的重复消费、效果确认流程不同，具体物品分类和参数限制见 [CLI](../../docs/CLI.md#动作与-lua)。

## 示例：`examples/`

示例不由正式策略自动加载，阅读或试用时按用途选择。

| 文件 | 演示内容 | 使用边界 |
| --- | --- | --- |
| [read-state.lua](examples/read-state.lua) | 使用 `game.state()` 做只读分支和短循环，检查角色就绪、地图及存活状态。 | 只读示例。 |
| [read-domains.lua](examples/read-domains.lua) | 使用 `game.observe()` 按需读取场景、装备、任务和 UI，保留不可用及不支持状态。 | 只读，适合学习分领域观察。 |
| [common-basic.lua](examples/common-basic.lua) | 顺序调用移动、朝向、跳跃、攻击、拾取，并在低血量时尝试使用固定药品。 | 会实际移动、攻击和消耗物品；只演示动作串联。 |
| [tick-jump-attack.lua](examples/tick-jump-attack.lua) | tick 入门：保持方向助跑到接近参考最大移速再起跳，空中攻击一次，落地后停止。 | 会实际移动、跳跃和普攻；只在有足够空间的同高平地试用，不寻路、不选怪、不保证命中。 |

### tick 动作入门：连续移动跳砍

先读 [tick-jump-attack.lua](examples/tick-jump-attack.lua)，再从已登录的工作台显式运行。装备可普攻的武器，选择有足够空间的安全同高平地，确认没有其他脚本控制角色；本例不处理斜坡、台阶、绳梯、落层、怪物或传送门。已有容器须使用包含此示例及对应 tick 行为的镜像；内置文件不会随宿主源码编辑自动更新。

```bash
DIR=/你的工作台目录
SCRIPT=/opt/beidou-pilot/shared/scripts/examples/tick-jump-attack.lua

private/workbenches/workbench "$DIR" script describe "$SCRIPT"
private/workbenches/workbench "$DIR" script run "$SCRIPT" --direction right --seconds 5
private/workbenches/workbench "$DIR" snapshot

# 异步受理后返回；保留返回的 script_id，再按该 ID 查询或明确取消。
private/workbenches/workbench "$DIR" script start "$SCRIPT" --direction left --seconds 5
private/workbenches/workbench "$DIR" script status --session SCRIPT_ID
private/workbenches/workbench "$DIR" script cancel --session SCRIPT_ID
```

`--direction` 来自头部 `@option`，默认 `right`，也可为 `left`。`--seconds` 是整个原生会话的期限，不是跳跃时长；例如起跳失败时由这个期限停止等待并释放输入。本例省略 `@tick.gear` 时使用第3档（30Hz）；复制到用户脚本后，可在前导注释中显式设置，例如 `-- @tick.gear 4` 选择原生更新；1、2、3档分别为10Hz、20Hz和30Hz。低档只降低判断频率，不改变角色物理和每宿主更新的取消/放键；落地后在下一次到期判断清方向。

阅读时关注四点：`@mode tick` 选择新引擎；`main` 每次只做短判断，返回 `nil` 后下次继续；`context.state.phase` 保存“助跑 → 等待空中 → 等待落地 → 停下”的阶段，避免每次重新跳或重复攻击；`player.move` 只需设置一次，跳跃和攻击都保留持续方向，只在确认落地后 `move(nil)`，速度接近零后返回 `"done"`。

`character.velocity` 是角色自己的当前运动向量，`character.movement` 是按当前有效属性及本端物理模型推断的静止平地参考能力，两者不混用。自己、其他玩家、怪物、NPC、投射物和掉落物共享可移动物体的观察基类，每个实体各自拥有向量，世界不是运动主体。向量保留原生或原生更新区间差分的来源，未知不填零。沿目标方向达到参考移速的99%后才提交 jump：无头速度渐近稳态，不能严格比较相等，也不用固定助跑时长/距离或仅凭速度平台。完整运动参考及最大跳高的适用条件见 [运动观察](../../docs/LUA_API.md#运动观察与静止参考)。

空中阶段要求真实 `character.on_ground=false` 且 `character.y` 小于原平地Y；jump 槽空闲仅表示输入已消费和释放，不表示已经落地。两端均使用本端原生地面标志确认落地，未知时不靠重复坐标推断。速度/能力参考只阻断依赖它们的助跑或停止确认，不阻断已经具备离地事实的空中攻击。`settled` 包含停止移动等条件，不能用于全程移动的落地判断。受理与输入释放也不等于真实空中出手或命中；实际效果需原生事实或画面另行核对。

可以从这个结构扩展更多阶段，不要加入阻塞等待或混用 coroutine 的 `game.sleep()/game.state()`。tick 多会话共享 player，同客户端其他会话可能覆盖方向；初学试用只运行这一份动作示例。完整契约见 [tick API](../../docs/LUA_API.md#tick-环境)。

## 调用与维护

由 CLI 消费的旅行、战斗和恢复策略都声明 `main(context)` 与 `@option`；`script describe FILE` 可查看参数，`script run FILE` 可按同一声明传值。旅行策略的 `_common.lua` 由策略装载器按内置文件路径自动组合，其他辅助库和函数库示例仍按各自用途加载。Python 命令适配器继续负责解析游戏目录资料、预检用户输入并映射现有参数；Lua 入口从 `context.options` 取运行配置，从 `context.scene` 取身份锚点和可用静态地形。策略预算字段使用 `budget_seconds`，与 CLI 控制整个原生脚本生命周期的 `--seconds` / `--continuous` 分开。普通 Lua chunk、`--code` 与示例函数库仍保持原始语义。

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

内置脚本随镜像版本固定，已有容器保持启动时的版本。执行中断或等待失败只结束等待；先用 `script status` 查看已有会话，需要取消时明确执行 `script cancel --session SCRIPT_ID`，并核对终态及放键。

编写脚本查 [Lua API](../../docs/LUA_API.md)，装载、控制权和取消规则查 [控制协议](../../docs/CONTROL.md)，维护本目录前阅读 [AGENTS.md](AGENTS.md)。脚本返回、动作派发和离线测试属于过程证据，实际到达、消耗、恢复与战斗效果另行确认。
