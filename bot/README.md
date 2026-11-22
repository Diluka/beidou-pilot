# Bot Lua 包骨架

该目录是可复制到角色 `/work/scripts/bot` 的 tick 脚本包。当前提供包结构、默认值、离线 smoke test，以及只读地形构图、坐标定位和 A* 路径规划；跟随、移动执行、战斗、喝药或拾取仍未实现。

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

尚未实现的方法按签名返回 `nil, "not_implemented"`、`false, "not_implemented"` 或 `"failed", "not_implemented"`；terrain 的 `build`、`platform_at` 和 `plan` 已实现。terrain 的数据结构契约以 [`docs/PHASE1.md`](../docs/PHASE1.md) 为准，并由专用离线用例校验；其他接口骨架由 `bot/test/run.lua` 检查。

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

这些值只定义配置，不会驱动任何游戏行为。

## 离线测试

从仓库根目录运行：

```bash
bash bot/test/run.sh
```

脚本使用仓库固定的 Lua 子模块编译 Lua，并执行接口、默认值、桩返回值、入口与测试辅助脚本语法检查，同时校验合成和真实捕获地图几何 fixture。成功时输出：

```text
terrain ok: synthetic locations=8; map=102000000 platforms=125 candidates=1553 character=(2452,1935) platform=125 path=125->1 edges=4 kinds=jumpup,jumpup,step,jumpup
bot smoke ok: 9 modules
```

## 测试辅助脚本

`bot/test/capture_terrain.lua` 只读取当前 GUI 场景的 `context.scene.terrain.navigation`；需在地图 `102000000` 执行，运行前由角色准备步骤创建 `/work/bot/fixtures/` 目录，脚本生成 `/work/bot/fixtures/map_102000000.lua`，供审阅后复制为仓库夹具。夹具只保留地图代次和静态导航几何。

`bot/test/owner_drive.lua` 是 owner 移动试验脚本：向右 2 秒、向左 2 秒、原地跳一下，再循环；不攻击、不拾取、不使用物品。将其复制到 owner 角色的 `/work/scripts` 后，以 CLI 的会话期限运行，例如 `script run owner_drive.lua --seconds 10`。`--seconds` 由 CLI 控制，当前全局默认 30 秒；脚本文件不能单独覆盖该默认值。

这些测试辅助脚本不改变 `bot/main.lua` 的 stub 状态，也不代表跟随、战斗或拾取已经实现。

## 手工同步

将包内容复制到角色脚本目录；该命令可用于首次同步和更新已有目录，不会额外嵌套一层 `bot/`：

```bash
cp -r bot/. <角色>/scripts/bot/
```
