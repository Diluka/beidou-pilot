# Bot Lua 包骨架

该目录是可复制到角色 `/work/scripts/bot` 的 tick 脚本包。当前只提供包结构、默认值、接口桩和离线 smoke test；所有 `lib` 实现均返回 `not_implemented`，不包含跟随、移动、战斗、喝药或拾取行为。

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

尚未实现的方法按签名返回 `nil, "not_implemented"`、`false, "not_implemented"` 或 `"failed", "not_implemented"`。具体返回契约由 `bot/test/run.lua` 检查。

## 默认值

`owner` 默认为空；跟随距离 `80`、停止距离 `40`、HP/MP 药水阈值 `60`/`30`、拾取半径 `150`。攻击技能和 HP/MP 药品 ID 占位均为 `0`。这些值只定义配置，不会驱动任何游戏行为。

## 离线测试

从仓库根目录运行：

```bash
bash bot/test/run.sh
```

脚本使用仓库固定的 Lua 子模块编译 Lua，并执行接口、默认值、桩返回值、入口语法与合成地形 fixture 检查。成功时输出：

```text
bot smoke ok: 9 modules
```

## 手工同步

将包内容复制到角色脚本目录；该命令可用于首次同步和更新已有目录，不会额外嵌套一层 `bot/`：

```bash
cp -r bot/. <角色>/scripts/bot/
```
