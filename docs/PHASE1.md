# 第一期：能跟能打（伴游机器人 MVP）

- 状态：历史拆分。原 headless 后端已退役；机器人邮箱已迁移到 GUI，任务表与验收前提需维护者重新确认后再执行。
- 设计依据：[伴游机器人设计与路线](COMPANION_BOT.md) 的 P0/P1
- 任务模板：[开发任务模板](../.github/ISSUE_TEMPLATE/task.md)

## 1. 本期目标

一个 GUI 机器人角色，在开发服同一张地图跟随指定玩家，协助打怪、喝药、拾取，能通过文件邮箱暂停/恢复/查状态，连续运行 30 分钟不死亡、不长时间卡住。

**成功判据**：

- 30 分钟同图跟随/打怪；可行动采样中跟随距离 ≤120px 占比 ≥90%；无 >10s 卡住；无死亡。
- `follow/hunt/stay/status/stop` 文件指令 2 秒内生效；`state.json` 每秒更新；`events.jsonl` 有模式/指令/死亡/卡住事件。
- 取消脚本后角色停止输入；重启进入 `recover`，确认安全后恢复计划。
- 离线 Lua 测试覆盖平台图/A*、跟随目标、指令解析、卡住恢复。

## 2. 范围与非范围

**范围**：`bot/` 目录脚本包、平台图/A*、移动执行、跟随、战斗、自保、拾取、文件指令、状态/事件、30 分钟 GUI 验收、运行入口与 README。

**非范围**：

- 原生聊天/私聊、队伍/组队、组队任务、BOSS、LLM、跨图。
- 机器人邮箱/运行后端迁移（已由独立前置工作处理）。
- 服务端修改、正式环境数据写入。

## 3. 后端分工

> 后端选择、差异审计、GUI 兼容选型是全局约定，只在本文和设计文档维护；任务正文不重复这些共识，只写本任务特有的目标和边界。

- 后端只有原版 GUI。开发任务只在这一个后端实现和验收；任务正文锁定预期行为。
- bot 主包使用纯 Lua 固定槽位文件邮箱，在 GUI/Wine 运行。
- GUI 原生行为是权威依据；不再维护第二后端差异审计。
- 如果某项行为还没有可靠依据，先派发前置调查/取证任务，把预期行为写成可复核契约；功能任务只消费已锁定的证据。
- GUI 兼容优先通过客户端钩子/桥的直接指令实现；模拟键鼠只在有证据表明钩子不可用时使用。选型由维护者决定；证据不足先派调查任务。

## 4. 实施顺序

```text
第 0 步（先行）：P1-01a 对齐骨架的地形 fixture 与配置契约
第 1 步（可并行）：P1-01 包骨架/测试入口；P1-02 开发角色与地图 fixture
第 2 步：P1-03 平台图 → P1-04 A* → P1-05 走/小步 → P1-06 跳/落/绳
       同时推进：P1-11 指令/状态/主流程
第 3 步（P1-06 + P1-11 完成后并行）：P1-07 跟随；P1-08 战斗；P1-10 拾取；P1-09 自保
第 4 步：P1-12 30 分钟集成验收
第 5 步：P1-13 botctl/README 与交接
```

关键路径：`P1-01a → P1-02/P1-01 → P1-03 → P1-04 → P1-05 → P1-06 → P1-07/P1-08/P1-10 → P1-12 → P1-13`。

## 5. 任务表

| ID | 任务 | 依赖 |
| --- | --- | --- |
| P1-01 | 包骨架、接口桩与离线测试入口 | 无 |
| P1-01a | 对齐骨架的地形 fixture 与配置契约 | 无 |
| P1-02 | 开发角色、地图 fixture 与双角色基线 | P1-01a |
| P1-03 | 地形平台图与坐标定位 | P1-01、P1-02、P1-01a |
| P1-04 | 平台图 A* 路径规划 | P1-03 |
| P1-05 | 移动执行：走/小步 | P1-04、P1-02 |
| P1-06 | 移动执行：跳上/落下/绳 | P1-05 |
| P1-07 | 同图跟随玩家 | P1-06、P1-11 |
| P1-08 | 战斗目标选择与攻击 | P1-06、P1-11 |
| P1-09 | 喝药、死亡与复活自保 | P1-01、P1-02、P1-11 |
| P1-10 | 安全拾取 | P1-06、P1-11 |
| P1-11 | 指令邮箱、状态事件与主流程 | P1-01、P1-02 |
| P1-12 | 30 分钟集成验收与证据 | P1-07、P1-08、P1-09、P1-10、P1-11、P1-02 |
| P1-13 | 运行入口、README 与交接 | P1-12 |

依赖以 GitHub issue 原生 `blocked by` 为准；本表只用于阅读。

## 6. 共享接口与文件契约

本期所有任务共用以下契约；任务正文必须锁定自己那部分，执行者不得自行改名/改参数/改常量。

### 6.1 目录

```text
bot/
  main.lua
  defaults.lua
  lib/
    terrain.lua
    move.lua
    follow.lua
    combat.lua
    sustain.lua
    loot.lua
    io.lua
    state.lua
    world.lua
  test/
    run.sh
    run.lua
    fixtures/
  README.md
```

### 6.2 Fixture schema

真实地图夹具 `bot/test/fixtures/map_<id>.lua` 由 `bot/test/capture_terrain.lua` 从当前场景采集，返回 `map_id`、`scene_generation` 与嵌套 `navigation`；`synthetic.lua` 只作为最小 schema 夹具，必须使用同一 `navigation` 结构。

| 字段 | 契约 |
| --- | --- |
| `map_id` | 数字地图 ID。 |
| `scene_generation` | 采集时静态场景代次，正整数；只标识采样，不是地图版本。 |
| `navigation.model` | 仅含数值常量 `stand_height`、`wall_margin`、`min_platform_width`、`jump_rise`、`drop_min`、`drop_max`、`rope_grab`。 |
| `navigation.terrain_left` / `terrain_right` | 地形左右边界。 |
| `navigation.platforms` | 平台数组；每项仅含 `index`、`left`、`right`、`open_left`、`open_right`、`segments`。范围为 `left/right`，`segments` 每 4 个数字为 `left,right,y1,y2`，平台高度沿线段线性插值。 |
| `navigation.walls` | 扁平数组，每 3 个数字为 `x,top,bottom`。 |
| `navigation.ropes` | 绳梯数组；每项仅含 `index`、`x`、`y1`、`y2`、`platforms`。`platforms` 每 2 个数字为相交平台的 `platform_index,y`。 |
| `navigation.candidates` | 必含 `walk`、`step`、`jumpup`、`drop`、`rope` 五个键；前四类每 5 个数字为 `from,to,x,destination,rise`，`rope` 每 6 个数字追加 `rope_index`。候选数组可以为空；`destination` 是目标平台落点 x 坐标。 |
| `rise` | `walk/step` 取源/目标平台相邻边缘高度之差（源减目标）；`jumpup` 取候选 `x/destination` 高度之差（源减目标）；`drop` 取目标落点减源开放边缘高度（向下为正）；`rope` 取目标减源高度（沿绳向上为负）。`walk/step` 的候选起终点会向平台内部偏移，因此斜平台上的 `rise` 不一定等于候选 `x/destination` 两点的高度差。 |

平台及绳梯索引从 1 开始，candidate 的 `from/to` 指向平台索引。不得用 `x1/x2` 平台表、结构化 `walls/candidates` 或 `model.name/platforms` 替代上述契约。

### 6.3 Config keys

`bot/defaults.lua` 只提供下列键和值；它们是配置占位，不直接触发游戏行为：

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

### 6.4 世界模型

```lua
world = {
  ready = true,
  map_id = 102000000,
  scene_generation = 3,
  now = 12.345,
  character = {x=0, y=0, hp=100, max_hp=100, mp=50, max_mp=50,
               level=10, job=100, action_idle=true, on_ground=true, platform=3},
  owner = {present=true, name="Owner", character_id=123,
           x=0, y=0, distance=50, platform=3},  -- 不同图时 present=false
  mobs = {{object_id=1, template_id=100100, x=0, y=0, platform=3,
           hp_percent=80, active=true}},
  drops = {{object_id=2, item_id=4001007, x=0, y=0, platform=3, landed=true}},
  inventory = {{item_id=2000000, quantity=10}},
}
```

### 6.5 模块签名

```lua
-- terrain
function M.build(navigation) -> graph | nil, reason
function M.platform_at(graph, x, y, tolerance) -> platform_index | nil
function M.plan(graph, from_index, to_index, options) -> edges | nil, reason
-- edge = {kind="walk"|"step"|"jumpup"|"drop"|"rope", from=, to=,
--         x=, destination=, rise=, rope_index=}

-- move
function M.new(graph) -> mover
function M.set_path(mover, edges) -> true | false, reason
function M.step(mover, ctx, world) -> "running"|"done"|"failed", reason
function M.stop(mover)

-- follow
function M.update(ctx, world) -> action
-- action = {kind="move", x=, y=, stop_distance=} | {kind="wait", reason=}

-- combat
function M.select(world, options) -> mob | nil
function M.step(ctx, world, mob, mover) -> "running"|"done"|"failed", reason

-- sustain
function M.step(ctx, world) -> handled, reason

-- loot
function M.select(world, options) -> drop | nil
function M.step(ctx, world, drop, mover) -> "running"|"done"|"failed", reason

-- io
function M.poll(ctx, now) -> commands
function M.publish(ctx, world, now)
function M.event(ctx, kind, data)

-- state
function M.new() -> state
function M.apply(state, command) -> ok, reason
function M.transition(state, mode, reason)

-- world
function M.observe(ctx) -> world

-- main
local function main(context) ... end
```

主流程用 `terrain.platform_at` 填充 `character/owner/mobs/drops.platform`；仅在 `follow`/`hunt` 实际需要动作时尝试创建唯一 `mover = move.new(graph)`，并把可用 mover 传给 `combat.step`/`loot.step`。恢复到 `idle` 不依赖 mover。

### 6.6 文件与命令

```text
/work/bot/queue/slotN.cmd         N=1..8，key=value
  id=...
  kind=follow|hunt|stay|status|stop
  target=可选
  ttl=秒，0=不过期
  created_ms=Unix 毫秒（正 TTL 必填）
  source=host|cli
/work/bot/queue/done/<id>          ok
/work/bot/queue/rejected/<id>      rejected=<reason>
/work/bot/state.json              约 1s 更新，Windows 替换可能短暂缺失
/work/bot/events.jsonl            追加，按大小轮转
/work/bot/config.conf             owner、技能/药品、阈值、安全点
/work/bot/checkpoint.conf         模式/目标
```

发送者先写临时文件再发布到空槽；单一发送者避免槽位竞争。脚本用 rename 领取槽位。目标已存在时 Windows 的 rename 不覆盖；状态写入先尝试 rename，失败且目标存在时移除旧目标再重试，记录事件，不能保证全程原子可见。

启动从 `recover` 开始，不恢复 checkpoint 中的旧模式/目标，也不重放旧动作；世界就绪且本场景地形图可用后进入 `idle`。当前 checkpoint 仅做格式校验并保留。

`state.json` 最小字段：

```json
{
  "schema": 1,
  "ts_ms": 1760000000000,
  "session_id": "script-id",
  "version": "bot-0.1.0",
  "mode": "follow",
  "map_id": 102000000,
  "scene_generation": 3,
  "x": 0, "y": 0,
  "hp": 100, "max_hp": 100, "mp": 50, "max_mp": 50,
  "owner": {"present": true, "name": "Owner", "distance": 50},
  "target": null,
  "last_command": "follow",
  "last_error": null,
  "uptime_s": 12.5
}
```

`session_id` 为当前 Runtime tick 会话 ID，由 `context.tick.script_id` 提供；它不是持久化或重启后可复用的 ID。

### 6.7 模式

| 模式 | 行为 | 退出 |
| --- | --- | --- |
| `recover` | 观察、确认身份/位置、等安全；世界就绪且本场景有可用地形图后进入 `idle`，不依赖移动模块已实现 | 安全后按计划/指令 |
| `idle` | 停手等待 | 收到指令 |
| `follow` | 跟随 owner，保持 40～120px | `stay`/`hunt`/危险 |
| `hunt` | 在当前狩猎点打怪/拾取 | `follow`/`stay`/升级阈值 |
| `dead` | 复活一次、等待 | HP>0 |

## 7. 测试与验收

- 离线：`bash bot/test/run.sh`，纯 Lua fixture，不启动客户端。
- 实现/替换模块桩的包内任务，交付文件必须包含 `bot/test/run.lua`：只允许移除本模块的 `check_stub`、把新测试加入 `loadfile`/`dofile`；不改其他测试逻辑。
- 真实 GUI：开发服 `dev` 两个角色；在 GUI 客户端上验证预期行为，并核对入图、移动和实际游戏结果。
- 证据：`state.json`/`events.jsonl`/命令输出/关键时间点；原始证据留角色目录，公开记录只写结论。
- 多实例观察（动作/移动类任务）：用 [`tools/observer/observe_clients.py`](../tools/observer/observe_clients.py) 在同一 host 时钟下同时采样两个 GUI 实例，各作为观察端核对另一端；通过条件按具体任务写明。
- 不再进行 headless/GUI 差异审计；原双端基线只作历史记录。

## 8. 未纳入本期

- 私聊指令、队伍、组队任务、BOSS、LLM、跨图、GUI 机器人。
- GUI 兼容开发；如需要，先做钩子/协议调查任务，再按 hook 优先排任务。
- 经典组队任务默认 3 人起，玩家 + 1 机器人进不去；后续需要第二个机器人补位或开发服降门槛。
