# 共享 Lua 脚本

这里保存随客户端镜像固定的 Lua 资产，供 headless 与 GUI 客户端使用：`examples/` 是 tick 示例，`tick/travel/` 是通用跨图旅行策略包。客户端只有一套 tick 引擎，两者统一按 tick 执行、无需声明引擎，只在前导注释按需声明 `@tick.*`。旧的内置策略及其函数库已移除。示例用途见下表，旅行包见[跨图旅行策略包](#跨图旅行策略包ticktravel)；公共接口以 [Tick Lua API](../../docs/LUA_TICK_API.md) 为准。

示例与旅行包都不由内置策略自动加载，阅读或试用时按用途显式选择。示例会实际移动、跳跃、消耗 MP 或普攻；旅行包会真实寻路、跳跃并可能用药。运行前确认角色、场景和唯一操作者，并按实际游戏结果核对。

## 示例：`examples/`

| 文件 | 演示内容 | 使用边界 |
| --- | --- | --- |
| [tick-held-skill.lua](examples/tick-held-skill.lua) | 只设置一次技能持续意图，到明确的演示期限后撤下并结束，由 Runtime 确认停止所属持续输入。 | 会消耗 MP；传入角色已学会且本端支持的技能，保持时长不用于猜动画结束。 |
| [tick-jump-attack.lua](examples/tick-jump-attack.lua) | 保持方向助跑再起跳，空中普攻并撤下保持，落地后停止。 | 会实际移动、跳跃和普攻；需本端已知地面和动作忙闲事实，不寻路、不选怪、不保证命中或精确出手次数。 |

### tick 持续输入：技能保持与撤下

`tick-held-skill.lua` 演示 `player.skill(id)` 只调用一次，后续回调不重放。客户端按本端原生动作完成和准入处理当前仍有效的意图；`player.skill(nil)` 撤下整个动作槽，不清方向或强行中断已发生动画。撤下后直接返回 `"done"`，由 Runtime 确认停止所属持续输入（持键路径包含真实释放）后发布会话完成；脚本不轮询内部握手。按 ID 技能没有实体技能键，撤下移除持续意图及未执行派发，不发送技能 key-up。显式 `hold_seconds` 是调用者选择的保持期限，不是动画时间。无动作锁技能每次保持只派发一次；GUI 蓄力类别不支持。用药与技能不同，持续用药会重复尝试消耗，目标达到必须撤下；详见 [持续输入合同](../../docs/LUA_TICK_API.md#角色状态机与动作槽)。

```bash
private/workbenches/workbench "$DIR" script run \
  /opt/beidou-pilot/shared/scripts/examples/tick-held-skill.lua \
  --skill-id 你的已学会技能ID --hold-seconds 1 --seconds 3
```

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

`--direction` 来自头部 `@option`，默认 `right`，也可为 `left`。`--seconds` 是整个原生会话的期限，不是跳跃时长；例如起跳失败时由这个期限停止等待并释放输入。本例省略 `@tick.gear` 时使用第 3 档（30Hz）；复制到用户脚本后，可在前导注释中显式设置，例如 `-- @tick.gear 4` 选择原生更新；1、2、3 档分别为 10Hz、20Hz 和 30Hz。低档只降低判断频率，不改变角色物理和每宿主更新的取消/放键；落地后在下一次到期判断清方向。

阅读时关注四点：入口默认按第 3 档（30Hz）执行、无需声明引擎；`main` 只做短判断，返回 nil 后下次继续；`context.state.phase` 保存“助跑 → 空中 → 攻击输入消费 → 撤下保持 → 落地停止”阶段；方向和动作都只需设置一次，当前原生 `action="attack"` 且 `dispatched=true` 后用 `player.skill(nil)` 撤下，已经发生的动画继续，落地后用 `move(nil)` 清方向，速度接近零再返回 done。

`character.velocity` 是角色自己的当前运动向量，`character.movement` 是按当前有效属性及本端物理模型推断的静止平地参考能力，两者不混用。自己、其他玩家、怪物、NPC、投射物和掉落物共享可移动物体的观察基类，每个实体各自拥有向量，世界不是运动主体。向量保留原生或原生更新区间差分的来源，未知不填零。沿目标方向达到参考移速的 99% 后才提交 jump：无头速度渐近稳态，不能严格比较相等，也不用固定助跑时长/距离或仅凭速度平台。完整运动参考及最大跳高的适用条件见 [运动观察](../../docs/LUA_TICK_API.md#运动观察与静止参考)。

空中阶段要求真实 `character.on_ground=false`、Y 小于原平地 Y 且 `character.action_idle=true`；输入保持与角色动作分开，不用“槽空”猜落地。地面/动作事实未知时不以重复坐标推断。速度/能力参考只阻断助跑或停止确认，不阻断已具备离地事实的攻击。当前原生普攻与派发事实确认后撤下保持，不能把上次跳跃的 `dispatched` 或仍在空中当作普攻已派发。槽空也不表示所属输入已停止；最终返回 done 后由 Runtime 确认停止所属持续输入（持键路径包含真实释放）。低频可能错过原生重复边界，所以本例不承诺精确一次出手。`settled` 包含停止移动，不能用于全程移动的落地判断；派发、释放或动画结束也不等于命中。

可以从这个结构扩展更多阶段，不要加入阻塞等待或 `game.sleep()` 等旧接口。tick 多会话共享 player，同客户端其他会话可能覆盖方向；初学试用只运行这一份动作示例。完整契约见 [tick API](../../docs/LUA_TICK_API.md#tick-环境)。

## 跨图旅行策略包：`tick/travel/`

`tick/travel/` 是随镜像固定的目录脚本包，用于「声明目的地后跨图移动」的参考实现。由 CLI `travel` 查询跨图路线并注入 `context.route/context.goal` 后运行；普通 `script run/start` 不注入路线与目标，脚本会以 `route_unavailable` 明确失败，不伪造路线。

| 文件 | 职责 |
| --- | --- |
| [main.lua](tick/travel/main.lua) | 入口与 `@option`；每 tick 顺序 `safety → combat → locomotion → travel_core`，终止时 `player.stop()` |
| [terrain.lua](tick/travel/terrain.lua) | 消费 `context.scene.terrain.navigation` 的候选关系，按角色有效跳高过滤生成可执行边与代价，按场景代次缓存并做最短路 |
| [locomotion.lua](tick/travel/locomotion.lua) | `walk/step/jumpup/drop/rope` 逐边相位机、同平台 `walk_to`、门户 `enter_portal`、失败上报与运行期禁边 |
| [safety.lua](tick/travel/safety.lua) | 每 tick 最先：低血用药、达到目标撤下用药意图、死亡/无药/低于 HP 下限时终止 |
| [combat.lua](tick/travel/combat.lua) | 战斗层骨架：当前未启用，只记录请求，不产生攻击/技能输入 |
| [travel_core.lua](tick/travel/travel_core.lua) | 任务相位：boot → leg/门户 → final → arrived，含重规划、失败原因与日志 |

```bash
DIR=/你的工作台目录
PACKAGE=/opt/beidou-pilot/shared/scripts/tick/travel

private/workbenches/workbench "$DIR" script describe "$PACKAGE"
private/workbenches/workbench "$DIR" travel "$PACKAGE" \
  --target-map 102020100 --target-x 225 --target-y 1755 --seconds 180
```

- 路线由 CLI 用只读 `world-map route` 查询后注入；Lua 不解析门户模型、不做跨图搜索、不在运行中改道。注入形状与失败集合见 [Tick Lua API](../../docs/LUA_TICK_API.md#跨图旅行脚本包travel)，CLI 参数与输出见 [CLI](../../docs/CLI.md#跨图旅行travel)。
- 脚本参数按 `@option` 声明：`budget_seconds`（默认 120）、`arrive_tolerance`（12）、`min_hp_ratio`（0.25）、`heal_hp_ratio`（0.7）、`hp_item_id`（2000002）、`block_policy`（auto）、`clear_limit`（8）、`max_replans`（8），可用 `--budget-seconds` 等覆盖；`script describe` 显示有效默认值。`block_policy`/`clear_limit` 当前只解析默认值，不参与决策。
- 阶段边界：当前只实现「起点图 == 目标图（腿序列为空）→ 目标图内走到目标坐标 → 完成」；leg/门户/换图相位是 M3 骨架，尚未做真实客户端验证。挡路怪战斗与 M4 恢复策略未实现，`combat` 不产生战斗输入。
- 结果以 CLI 输出的 `route` 与事后 `arrival` 核对；脚本内部失败以 `error("travel_failed ...")` 结束会话。
- 会实际移动、跳跃并可能用药（用药受本端支持的药品范围限制）。先在安全城镇单图验证，确认角色、场景与唯一操作者，不要在其他脚本控制角色时运行。

## 调用与维护

示例与旅行包入口都声明 `main(context)` 与 `@option`；`script describe FILE|DIR` 可查看参数，`script run FILE` / `travel DIR` 可按同一声明传值。内置资产随镜像位于 `/opt/beidou-pilot/shared/scripts/`，可以通过通用入口直接查看和调用，例如：

```bash
beidou-pilot script describe /opt/beidou-pilot/shared/scripts/examples/tick-held-skill.lua
beidou-pilot script run /opt/beidou-pilot/shared/scripts/examples/tick-jump-attack.lua \
  --direction right --seconds 5
```

自定义脚本放工作台的 `scripts/`，在容器内对应 `/work/scripts/`，通过统一宿主入口提交：

```bash
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --seconds 20
```

内置示例与旅行包随镜像版本固定，已有容器保持启动时的版本。执行中断或等待失败只结束等待；先用 `script status` 查看已有会话，需要取消时明确执行 `script cancel --session SCRIPT_ID`，并核对终态及放键。

编写脚本查 [Tick Lua API](../../docs/LUA_TICK_API.md)，旅行用法查 [CLI](../../docs/CLI.md#跨图旅行travel)，装载、控制权和取消规则查 [控制协议](../../docs/CONTROL.md)，维护本目录前阅读 [AGENTS.md](AGENTS.md)。脚本返回、动作派发、CLI 成功输出和离线测试属于过程证据，实际到达、消耗、恢复与战斗效果另行确认。
