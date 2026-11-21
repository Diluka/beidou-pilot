# 第一期：能跟能打（伴游机器人 MVP）

- 状态：任务已拆分，按 GitHub Milestone「第一期：能跟能打（伴游机器人 MVP）」执行
- 设计依据：[伴游机器人设计与路线](COMPANION_BOT.md) 的 P0/P1
- 任务模板：[开发任务模板](../.github/ISSUE_TEMPLATE/task.md)

## 1. 本期目标

一个 headless 机器人角色，在开发服同一张地图跟随指定玩家，协助打怪、喝药、拾取，能通过文件邮箱暂停/恢复/查状态，连续运行 30 分钟不死亡、不长时间卡住。

**成功判据**：

- 30 分钟同图跟随/打怪；可行动采样中跟随距离 ≤120px 占比 ≥90%；无 >10s 卡住；无死亡。
- `follow/hunt/stay/status/stop` 文件指令 2 秒内生效；`state.json` 每秒更新；`events.jsonl` 有模式/指令/死亡/卡住事件。
- 取消脚本后角色停止输入；重启进入 `recover`，确认安全后恢复计划。
- 离线 Lua 测试覆盖平台图/A*、跟随目标、指令解析、卡住恢复。

## 2. 范围与非范围

**范围**：`bot/` 目录脚本包、平台图/A*、移动执行、跟随、战斗、自保、拾取、文件指令、状态/事件、30 分钟 headless 验收、运行入口与 README。

**非范围**：

- 原生聊天/私聊、队伍/组队、组队任务、BOSS、LLM、跨图、GUI 机器人。
- GUI/headless 行为差异核对（独立审计任务）。
- 服务端修改、正式环境数据写入。

## 3. 后端分工

> 后端选择、差异审计、GUI 兼容选型是全局约定，只在本文和设计文档维护；任务正文不重复这些共识，只写本任务特有的目标和边界。

- 机器人固定 headless。开发任务只实现和验收 headless；任务正文锁定预期行为。
- GUI 行为是权威参考；差异由独立的“后端差异审计”任务在专门会话中核对，产出差异报告或临时补充任务。差异不阻塞功能任务，也不延长当前交付。
- 如果某个 headless 行为还没有可靠依据，先派发前置调查/取证任务，把预期行为写成可复核契约；功能任务只消费已锁定的证据。
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

关键路径：`P1-01 → P1-03 → P1-04 → P1-05 → P1-06 → P1-07/P1-08/P1-10 → P1-12 → P1-13`。

## 5. 任务表

| ID | 任务 | 依赖 |
| --- | --- | --- |
| P1-01 | 包骨架、接口桩与离线测试入口 | 无 |
| P1-01a | 对齐骨架的地形 fixture 与配置契约 | 无 |
| P1-02 | 开发角色、地图 fixture 与双角色基线 | 无 |
| P1-03 | 地形平台图与坐标定位 | P1-01、P1-02 |
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

### 6.2 世界模型

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

### 6.3 模块签名

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

主流程负责创建唯一 `mover = move.new(graph)`，用 `terrain.platform_at` 填充 `character/owner/mobs/drops.platform`，并把 `mover` 传给 `combat.step`/`loot.step`；模块不各自创建 mover。

### 6.4 文件与命令

```text
/work/bot/queue/<seq>-<id>.cmd     key=value
  id=...
  kind=follow|hunt|stay|status|stop
  target=可选
  ttl=秒，0=持续到被替换
  source=host|cli
/work/bot/queue/done/<id>          ok 或 rejected=<reason>
/work/bot/state.json              1s 原子写
/work/bot/events.jsonl            追加，按大小轮转
/work/bot/config.conf             owner、技能/药品、阈值、安全点
/work/bot/checkpoint.conf         模式/目标
```

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

### 6.5 模式

| 模式 | 行为 | 退出 |
| --- | --- | --- |
| `recover` | 观察、确认身份/位置、等安全 | 安全后按计划/指令 |
| `idle` | 停手等待 | 收到指令 |
| `follow` | 跟随 owner，保持 40～120px | `stay`/`hunt`/危险 |
| `hunt` | 在当前狩猎点打怪/拾取 | `follow`/`stay`/升级阈值 |
| `dead` | 复活一次、等待 | HP>0 |

## 7. 测试与验收

- 离线：`bash bot/test/run.sh`，纯 Lua fixture，不启动客户端。
- 真实 headless：开发服 `dev` 两个角色；只验证 headless 预期行为，不打开 GUI 对比。
- 证据：`state.json`/`events.jsonl`/命令输出/关键时间点；原始证据留角色目录，公开记录只写结论。
- 差异：如果怀疑 headless 与 GUI 不一致，另开“后端差异审计”任务；不在本期功能任务内处理。

## 8. 未纳入本期

- 私聊指令、队伍、组队任务、BOSS、LLM、跨图、GUI 机器人。
- GUI 兼容开发；如需要，先做钩子/协议调查任务，再按 hook 优先排任务。
- 经典组队任务默认 3 人起，玩家 + 1 机器人进不去；后续需要第二个机器人补位或开发服降门槛。
