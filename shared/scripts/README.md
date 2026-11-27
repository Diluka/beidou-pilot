# 共享 Lua 脚本

这里保存随客户端镜像固定的 tick 脚本示例，供 GUI 客户端使用。客户端只有一套 tick 引擎，示例统一按 tick 执行、无需声明引擎，只在前导注释按需声明 `@tick.*`。旧的内置策略及其函数库已移除。各示例用途见下表，公共接口以 [Tick Lua API](../../docs/LUA_TICK_API.md) 为准。

示例不由内置策略自动加载，阅读或试用时按用途显式选择。示例会实际移动、跳跃、消耗 MP 或普攻，运行前确认角色、场景和操作者，并按实际游戏结果核对。

## 示例：`examples/`

| 文件 | 演示内容 | 使用边界 |
| --- | --- | --- |
| [tick-held-skill.lua](examples/tick-held-skill.lua) | 只设置一次技能持续意图，到明确的演示期限后撤下并结束，由 Runtime 确认停止所属持续输入。 | 会消耗 MP；传入角色已学会且本端支持的技能，保持时长不用于猜动画结束。 |
| [tick-jump-attack.lua](examples/tick-jump-attack.lua) | 保持方向助跑再起跳，空中普攻并撤下保持，落地后停止。 | 会实际移动、跳跃和普攻；需本端已知地面和动作忙闲事实，不寻路、不选怪、不保证命中或精确出手次数。 |

### tick 持续输入：技能保持与撤下

`tick-held-skill.lua` 演示 `player.skill(id)` 只调用一次，后续回调不重放。客户端按本端原生动作完成和准入处理当前仍有效的意图；`player.skill(nil)` 撤下整个动作槽，不清方向或强行中断已发生动画。撤下后直接返回 `"done"`，由 Runtime 确认停止所属持续输入（持键路径包含真实释放）后发布会话完成；脚本不轮询内部握手。按 ID 技能没有实体技能键，撤下移除持续意图及未执行派发，不发送技能 key-up。显式 `hold_seconds` 是调用者选择的保持期限，不是动画时间。无动作锁技能每次保持只派发一次；GUI 蓄力类别不支持。用药与技能不同，持续用药会重复尝试消耗，目标达到必须撤下；详见 [持续输入合同](../../docs/LUA_TICK_API.md#角色状态机与动作槽)。

```bash
workbenches/workbench dev/NAME script run \
  /opt/beidou-pilot/shared/scripts/examples/tick-held-skill.lua \
  --skill-id 你的已学会技能ID --hold-seconds 1 --seconds 3
```

### tick 动作入门：连续移动跳砍

先读 [tick-jump-attack.lua](examples/tick-jump-attack.lua)，再从已登录的工作台显式运行。装备可普攻的武器，选择有足够空间的安全同高平地，确认没有其他脚本控制角色；本例不处理斜坡、台阶、绳梯、落层、怪物或传送门。已有容器须使用包含此示例及对应 tick 行为的镜像；内置文件不会随宿主源码编辑自动更新。

```bash
ROLE=dev/NAME   # 换为本次授权的开发角色
SCRIPT=/opt/beidou-pilot/shared/scripts/examples/tick-jump-attack.lua

workbenches/workbench "$ROLE" script describe "$SCRIPT"
workbenches/workbench "$ROLE" script run "$SCRIPT" --direction right --seconds 5
workbenches/workbench "$ROLE" snapshot

# 异步受理后返回；保留返回的 script_id，再按该 ID 查询或明确取消。
workbenches/workbench "$ROLE" script start "$SCRIPT" --direction left --seconds 5
workbenches/workbench "$ROLE" script status --session SCRIPT_ID
workbenches/workbench "$ROLE" script cancel --session SCRIPT_ID
```

`--direction` 来自头部 `@option`，默认 `right`，也可为 `left`。`--seconds` 是整个原生会话的期限，不是跳跃时长；例如起跳失败时由这个期限停止等待并释放输入。本例省略 `@tick.gear` 时使用第 3 档（30Hz）；复制到用户脚本后，可在前导注释中显式设置，例如 `-- @tick.gear 4` 选择原生更新；1、2、3 档分别为 10Hz、20Hz 和 30Hz。低档只降低判断频率，不改变角色物理和每宿主更新的取消/放键；落地后在下一次到期判断清方向。

阅读时关注四点：入口默认按第 3 档（30Hz）执行、无需声明引擎；`main` 只做短判断，返回 nil 后下次继续；`context.state.phase` 保存“助跑 → 空中 → 攻击输入消费 → 撤下保持 → 落地停止”阶段；方向和动作都只需设置一次，当前原生 `action="attack"` 且 `dispatched=true` 后用 `player.skill(nil)` 撤下，已经发生的动画继续，落地后用 `move(nil)` 清方向，速度接近零再返回 done。

`character.velocity` 是角色自己的当前运动向量，`character.movement` 是按当前有效属性及本端物理模型推断的静止平地参考能力，两者不混用。自己、其他玩家、怪物、NPC、投射物和掉落物共享可移动物体的观察基类，每个实体各自拥有向量，世界不是运动主体。向量保留原生或原生更新区间差分的来源，未知不填零。沿目标方向达到参考移速的 99% 后才提交 jump：速度渐近稳态，不能严格比较相等，也不用固定助跑时长/距离或仅凭速度平台。完整运动参考及最大跳高的适用条件见 [运动观察](../../docs/LUA_TICK_API.md#运动观察与静止参考)。

空中阶段要求真实 `character.on_ground=false`、Y 小于原平地 Y 且 `character.action_idle=true`；输入保持与角色动作分开，不用“槽空”猜落地。地面/动作事实未知时不以重复坐标推断。速度/能力参考只阻断助跑或停止确认，不阻断已具备离地事实的攻击。当前原生普攻与派发事实确认后撤下保持，不能把上次跳跃的 `dispatched` 或仍在空中当作普攻已派发。槽空也不表示所属输入已停止；最终返回 done 后由 Runtime 确认停止所属持续输入（持键路径包含真实释放）。低频可能错过原生重复边界，所以本例不承诺精确一次出手。`settled` 包含停止移动，不能用于全程移动的落地判断；派发、释放或动画结束也不等于命中。

可以从这个结构扩展更多阶段，不要加入阻塞等待或 `game.sleep()` 等旧接口。tick 多会话共享 player，同客户端其他会话可能覆盖方向；初学试用只运行这一份动作示例。完整契约见 [tick API](../../docs/LUA_TICK_API.md#tick-环境)。

## 校准探针：`calibration/`

| 文件 | 用途 | 使用边界 |
| --- | --- | --- |
| [tick-motion-calibration.lua](calibration/tick-motion-calibration.lua) | 有界采样本地角色物理末态：行走、制动、反向、静止跳、方向跳、空中松向或空中反向各一次，每个宿主帧输出一行结构化 JSON 供离线比较。 | 只做一次移动/跳跃输入，不攻击、不用药、不换图，也不改动运动规则或导航阈值；只在安全平地、无怪且仅本脚本控制角色时使用。采样缺失/更新号跳变由比较器判证据不足，不插值补造。 |

示例演示公共 API 用法；校准探针是观察工具：固定 `@tick.gear 4`、按 `--seconds` 和脚本自身 `timeout_ms` 限时，把同一份 `character.physics` 契约记录到脚本事件日志，再由 `tools/motion_compare.py` 离线按物理 `update_id` 去重与对齐。运行和比较方法见 [tick API 的运动校准章节](../../docs/LUA_TICK_API.md#运动校准脚本与离线比较器)。

### 运动校准采样

`calibration/tick-motion-calibration.lua` 用于建立 GUI 物理pose基线，不参与玩法控制。先确认角色站在安全平地、本图没有可见怪物且没有其他脚本控制角色，再在两个 GUI 实例或版本上各运行一次同场景同方向的会话：

```bash
SCRIPT=/opt/beidou-pilot/shared/scripts/calibration/tick-motion-calibration.lua
workbenches/workbench dev/NAME script run "$SCRIPT" --scenario walk --direction right --seconds 10
```

场景可选 `walk/brake/reverse/jump_stationary/jump_directional/air_release/air_reverse`，方向为 `left/right`；`runup_ms/hold_ms/air_release_ms/timeout_ms` 控制各阶段时长。每个宿主帧通过 `game.log` 输出一行前缀 `BEIDOU_MOTION_CAL v1 ` 的 JSON，写入该实例桥目录的 `script-events.jsonl`；把两份文件复制到同一开发环境后运行离线比较器：

```bash
python3 tools/motion_compare.py --left gui-events.jsonl --right other-events.jsonl
```

比较器按真实 `physics.update_id` 去重（重复宿主帧校验位姿一致）、以意图变化后的第一份物理样本为消费边沿对齐，逐物理步比较相对轨迹、速度和离地/落地事件；`step_ms` 不同、更新号缺口、字段缺失或记录跨场景时返回证据不足并要求重采，不通过平移或放宽容差掩盖。当前 GUI `step_ms=30`；步长不同、更新号缺口或字段缺失的样本按证据不足拒绝，不混算。

## 调用与维护

示例文件声明 `main(context)` 与 `@option`；`script describe FILE` 可查看参数，`script run FILE` 可按同一声明传值。内置示例随镜像位于 `/opt/beidou-pilot/shared/scripts/examples/`，可以通过通用入口直接查看和调用，例如：

```bash
beidou-pilot script describe /opt/beidou-pilot/shared/scripts/examples/tick-held-skill.lua
beidou-pilot script run /opt/beidou-pilot/shared/scripts/examples/tick-jump-attack.lua \
  --direction right --seconds 5
```

自定义脚本放在所选角色的 `scripts/`。`script describe/run/start` 从容器 `/work/scripts` 解析相对路径，也接受显式容器绝对路径：

```bash
workbenches/workbench dev/NAME script run control.lua --seconds 20
```

内置示例随镜像版本固定，已有容器保持启动时的版本。执行中断或等待失败只结束等待；先用 `script status` 查看已有会话，需要取消时明确执行 `script cancel --session SCRIPT_ID`，并核对终态及放键。

编写脚本查 [Tick Lua API](../../docs/LUA_TICK_API.md)，装载、控制权和取消规则查 [控制协议](../../docs/CONTROL.md)，维护本目录前阅读 [AGENTS.md](AGENTS.md)。脚本返回、动作派发和离线测试属于过程证据，实际到达、消耗、恢复与战斗效果另行确认。
