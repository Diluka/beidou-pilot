# 伴游机器人 Lua 包

该目录是可复制到角色 `/work/scripts/bot` 的 tick 脚本包。`lib.io`、`lib.state`、`lib.world` 与 `main.lua` 提供指令邮箱、状态/事件发布、基础世界投影和 tick 主流程；`lib.terrain` 提供只读地形构图、平台定位与 A* 路径规划。移动执行、跟随、战斗、自保及拾取仍由后续任务实现。机器人只读 `/work/bot` 的配置和队列文件。

`main.lua` 按 tick API 定义唯一的顶层 `local function main(context)`。tick 加载器会在内部编译并包装入口，因此不需要、也不应从用户脚本返回一个模块表。此骨架不会在顶层调用 `game` 或 `player`。

## 模块接口

| 模块 | 函数签名 |
| --- | --- |
| `lib.terrain` | `build(navigation)`、`platform_at(graph, x, y, tolerance)`、`plan(graph, from_index, to_index, options)` |
| `lib.move` | `new(graph)`、`set_path(mover, edges)`、`step(mover, ctx, world)`、`stop(mover)` |
| `lib.follow` | `update(ctx, world)` |
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

follow 返回 `wait` 时主流程停止现有 mover；目标平台或场景代次变化，或 owner 的期望位置移动达到 `stop_distance` 时重算路径，同平台内的小幅位置变化继续复用路径。

`/work/bot/state.json` 原子更新，常规间隔约 1 秒；`/work/bot/events.jsonl` 记录命令、模式和错误事件，单文件达到 1 MiB 时滚动到 `events.1.jsonl`。启动进入 `recover`；世界就绪且当前场景有可用地形图时转为 `idle`，不要求 `move.new` 已实现。mover 仅在 follow/hunt 产生实际移动或目标动作时才按场景代次尝试创建。checkpoint 当前只校验并保留，不重放上次动作或恢复旧模式/目标。

`state.json.session_id` 取自只读 `context.tick.script_id`，即当前 Runtime tick 会话 ID。

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
