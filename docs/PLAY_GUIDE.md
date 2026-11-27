# AI 操作者的客户端使用指引

本页只讲操作流程：怎么确认角色、观察、执行有界脚本、停止和交接。当前能力与缺口见[客户端能力边界](CLIENT_LIMITATIONS.md)；伴游机器人是应用层，设计和阶段见[伴游机器人设计与路线](COMPANION_BOT.md)，不是已交付能力。

先按任务选择分区：常驻角色自然游玩用 `live/NAME`，开发调试、复现和匹配样本验收用 `dev/NAME`。从仓库根运行 `workbenches/workbench list` 查找角色；下文 `NAME`、`GUI_NAME` 是分区内角色目录名。宿主将客户端命令转发到该角色的容器。完整参数见 [CLI](CLI.md)，环境准备见[工作台指南](../workbenches/README.md)。

可使用仓库技能 [beidou-pilot-client](../.agents/skills/beidou-pilot-client/SKILL.md) 按当前状态选择最短路径；缺少账号、没有角色或停在首次界面时，查其[账号准备与首次登录](../.agents/skills/beidou-pilot-client/references/first-login.md)，已有角色则按记录继续。

## 先确认目标、角色和操作者

从任务和角色记录确认分区、授权范围及操作者。开发角色按当前开发任务授权，读 `STATE.md` 核对职业、等级、技能、装备、位置及记录来源；常驻角色沿 `PLAN.md` 和已确认进度接续，另有授权要求。文件存在或账号可登录本身不扩大分区授权。凭据留在私密配置，不写入参数、日志或 Issue。

开发样本需要准备时先确认 `workbenches/workbench server dev status`；需要启服才执行 `server dev up`。在此独立环境可用 `server dev cli` 提供的命令建号、建角或准备条件，再由真实客户端确认。开发和样本准备在 `dev` 进行；`live` 按已有计划和授权使用。操作所选角色前先做只读检查：

```bash
workbenches/workbench dev/NAME plan
workbenches/workbench dev/NAME status
```

`plan` 只核对目标，不构建或启动客户端和服务器。确认项目、服务、容器和镜像属于所选分区；配置缺失、身份不符或服务未就绪时在本区处理，不换到另一服。

结合本地认领、其他工作台与外部操作者、服务器在线账号/角色列表判断占用。`status` 只说明当前工作台实例，账号空闲状态以在线列表和认领记录为准。

## 用已有角色完成最小上手

准备方式见 [README](../README.md#准备)和[外部资源配置](ARCHITECTURE.md#外部资源与配置)。新实例默认使用 `main` 当时的已提交版本构建或复用镜像；开发验证在 `workbench.json.ref` 明确指定提交。已有容器后续命令继续使用启动时的 CLI 与内置 Lua，与当前主检出无关。

```bash
workbenches/workbench dev/NAME open
workbenches/workbench dev/NAME doctor
workbenches/workbench dev/NAME status
workbenches/workbench dev/NAME bridge status
workbenches/workbench dev/NAME capabilities
workbenches/workbench dev/NAME snapshot
```

两个后端都从所选角色目录读取 `account.json`（权限 `0600`）：`username/password/character_id`，以及默认各为 0 的 `world/channel`。`character_id` 指已有角色；频道索引从 0 开始，返回实际频道从 1 开始。每个角色有自己的 `default` 客户端容器，角色目录读写挂到 `/work`。启动器将本次账号和分区服务器配置保存到 `runtime/default/RUN_ID`，`CLIENT_ROOT` 指向本次运行根。入图等待由 `workbench.json.timeout` 配置。

入图需同时确认新鲜状态中的 `ready`、角色名称、频道、地图和位置，原生 `instance_id/run_id` 须属于本次运行。`status` 还提供 `source_revision/image/run_id`，用它说明正在验证哪个版本。容器运行、认证成功和角色选择成功是前置条件，入图以新鲜状态的完整核对为准。启动失败先读 `status` 和工作台 `runtime/default/` 中的运行日志，保留未确认事实，再决定是否重开。

## 观察、选择能力并核对结果

先读 `snapshot`，再按需使用 `inspect scene/inventory/quests/skills`。`capabilities.native_actions` 来自有效在线桥；按领域响应的支持状态、来源与时效读取字段；只使用已提供的字段。任务观察支持正常增量，原始进度串及关联语义按原样保留。

在已确认安全区域选择一项有界 tick 动作并比较前后事实。仓库示例 [tick-jump-attack.lua](../shared/scripts/examples/tick-jump-attack.lua) 是可复用的有界移动跳砍脚本；仅需短移时写一个设置 `player.move`、在 `context.tick.time` 到达期限后清方向并返回 `done` 的 tick 文件。下面按示例运行，须先核实该方向有足够空间且没有其他脚本控制角色：

```bash
workbenches/workbench dev/NAME script describe /opt/beidou-pilot/shared/scripts/examples/tick-jump-attack.lua
workbenches/workbench dev/NAME script run /opt/beidou-pilot/shared/scripts/examples/tick-jump-attack.lua --direction right --seconds 5
workbenches/workbench dev/NAME snapshot
workbenches/workbench dev/NAME script status
```

按真实位置判断移动，按经验/等级判断成长，按库存和 HP/MP 判断恢复，按槽位变化判断换装。受理、输入派发、脚本完成与放键分别核对；命中、拾取或任务完成另行验证。结果不明时不重放消费、交易、奖励或加点。常驻角色按养成计划行动；开发样本按目标条件准备和核对。

角色持续动作写在 tick Lua 文件或目录脚本包里，入口声明 `main(context)`。`script describe/run/start` 从本角色的 `/work/scripts` 解析相对路径，例如 `script run control-tick.lua --seconds 20`；内置示例使用明确的容器绝对路径。长时运行须显式 `--continuous`。维护示例前读 [shared/scripts/AGENTS.md](../shared/scripts/AGENTS.md)，写脚本查 [Tick Lua API](LUA_TICK_API.md)。

同层移动、单根绳梯和门户都有场景前提。缺能力或静态资料时按实际错误与[缺口索引](CLIENT_LIMITATIONS.md)处理，未知事实保留原样。

## GUI 与首次登录的边界

需要 GUI 特有操作时，先完成账号和控制权交接，再按 [GUI 准备](CLI.md#原版-gui)从对应工作台启动：

```bash
workbenches/workbench dev/GUI_NAME open
workbenches/workbench dev/GUI_NAME snapshot
```

工作目录默认使用原版 GUI 的 `default` 实例；`backend` 可省略或设为 `beidou`。账号只支持 `world=0`，按账号配置的角色和频道正常登录。`--character/--character-index/--channel` 和固定账号/名称文件已退役。

通过当前 `snapshot`、`inspect stage` 和 `screenshot` 定位界面，优先使用新鲜对话正文与引用。根桌面 `click X Y` 必须依据当次截图。需要滚轮原语时，在所属 GUI 容器内执行，例如：

```bash
docker exec --user 1000:1000 CONTAINER python3 -m beidou_pilot.engines.desktop scroll down --ticks 1
```

原语直接操作该容器的显示环境，用于没有原生入口的界面操作。首次登录与建角走独立命令，由原生桥调用原版客户端内部动作；手工键鼠用于原生入口不可用的界面，并按当前账号、角色和选择记录操作。

有已有 CID 时用 `open` 入图。要验证首次登录或建角流程，使用开发分区的独立账号和[首次登录入口](CLI.md#首次登录与建角)，并分别核对注册、建角、绑定和实际入图。

## 停止、下线与交接

`script run` 的同步等待或 `script start` 的受理等待收到 Ctrl+C、SIGINT 或 SIGTERM 时，宿主薄入口向该次容器内 CLI 转发信号，只结束等待，已受理脚本继续运行。等待超时或观察失败只结束 CLI 等待，任务是否停止以当前脚本状态为准。中断或失败后先用 `script status` 观察当前任务及 `script.id`，核对受理和执行事实后再决定后续；Lua 执行期限及原生停止规则仍由 Runtime 处理。

需要停止脚本时按当前 `script.id` 显式 `script cancel --session SCRIPT_ID`，核对终态和放键后再交接；客户端关闭另用 `close`。详情见[控制协议](CONTROL.md#控制权期限与取消)。

```bash
workbenches/workbench dev/NAME script status
workbenches/workbench dev/NAME script cancel --session SCRIPT_ID
workbenches/workbench dev/NAME bridge status
workbenches/workbench dev/NAME close
workbenches/workbench dev/NAME status
```

取消后核对同一原生身份下的终态与 `control_released`；全局 `held_keys` 仍可能包含其他会话的合法持键，有惯性或动画时继续观察。需要停止全部会话并释放按键时用 `stop` 或 `bridge stop`；正常交接只取消自己的 `script.id`。短脚本结束保留客户端；宿主 `close` 才经 Docker 正常关闭、核实退出并回收。容器内 `close` 会提示使用宿主生命周期入口。危险区域结束有界执行后，先进入已验证安全位置或关闭所属实例，再长时间分析。

交接时，常驻角色记录养成计划及实际进度，开发角色更新 `STATE.md` 的当前条件、来源与核对时间。公开记录只给无私密结论。记录源码、镜像、桥和场景，分别汇报离线检查、构建、入图及实际动作。日常 `close` 只回收客户端，开发服无需随客户端关闭或重置。


## 伴游机器人（应用层）

伴游机器人不是客户端内置策略，而是计划跑在 GUI 客户端里的常驻 tick 目录脚本包；当前仍在设计与分阶段实施，尚未交付。机器人跟随、协助战斗、组队任务或 BOSS 行为由脚本和内容包决定。

- 机器人代码放该角色 `/work/scripts/bot/`，状态/事件/指令放 `/work/bot/`；一行一个角色。
- 玩家私聊控制和大模型自然语言属于后续原生能力；在聊天/队伍能力交付前，用宿主文件邮箱和同图跟随验证闭环。
- 机器人不接管 GUI 专属对话、商店、换装；这些走“停手 → 维护窗口 → 重启”的流程，不在战斗中间插操作。
- 第一版设计只做同图跟随/战斗；跨图跟随、NPC 交互、交易和手动 AP 仍是缺口，见[能力边界](CLIENT_LIMITATIONS.md)。
- 没有大模型时，固定指令 + 计划文件应能完整工作；大模型只是慢速参谋，不参与逐帧动作。

设计与验收细节见[伴游机器人设计与路线](COMPANION_BOT.md)。
