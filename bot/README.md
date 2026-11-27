# 伴游机器人 Lua 包

该目录是可复制到角色 `/work/scripts/bot` 的 tick 脚本包。`lib.io`、`lib.state`、`lib.world` 与 `main.lua` 提供指令邮箱、状态/事件发布、基础世界投影和 tick 主流程；`lib.terrain` 提供只读地形构图、平台定位与 A* 路径规划。`lib.move`、`lib.follow`、`lib.combat`、`lib.sustain` 与 `lib.loot` 实现其各自当前覆盖的行为；具体限制以模块和离线/真实场景验收为准。机器人只读 `/work/bot` 的配置和队列文件。

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
| `hp_item` | `0` |
| `mp_item` | `0` |
| `follow_distance` | `80` |
| `stop_distance` | `40` |
| `pot_hp` | `60` |
| `pot_mp` | `30` |
| `loot_radius` | `150` |

将配置写入角色 `/work/bot/config.conf`，格式为 `key=value`，例如 `owner_name=Owner`、`owner_character_id=123`。缺失或无法解析的值使用表中默认值。

## 指令、状态与事件

把每条命令写入 `/work/bot/queue/<seq>-<id>.cmd`，每行一个 `key=value` 字段。`id/kind/ttl/source` 必填，`target` 可选；`kind` 仅支持 `follow`、`hunt`、`stay`、`status`、`stop`，`source` 为 `host` 或 `cli`。例如：

```text
id=c1
kind=status
ttl=10
source=host
```

脚本在约 0.5 秒间隔扫描队列。命令处理后移动到 `queue/done/<id>`（内容 `ok`）或 `queue/rejected/<id>`（内容 `rejected=<reason>`）；重复 ID 不会再次执行，最近 100 个 ID 会留在会话内去重。`ttl=0` 不过期；正 TTL 从命令文件修改时间起计时，过期命令写入拒绝回执。`status` 立即发布状态。

follow 返回 `wait` 时主流程停止现有 mover；目标平台或场景代次变化，或 owner 的期望位置移动达到 `stop_distance` 时重算路径，同平台内的小幅位置变化继续复用路径。自然场景中 owner 与 bot 位于不同平台且路径规划返回 `no_path` 时，跟随不能保证接近目标；dev headless 冒烟在修复后仍观察到 `follow/wait: owner_platform_unreachable`，30 分钟跟随验收尚未完成。

### 一次性场景目标与无目标等待

在普通 `kind=follow` 邮箱命令的 `target` 字段中可指定 `npc:<名称>`（也可用 NPC 模板 ID）、`portal:<名称>` 或 `point:<名称>`。NPC 从当前场景按精确名称/模板 ID 定位并锁定实体；门户与练级点坐标由角色 `/work/bot/targets.conf` 只读提供：

```text
<map_id>:point:<名称>=<x>,<y>
<map_id>:<instance_id>:<scene_generation>:portal:<名称>=<x>,<y>
```

门户坐标须从当前实例的 `inspect scene`/`inspect map <map_id>` 唯一匹配后导出；实例、地图或场景代次不符时不会复用。所有导航复用当前场景地形图的 `terrain.plan` 与 `move`；同平台仍执行末段移动。只有角色接地、位于目标平台且进入目标范围才发 `target/arrived`；门户范围使用自身边界，NPC/点目标使用 `stop_distance`。到达后不代做 NPC 对话或门户交互；目标缺失/消失、坐标或平台未知、无路及执行失败以 `target/wait` 给出原因，并停止输入、回到 idle。

`hunt` 当前地图没有可选怪物且没有可拾取物时保留 hunt 模式并发出 `hunt/wait`，原因是 `no_target`；每秒复查一次，等待期间不逐 tick 重试攻击或拾取。

`/work/bot/state.json` 原子更新，常规间隔约 1 秒；`/work/bot/events.jsonl` 记录命令、模式和错误事件，单文件达到 1 MiB 时滚动到 `events.1.jsonl`。启动进入 `recover`；世界就绪且当前场景有可用地形图时转为 `idle`，不要求 `move.new` 已实现。mover 仅在 follow/hunt 产生实际移动或目标动作时才按场景代次尝试创建。checkpoint 当前只校验并保留，不重放上次动作或恢复旧模式/目标。

`state.json.session_id` 取自只读 `context.tick.script_id`，即当前 Runtime tick 会话 ID。

## 宿主运行手册

前置条件：宿主具备 Python 3、`workbenches/workbench`，并已准备对应分区的工作台角色；`dev` 服已就绪。角色只能写成 `live/NAME` 或 `dev/NAME`。仓库根目录执行：

```bash
tools/botctl install dev/NAME
tools/botctl start dev/NAME
tools/botctl status dev/NAME
tools/botctl logs dev/NAME --lines 50
tools/botctl stop dev/NAME
```

`install` 覆盖 `scripts/bot` 中的机器人代码但保留 `state.json`、事件日志等角色状态；`start` 仅经 workbench 发布连续 tick 脚本，不启动客户端；`status` 同时显示 workbench 脚本状态和 `state.json`；`stop` 根据当前 `script.id` 发起取消，并检查脚本终止与 control_released；`logs` 默认显示最近 50 行。客户端关闭仍由 workbench 单独管理。

配置键及状态/事件字段见上方“默认值”“指令、状态与事件”。常见故障：

- “没有运行中的 bot script”：先运行 status；脚本已结束时无需 stop，也不要重复 start。
- `/work/bot` 写入失败：检查角色目录挂载权限与空间，勿用宿主绕过 workbench 写客户端状态。
- 脚本已结束或状态输出无法确认放键：按 status 检查终态；未确认 control_released 时将其视为停止未验收，不要关闭/重启客户端来掩盖现场。
- NAME 格式错误：必须提供 `dev/角色名` 或 `live/角色名`。

## 持久化状态（memory）

- 路径 `/work/bot/memory.lua`（可读 Lua 表，`schema = 1`），原子写（`.tmp` + rename），上限 64KB；
- API：`lib.memory` 的 `load/save/get/set/unset/flush/clear/reconcile/repair_meta`；命名空间约定 `bot`（模式/目标/地图等）、`supply`（补给阶段/上次商店）、`quest`（任务进度缓存）；
- 损坏文件自动改名为 `.bak` 并重置，不崩溃；`schema` 变化由 `repair_meta` 迁移；
- **客户端状态是唯一权威**：启动时与运行中定期用 `character/scene/inventory/quests` 的实时观察调用 `reconcile(store, namespace, live)`，冲突字段一律覆盖为 live 值并记录修复项；调用方应发布 `memory/repair` 事件；
- `flush` 节流 ≥1 秒；只缓存"客户端无法直接观察"的事实（巡逻进度、上次商店图、阶段），可观察事实每 tick 以 live 覆盖，禁止用旧缓存代替观察。

### 装备换装与待卖清单（equipment）

- 命名空间 `equipment`：`equipped`（客户端权威快照）、`sell_list`（待卖清单，含 `approved`）、`candidates`；
- 换装对账：客户端 `equipped` 变化时，被替换的旧装备自动加入 `sell_list`（`approved=false`，不自动卖），新增装备更新快照；
- 离线重登：`reconcile` 以客户端 `inventory/equipped` 为准——清单/候选里已不存在的物品自动移除，仍存在的保留；**清单持久化在 `/work/bot/memory.lua`，重登不丢**；
- 自动清包只处理 `approved=true` 的清单项；新获得/未确认装备永不自动卖；人工确认用 `equipment.approve(store, item_id)`。

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

这些测试辅助脚本不会自行启动机器人，也不代表地形、跟随、战斗或拾取行为已经实现。

## 手工同步

将包内容复制到角色脚本目录；该命令可用于首次同步和更新已有目录，不会额外嵌套一层 `bot/`：

```bash
cp -r bot/. <角色>/scripts/bot/
```
