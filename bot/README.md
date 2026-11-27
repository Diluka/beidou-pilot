# 伴游机器人 Lua 包

该目录是可复制到角色 `/work/scripts/bot` 的 tick 脚本包。`lib.io`、`lib.state`、`lib.world` 与 `main.lua` 提供指令邮箱、状态/事件发布、基础世界投影和 tick 主流程；`lib.terrain` 提供只读地形构图、平台定位与 A* 路径规划。`lib.move`、`lib.follow`、`lib.combat`、`lib.sustain` 与 `lib.loot` 实现其各自当前覆盖的行为；具体限制以模块和离线/真实场景验收为准。机器人从 `/work/bot` 读取配置与命令，并写状态、事件和回执。

`main.lua` 按 tick API 定义唯一的顶层 `local function main(context)`。tick 加载器会在内部编译并包装入口，因此不需要、也不应从用户脚本返回一个模块表。此骨架不会在顶层调用 `game` 或 `player`。

## 模块接口

| 模块 | 函数签名 |
| --- | --- |
| `lib.terrain` | `build(navigation)`、`platform_at(graph, x, y, tolerance)`、`plan(graph, from_index, to_index, options)` |
| `lib.move` | `new(graph)`、`set_path(mover, edges)`、`step(mover, ctx, world)`、`stop(mover)` |
| `lib.follow` | `update(ctx, world)` |
| `lib.target` | `selector(target)`、`step(ctx, world, navigation, kind, name, ensure_mover)` |
| `lib.combat` | `select(world, options)`、`step(ctx, world, mob, mover)` |
| `lib.sustain` | `step(ctx, world)` |
| `lib.loot` | `select(world, options)`、`step(ctx, world, drop, mover)` |
| `lib.io` | `poll(ctx, now)`、`publish(ctx, world, now)`、`event(ctx, kind, data)` |
| `lib.state` | `new()`、`apply(state, command)`、`transition(state, mode, reason)` |
| `lib.world` | `observe(ctx)` |

未实现的行为模块按签名返回 `nil, "not_implemented"`、`false, "not_implemented"` 或 `"failed", "not_implemented"`。terrain 的 `build`、`platform_at` 和 `plan` 已实现；接口及数据结构契约以 [`docs/PHASE1.md`](../docs/PHASE1.md) 为准，terrain 与邮箱/状态/世界行为均有离线用例覆盖。

## 运行范围与已知限制

机器人具备平台巡逻、绳梯与水平跳、顺路拾取、掉层恢复、远程距离筛选和普通门户绑定回图。目标可达性与战斗效果依赖现场地形；跨平台弹道/命中尚待真机确认。同平台拾取扫荡尚未合入并待验证。城镇门户 `landing_mismatch`、NPC/商店后输入冻结、`tick_overrun` 根因及自动补给闭环限制见[客户端能力](../docs/CLIENT_LIMITATIONS.md#伴游机器人当前能力和限制)。

常驻服仅按已授权计划正常游玩，不使用 GM 写入或直接修改数据库；交互后若输入冻结，按工作台关闭重开并核对实际输入。`lib.metrics` 已合入但主流程未接线，安装后不会自动产生指标。

## 低补给停手

可选的 `/work/bot/supply.conf` 启用低水位检查。例如：

```ini
red_item=2000000
red_low=5
blue_item=2000003
blue_low=3
arrow_item=2060000
arrow_low=50
```

只检查配置的物品，每种的 item 与 low 必须成对且为正整数；不写文件则不启用。狩猎时低于阈值、库存不可读或配置错误会发布 `supply/low`、撤下动作并结束脚本。事件发生不代表已确认放键，须查询该会话终态和 `control_released`。停止的位置不保证安全；当前尚无自动补给与回图编排，切勿在活动脚本期间操作商店。

## 地形平台定位

`lib.terrain.build(navigation)` 直接消费 `context.scene.terrain.navigation`，返回引用原始数据的 graph；成功时包含 1 基平台数组以及原样保留的 `walls`、`ropes`、`candidates`、`model` 和地形边界。输入缺失时返回 `nil, "navigation_unavailable"`；必需字段或结构无效时返回 `nil, "navigation_invalid:<field>"`，不会重新从 footholds 派生平台。

`lib.terrain.platform_at(graph, x, y, tolerance)` 按平台 `segments` 线性插值高度，仅在平台与线段范围内且高度差不超过容差时返回平台索引；重叠命中时选高度差最小者，平局选索引较小者，无命中返回 `nil`。坐标使用地图像素，y 向下为正。示例：

```lua
local terrain = require("lib.terrain")
local graph = assert(terrain.build(context.scene.terrain.navigation))
local platform = terrain.platform_at(graph, context.game.character.x, context.game.character.y, 25)
game.log("platform=" .. tostring(platform))
```

`lib.terrain.plan(graph, from_index, to_index, options)` 消费候选边，用 A* 按 `walk`、`step`、`jumpup`、`drop`、`rope` 的策略代价生成连续路径；`options.blocked` 可按 `"from:to"` 禁边，跳跃高度、速度可选调整。无路返回 `nil, "no_path"`，非法平台与模型缺失分别返回 `invalid_platform`、`model_unavailable`。上述 terrain 接口只读地形快照，不执行移动或 `player` 动作。

## 安全挂机平台分析

宿主工具 `tools/safe_platforms.py` 读取当前场景和静态地图，列出满足以下条件的平台：平台内没有静态刷怪点或当前场景怪物、怪物无法到达、玩家可从当前平台到达。它不发送游戏输入，只调用工作台的只读 `inspect scene` 与 `inspect map <id>`：

```bash
tools/safe_platforms.py dev/NAME
tools/safe_platforms.py dev/NAME --json
```

默认输出按路径代价排序的安全平台（平台号、x 范围、y、路径边摘要与长度）、推荐平台，以及被排除平台的原因（`spawn`、`monster_reachable`、`player_unreachable`、`monster_unlocated`）。刷怪来源同时包含 `inspect map` 的静态刷怪点和 `inspect scene` 的当前怪物快照，避免把已经站怪的平台判成安全。`--json` 额外给出平台、移动边、刷怪点、怪物可达集合与玩家可达集合。

平台由 footholds 按与原生 `shared/lua-runtime/SceneNavigation.h` 相同的链式合并规则组装，因此平台号与 `context.scene.terrain.navigation.platforms` 对齐。移动边在本工具内重建：

- 同平台行走；
- 下落：目标平台更低，且 x 范围重叠或水平边缘距离不超过 `drop_max`；
- jumpup：目标更高、上升不超过 `jump_rise`、水平间距不超过 `jump_gap`（默认 `jump_rise + stand_height`）；
- rope：按绳索与平台层生成上下边。

玩家可达集合从当前平台用 `walk`/`drop`/`jumpup`/`rope` 边做 Dijkstra；怪物可达集合从所有刷怪点所在平台出发，只允许同平台行走和向下掉落，不允许爬绳和跳台阶。模型常量默认值与 `SceneNavigation.h` 的 `kBodyHeight/kJumpRise/kDropMin/kDropMax/kRopeGrab` 一致，可用 `--jump-rise`、`--jump-gap`、`--drop-max`、`--stand-height`、`--rope-grab` 覆盖。

可选 tick 脚本 `bot/safe_spot.lua` 在场景内按同一规则计算安全平台，选择最近的玩家可达安全平台，并用 `lib.move` 沿 `terrain.plan` 路径走过去；当前平台已经安全时只报告坐标，没有可达安全平台时报告 `no_safe_platform`。它必须随 `bot` 包一起安装后运行：

```bash
tools/botctl install dev/NAME
workbenches/workbench dev/NAME script run bot/safe_spot.lua --seconds 30
```

限制：

- 怪物模型使用静态刷怪点和当前场景怪物的平台归属，未建模怪物巡逻范围 `rx0/rx1`、跳跃、爬绳、瞬移或召唤；地图存在这类怪物时，安全结论不保证。
- 刷怪点无法定位到平台时按全图不安全处理；地图只有 `link` 引用、没有本地 footholds 时工具直接报错。
- 玩家模型不建模墙和头顶平台对跳跃的遮挡，也不单独推导 `horizontal_jump`/`downjump`；它比客户端原生 `terrain.plan` 保守或近似。`safe_spot.lua` 在移动前会用 `terrain.plan` 逐个验证安全候选，规划失败即报告而没有安全目标。
- `safe_spot.lua` 只使用场景中的当前怪物位置，不读取静态刷怪点；宿主工具同时使用静态刷怪点和当前怪物快照，长期安全性以宿主工具为准。
- 分析只针对当前地图和当前时刻，不计算跨图、出租车/船等脚本交通。

## 默认值

默认配置键与值如下（契约来源见 [`docs/PHASE1.md`](../docs/PHASE1.md) 的 config keys 表）：

| 键 | 默认值 |
| --- | --- |
| `owner_name` | `""` |
| `owner_character_id` | `0` |
| `attack_skill_id` | `0` |
| `attack_mode` | `"melee"` |
| `attack_range` | `110` |
| `min_range` | `60` |
| `ranged_skill_id` | `3000002` |
| `ranged_skill_bonus_per_level` | `15` |
| `ranged_skill_level` | `0` |
| `skill_mp_cost` | `10` |
| `ammo_item_id` | `2060000` |
| `ammo_low` | `50` |
| `hp_item` | `0` |
| `mp_item` | `0` |
| `follow_distance` | `80` |
| `stop_distance` | `40` |
| `pot_hp` | `60` |
| `pot_mp` | `30` |
| `loot_radius` | `150` |
| `metrics_enabled` | `1` |

将配置写入角色 `/work/bot/config.conf`，格式为 `key=value`，例如 `owner_name=Owner`、`owner_character_id=123`。缺失或无法解析的值使用表中默认值。

## 指令、状态与事件

把每条命令写入 `/work/bot/queue/slotN.cmd`（N 为 1 至 8），每行一个 `key=value` 字段。`id/kind/ttl/source` 必填，正 TTL 还需 `created_ms`（Unix 毫秒），`target` 可选；`kind` 仅支持 `follow`、`hunt`、`stay`、`status`、`stop`，`source` 为 `host` 或 `cli`。例如：

```text
id=c1
kind=status
ttl=10
created_ms=1760000000000
source=host
```

宿主先把完整内容写入临时文件，选取空槽后 rename 到槽位；单一写入者避免槽位竞争。脚本约每 0.5 秒按槽号扫描，以 rename 领取为 `.processing`。Windows 下覆盖已有 state 的 rename 失败后会删除旧文件再重试，因此更新存在短暂无文件窗口，不保证严格原子替换。命令处理后写入 `queue/done/<id>`（内容 `ok`）或 `queue/rejected/<id>`（内容 `rejected=<reason>`）；重复 ID 不会再次执行，最近 100 个 ID 会留在会话内去重。`ttl=0` 不过期；正 TTL 从命令内 `created_ms` 起计时，过期命令写入拒绝回执。`status` 立即发布状态。

follow 返回 `wait` 时主流程停止现有 mover；目标平台或场景代次变化，或 owner 的期望位置移动达到 `stop_distance` 时重算路径，同平台内的小幅位置变化继续复用路径。自然场景中 owner 与 bot 位于不同平台且路径规划返回 `no_path` 时，跟随不能保证接近目标；原 headless dev 冒烟在修复后仍观察到 `follow/wait: owner_platform_unreachable`；headless 已退役，跨平台跟随效果按当前 GUI 场景观察。

### 一次性场景目标与无目标等待

在普通 `kind=follow` 邮箱命令的 `target` 字段中可指定 `npc:<名称>`（也可用 NPC 模板 ID）、`portal:<名称>` 或 `point:<名称>`。NPC 从当前场景按精确名称/模板 ID 定位并锁定实体；门户与练级点坐标由角色 `/work/bot/targets.conf` 只读提供：

```text
<map_id>:point:<名称>=<x>,<y>
<map_id>:<instance_id>:<scene_generation>:portal:<名称>=<x>,<y>
```

门户坐标须从当前实例的 `inspect scene`/`inspect map <map_id>` 唯一匹配后导出；实例、地图或场景代次不符时不会复用。所有导航复用当前场景地形图的 `terrain.plan` 与 `move`；同平台仍执行末段移动。只有角色接地、位于目标平台且进入目标范围才发 `target/arrived`；门户范围使用自身边界，NPC/点目标使用 `stop_distance`。到达后不代做 NPC 对话或门户交互；目标缺失/消失、坐标或平台未知、无路及执行失败以 `target/wait` 给出原因，并停止输入、回到 idle。

`hunt` 优先攻击观察到的怪，其次处理安全的掉落；无目标时在当前地图按平台候选顺序逐次规划巡逻，路径失败则记录并跳过，覆盖一轮后等待刷新。跨平台拾取依赖地形路径；当前保护仅按 owner 距离判断，不包含掉落归属判断。`hunt/patrol`、`hunt/platform`、`hunt/skip`、`hunt/recover`、`hunt/cycle` 和 `loot/navigate` 事件记录规划与实际状态，路径受地形和移动能力限制，GUI 实际效果需按地图验证。

`/work/bot/state.json` 常规间隔约 1 秒更新，Windows 覆盖回退时有短暂缺失窗口；`/work/bot/events.jsonl` 记录命令、模式和错误事件，单文件达到 1 MiB 时滚动到 `events.1.jsonl`。启动进入 `recover`；世界就绪且当前场景有可用地形图时转为 `idle`，不要求 `move.new` 已实现。mover 仅在 follow/hunt 产生实际移动或目标动作时才按场景代次尝试创建。checkpoint 当前只校验并保留，不重放上次动作或恢复旧模式/目标。

`tick/slow` 是状态发布间隔候选：两次成功发布的 `os.time()` 整数秒之差至少 3 时最多每 60 秒记录一次，包含 tick index、delta、动作类别和 `reason=unknown`。它使用系统墙钟且只有秒级精度，可能受调度、钟表调整或发布节流影响，不表示单次 tick 超时，也不区分 CPU 和 IO；Lua tick 上下文不暴露预算值，`budget_ms` 为 null。\n\n`state.json.session_id` 取自只读 `context.tick.script_id`，即当前 Runtime tick 会话 ID。

## 宿主运行手册

前置条件：宿主具备 Python 3、`workbenches/workbench`，并已准备对应分区的工作台角色；`dev` 服已就绪。角色只能写成 `live/NAME` 或 `dev/NAME`。仓库根目录执行：

```bash
tools/botctl install dev/NAME
tools/botctl plan dev/NAME --hunt-map 20000
tools/botctl start dev/NAME
tools/botctl send dev/NAME --kind status --ttl 10
tools/botctl status dev/NAME
tools/botctl logs dev/NAME --lines 50
tools/botctl stop dev/NAME
```

`install` 从当前检出复制并覆盖 `scripts/bot` 中的机器人代码，创建邮箱目录但保留 `state.json`、事件日志等角色状态；`start` 仅经 workbench 发布连续 tick 脚本，不启动客户端；`status` 同时显示 workbench 脚本状态和 `state.json`；`stop` 根据当前 `script.id` 发起取消，并检查脚本终止与 control_released；`logs` 默认显示最近 50 行。客户端关闭仍由 workbench 单独管理。

`send` 使用单一宿主发送者，先写临时文件再以不覆盖的硬链接发布到空槽，最多等待回执 3 秒。超时不代表命令未执行，不要重发；先检查原命令 ID 的回执与状态。启动后遗留的 `.processing` 会拒绝为 `interrupted`，不重放旧动作。

配置键及状态/事件字段见上方“默认值”“指令、状态与事件”。常见故障：

- “没有运行中的 bot script”：先运行 status；脚本已结束时无需 stop，也不要重复 start。
- `/work/bot` 写入失败：检查角色目录挂载权限与空间，勿用宿主绕过 workbench 写客户端状态。
- 脚本已结束或状态输出无法确认放键：按 status 检查终态；未确认 control_released 时将其视为停止未验收，不要关闭/重启客户端来掩盖现场。
- NAME 格式错误：必须提供 `dev/角色名` 或 `live/角色名`。

## 跨图寻路

先安装 bot 并让客户端入图，然后可用 `tools/botctl plan dev/NAME --hunt-map 20000` 从当前场景地图调用 `bot_route.py` 生成 `/work/bot/route.json`，并更新 `/work/bot/plan.conf` 的 `hunt_map` 和 `plan_revision`。已有其他计划项保留，旧的 `route` 路径覆盖会清除；观察或寻路失败时原计划和航线保持不变。此命令只规划，不启动脚本或切换模式。idle 或 hunt 模式下，地图不同时 bot 使用路线前往目标；到达后保持原模式。显式 stop/stay 暂停自动旅行，发送 hunt 可恢复。路线不可用时等待，不在错误地图狩猎。每次重规划更新 revision，使失败后的同目标路线可以重新尝试。

也可手动在宿主侧生成航点，再交给独立 tick 脚本执行：

```bash
# 生成从 10000 到 20000 的航点（写入角色 bot/route.json）
python3 tools/bot_route.py dev/NAME 10000 20000 \
  --output private/workbenches/dev/NAME/bot/route.json

# 在客户端内逐航点走到传送门并按上
workbenches/workbench dev/NAME script run bot/travel.lua --seconds 240
```

- 航点来源是客户端原生 `world-map route`，只覆盖普通门户；船、出租车等脚本交通不在图中，找不到路线时返回非零并提示人工分段处理，不能保证识别所有脚本门。
- 每个航点执行 `terrain.plan` + `move.step` 到传送门坐标，再按上并确认换图；失败重试一次，仍失败或超时则释放输入并返回原因，`no_path` 不会盲目直走。
- 执行日志会记录 `leg i/N map=... plan ... -> portal ...` 与换图结果，便于核对。

## 持久化状态（memory）

以下描述独立模块接口；当前 defaults 不含 `memory_enabled`，主包的持久化分支未启用，不应把模块能力当成已接线运行能力。

- 路径 `/work/bot/memory.lua`（可读 Lua 表，`schema = 1`），先写 `.tmp` 再 rename；Windows 覆盖回退时存在短暂缺失窗口，上限 64KB；
- API：`lib.memory` 的 `load/save/get/set/unset/flush/clear/reconcile/repair_meta`；命名空间约定 `bot`（模式/目标/地图等）、`supply`（补给阶段/上次商店）、`quest`（任务进度缓存）；
- 损坏文件自动改名为 `.bak` 并重置，不崩溃；`schema` 变化由 `repair_meta` 迁移；
- **客户端状态是唯一权威**：启动时与运行中定期用 `character/scene/inventory/quests` 的实时观察调用 `reconcile(store, namespace, live)`，冲突字段一律覆盖为 live 值并记录修复项；调用方应发布 `memory/repair` 事件；
- `flush` 节流 ≥1 秒；只缓存"客户端无法直接观察"的事实（巡逻进度、上次商店图、阶段），可观察事实每 tick 以 live 覆盖，禁止用旧缓存代替观察。

### 装备换装与待卖清单（equipment）

- 命名空间 `equipment`：`equipped`（客户端权威快照）、`sell_list`（待卖清单，含 `approved`）、`candidates`；
- 换装对账：客户端 `equipped` 变化时，被替换的旧装备自动加入 `sell_list`（`approved=false`，不自动卖），新增装备更新快照；
- 独立调用 `reconcile` 时以提供的客户端 `inventory/equipped` 为准：清单/候选里已不存在的物品移除，仍存在的保留。只有调用方接线并成功保存 memory，清单才会持久化；当前主包的 memory 分支未启用。
- 模块中的批准标记可由调用方以 `equipment.approve(store, item_id)` 设置；这不代表主包已接入自动清包或自动出售。

## 战斗模式（近战/远程/技能）

`config.conf`（或 defaults）可配置：

```ini
attack_mode=ranged                 # melee | ranged | skill
attack_range=110                   # 弓/弩基础射程，不含技能加成
min_range=60                       # 过近后撤阈值
ranged_skill_id=3000002            # 远程箭（弓箭手 1 转）
ranged_skill_bonus_per_level=15    # 远程箭每级射程增量
ranged_skill_level=0               # 技能列表不可读时的手动档位
attack_skill_id=1000               # skill 模式主攻技能；MP 不足回退普攻
skill_mp_cost=10
```

远程/技能模式的有效射程按武器与已学技能计算：`attack_range + 已学远程箭等级 × ranged_skill_bonus_per_level`。

- 技能等级优先取客户端观察 `game.character.skills`；`skills_complete=false` 或技能列表不可读时使用配置的 `ranged_skill_level`；
- 远程箭 `3000002` 数据来自客户端 `Data/Skill/300.img/skill/3000002`：最高 8 级，`range` 依次为 15/30/…/120，即每级 +15；
- 弓/弩基础射程 110 来自真机距离预判，原版客户端公式待核实；其他武器可按实测改 `attack_range`；
- 弓箭手默认：未学远程箭时射程 110px，远程箭 8 级后 230px。

- `ranged`：进入有效射程即停、转向、`player.attack()`（弓/弩消耗箭矢），`< min_range` 先后撤，不贴脸；
- `skill`：MP 足够时 `player.skill(attack_skill_id)`，否则普攻；目标丢失/切换时释放技能意图；
- `melee`：保持旧行为（60px 内普攻）。
弓箭手推荐：`attack_mode=ranged`，技能可用后改 `skill`。

### 远程走位与平台限制

狩猎时，远程和技能模式优先从安全的当前平台攻击射程内其他平台的怪：仅接受水平距离在射程内、垂直差不超过 40px 且墙与平台边界未阻断的目标，不为跨平台目标追击或换位。射程使用已学远程箭或配置兜底值；`combat/ranged_target` 和 `combat/range_blocked` 记录选择与阻断。几何判断仅为保守近似，弹道和命中需真机验证。

远程和技能模式下，目标小于 `min_range` 时释放攻击输入，以同平台有界步行后撤；平台边缘或墙的可用退距不足 `min(40, min_range/2)`、地形不可用或移动失败时放弃目标并记录 `combat/retreat_blocked`。巡逻跳过宽度小于 `min_range + 60` 的平台并按场景记录 `hunt/skip`；狩猎不会攻击该类平台的目标。贴身时无论血量均不输出；无药时 `sustain/no_potion` 事件限频记录，主流程继续；不保证可以脱离追击。墙与平台判断依赖当前地形快照，真实效果仍需客户端验证。

## 刷怪指标采集合同

主流程默认启用 `lib.metrics` 被动采集，在 `/work/bot/config.conf` 设置 `metrics_enabled=0` 可关闭，默认值为 `1`。初始化失败会记录 `metrics/error` 并在本会话禁用；采集调用异常限频报告，不阻塞原有动作。采集在平台投影后观察、跟踪狩猎目标，并记录明确的卡住事件；平台或场景变化仅记录变化事实，不猜测选择原因与采样策略。当前喝药返回值只表示请求，拾取 `picked` 可能只是掉落消失，均不能证明实际消耗或拾取，故不计为确认事件；死亡和 HP 净下降由模块观察，避免重复计数。它不执行动作或选点评分。退出及异常可能在下次周期写入前发生，不能保证最后一个窗口落盘。

```lua
local metrics = require('lib.metrics')
local samples = assert(metrics.new('/work/bot/metrics.json'))
metrics.observe(samples, context, world) -- 每 tick；失败只记录，不影响动作
metrics.target(samples, selected_mob)   -- 无目标传 nil
metrics.event(samples, 'hp_potion', {map_id=world.map_id, platform=platform, mob_template=template})
```

文件为 `schema: 1`、`records` 数组；每条记录是一段窗口内的 `map_id`、怪物所在 `platform`、`mob_template`（未知为 null），`scene_generation`、`window_start/window_end` 是脚本 tick 秒和场景代次，不是跨会话的墙钟。`sample_windows` 是窗口数；`dwell_s` 只计角色停留的平台上，连续两次观察到该怪种的时间；不同怪种的暴露可以重叠，不能相加作为平台总驻留。未观察到怪不等于没有刷怪。`kills` 是目标消失或不活跃的估计次数，`estimated` 和 `kill_source` 标明估计来源，不代表服务端确认击杀；切图不会计为击杀。经验取客户端 `character.experience`（回退 `exp`），仅在调用方额外提供可信唯一归因标志 `world.metrics_exp_attributable=true`、同一采样区间等级不变且经验上升时归入目标，仍是估计；当前主流程没有该标志，经验按未知处理；无法归属时 `exp_unknown_kills` 增加且该窗口的 `exp` 为 null。升级、多人攻击或多目标引起的经验变化可能无法归因。

`kills` 仅涵盖调用方持续提供的选中目标，并非全场怪物死亡数；零值仅在调用方明确提供 `world.metrics_targets_complete=true` 时可用，当前主流程不提供该标志。`kill_time_sum/kill_time_samples` 是选中到估计结束的秒数及样本数；`hp_potions/mp_potions/arrows`、`drops_seen/drops_picked`（按物品 ID）、`damage_taken/deaths/stuck_events` 分列保留原始计数；HP 净下降及死亡仅归角色平台、不归怪种，净下降会被同时发生的治疗抵消。null 是未知，不等于零；调用方必须在有足够证据时才传递事件，按键请求不等于物品实际消耗或拾取成功。`complete` 仅在调用方对每次观察明确提供 `world.metrics_complete=true` 且无观察缺口、掉视野或切图时为 true；现有 world 投影未提供此标志，接线不得擅自视为完整。间隔超过 2 秒、观察缺失、切图或目标消失使窗口不完整；不完整窗口不能用于计算速率。`insufficient` 表示本窗口击杀数小于 5 或驻留不足 60 秒；跨窗口分析应先合并完整窗口后重新判断样本量。

调用方在 `observe` 之后、下一采样之前可用 `metrics.visit(samples, {arrival_reason=..., exit_reason=..., collection_policy=..., policy_seed=...})` 显式登记新的一次平台访问；它截断此前目标和采样基线；上次访问的 `exit_reason` 写入关闭窗口，新的进入原因、规则 ID、种子、`visit_start` 写入新窗口。`entries` 为已知访问中该怪种的首次记录次数，缺少访问事件为 null；它不等于全图访问次数。漏采或切图按不完整窗口截断；未知离开原因不可当正常巡逻。建议使用中性、可复现轮转或随机采样并覆盖可达平台，不要依据当前效率选择，采样不足不能用于推断平台优劣；本模块不实现调度或声称采样公平。`kill_time_sum` 允许目标跨窗口，完整时长归入结束窗口，跨缺口或场景变更不计。

每约 20 秒将已关闭窗口写入 `/work/bot/metrics.json`，先写临时文件再 rename；Windows 覆盖回退有短暂无文件窗口。单文件上限 256 KiB，最多保留当前及 `metrics.1.json` 两代，继续滚动会丢弃最旧一代并发布 `metrics/rotate`；宿主必须定期复制以保存更长历史。采集异常应由接线方旁路处理，不得阻塞机器人动作。宿主可选使用 `python3 tools/farm_stats.py dev/NAME --json` 或给出文件路径做离线汇总；工具不操作游戏，不做目标策略，未确认完整的窗口不进入速率计算。长时研究须定期自行复制数据。

## 运行时预算

bot 主循环以 `@tick.budget_ms 200` 运行（默认 100ms）：GUI 宿主的调度/桥抖动实测可让单次回调达到 110–170ms，按默认预算会以 `tick_overrun` 中止长跑会话。放宽到 200ms 继续保留 `overrun abort`，异常卡死仍会中止，只吸收宿主抖动；`script status` 的 `tick.overruns/max_us` 仍用于观察真实耗时。若需要更严格的实时性，可在复制脚本上覆盖 `@tick` 前导注释。

## 离线测试

从仓库根目录运行：

```bash
bash bot/test/run.sh
```

脚本使用仓库固定的 Lua 子模块编译 Lua，并执行接口、默认值、剩余桩返回值、入口与测试辅助脚本语法检查；`test_io.lua` 使用假文件系统检查队列回执、状态 JSON、状态机、世界投影和事件轮转，同时校验合成和真实捕获地图几何 fixture。成功时包含以下输出：

```text
bot io/state/world tests ok
terrain ok: synthetic locations=8; map=102000000 platforms=125 candidates=1553 character=(2452,1935) platform=125 path=125->1 edges=4 kinds=jumpup,jumpup,step,jumpup
bot smoke ok: 9 modules
```

## 测试辅助脚本

`bot/test/capture_terrain.lua` 只读取当前 GUI 场景的 `context.scene.terrain.navigation`；需在地图 `102000000` 执行，运行前由角色准备步骤创建 `/work/bot/fixtures/` 目录，脚本生成 `/work/bot/fixtures/map_102000000.lua`，供审阅后复制为仓库夹具。夹具只保留地图代次和静态导航几何。

`bot/test/owner_drive.lua` 是 owner 移动试验脚本：向右 2 秒、向左 2 秒、原地跳一下，再循环；不攻击、不拾取、不使用物品。将其复制到 owner 角色的 `/work/scripts` 后，以 CLI 的会话期限运行，例如 `script run owner_drive.lua --seconds 10`。`--seconds` 由 CLI 控制，当前全局默认 30 秒；脚本文件不能单独覆盖该默认值。

这些测试辅助脚本不会自行启动机器人；行为以各模块及实际场景验证为准。

## 手工同步

将包内容复制到角色脚本目录；该命令可用于首次同步和更新已有目录，不会额外嵌套一层 `bot/`：

```bash
cp -r bot/. <角色>/scripts/bot/
```
