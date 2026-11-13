# 游戏 AI 操作指引

本篇供新会话从已有授权继续工作台。宿主唯一入口为 `private/workbenches/workbench DIR COMMAND`，客户端命令由它转发给所属容器。以下 `/external/workbench` 须替换为本次已确认的工作目录；参数以 `--help` 为准，完整命令、Lua 与支持范围见 [CLI](CLI.md)、[Lua API](LUA_API.md) 和[架构说明](ARCHITECTURE.md)。

可使用仓库技能 [beidou-pilot-client](../.agents/skills/beidou-pilot-client/SKILL.md) 按当前状态选择最短路径；缺少账号、没有角色或停在首次界面时，查其[账号准备与首次登录](../.agents/skills/beidou-pilot-client/references/first-login.md)，已有角色则按记录继续。

## 先确认目标、角色和操作者

从用户指令及已有记录确认服务器用途、已授权的账号与角色、允许的玩法和本次操作者。工作台中的养成方案和交接记录负责跨会话连续性，源码版本作为补充参考。可从本机 `LOCAL.md` 等索引找到配置；授权以用户指令和已有记录为准，文件存在、服务运行和账号可登录作为辅助事实。凭据只从授权私密文件读取，不进入参数值、日志或 Issue。

工作目录提供 `account.json`，可选 `workbench.json` 保存后端和开发设置；资源配置统一在主检出目录的 `private/workbenches/resources.json`。常驻服务器由入口固定；调试和实际游戏验收默认使用常驻服，优先找回并复用已有工作台、账号角色和就绪实例，减少主机内存占用。只有场景必须时才新建账号或角色；仅在常驻服无法安全完成验证等特殊情况下使用隔离服，记录原因并在该目录的 `workbench.json.server` 显式声明。先执行只读检查：

```bash
private/workbenches/workbench /external/workbench plan
private/workbenches/workbench /external/workbench status
```

`plan` 只读取配置与目标，不构建、不启动客户端或服务。确认返回的项目、服务、容器与镜像属于本次授权目标。固定的常驻目标作为授权范围的依据；开发隔离配置须为非 `beidou-ms` 项目、不发布宿主端口，指定网络时须为同项目internal网络。未指定网络则由 `open` 准备所属连接。核验失败先查配置和真实原因，确需切换服务器时明确说明目标。

结合本地认领、其他工作台与外部操作者、服务器在线账号/角色列表判断占用。`status` 只说明当前工作台实例，账号空闲状态以在线列表和认领记录为准。同一目标同一角色只交给一名控制者，GUI 只保留一名明确操作者；发现占用先完成交接。

## 用已有角色完成最小上手

准备方式见 [README](../README.md#准备)和[外部资源配置](ARCHITECTURE.md#外部资源与配置)。新实例默认使用 `main` 当时的已提交版本构建或复用镜像；开发验证在 `workbench.json.ref` 明确指定提交。已有容器后续命令继续使用启动时的 CLI 与内置 Lua，与当前主检出无关。

```bash
private/workbenches/workbench /external/workbench open
private/workbenches/workbench /external/workbench doctor
private/workbenches/workbench /external/workbench status
private/workbenches/workbench /external/workbench bridge status
private/workbenches/workbench /external/workbench capabilities
private/workbenches/workbench /external/workbench snapshot
```

两端使用同一份 `account.json`（权限 `0600`）：`username/password/character_id`，以及默认各为0的 `world/channel`。`character_id` 指已有角色；频道索引从0开始，返回实际频道从1开始。每个目录使用自己的 `default` 容器，启动器把本次账号和已解析服务器配置保存到 `runtime/default/RUN_ID`。整个工作目录读写挂到容器 `/work`，`CLIENT_ROOT` 指向本轮目录；用户只维护根账号与新建设置，运行快照自动生成。入图等待由 `workbench.json.timeout` 配置。

入图需同时确认新鲜状态中的 `ready`、角色 ID/名称、频道、地图和位置，原生 `instance_id/run_id` 须属于本次运行。`status` 还提供 `source_revision/image/run_id`，用它说明正在验证哪个版本。容器运行、认证成功和角色选择成功是前置条件，入图以新鲜状态的完整核对为准。启动失败先读 `status` 和工作台 `runtime/default/` 中的运行日志，保留未确认事实，再决定是否重开。

## 观察、选择能力并核对结果

先读 `snapshot`，再按需使用 `inspect scene/inventory/quests/skills`。`capabilities.native_actions` 来自有效在线桥；领域响应中的支持状态、来源与时效分别判断，未知保持未知。无头任务支持正常增量，原始进度串及关联语义按原样保留。

在已确认安全区域选择一项有界动作并比较前后事实。下面仅适用于已核实右侧可安全短移的场景：

```bash
private/workbenches/workbench /external/workbench walk right --seconds 0.2
private/workbenches/workbench /external/workbench snapshot
private/workbenches/workbench /external/workbench script status
```

按真实位置判断移动，按经验/等级判断成长，按库存和 HP/MP 判断恢复，按槽位变化判断换装。请求受理、输入派发、脚本完成与放键是分别可观察的事实，命中、拾取或任务完成另行核对。消费、交易、奖励、加点等结果不明时先观察，不可逆操作按一次执行处理；成长决策延续已核实的养成计划。

持续策略写 Lua。宿主入口转发 `script run --code CODE --seconds N`，或读取容器路径中的 UTF-8 文件；工作台内的 `scripts/` 直接位于 `/work/scripts`，例如 `script run /work/scripts/control.lua --seconds 20`。文件与源码二选一，持续模式须明确 `--continuous`。内置 Lua 随镜像固定，用户提交的 Lua 是本次明确输入，可在已有实例中更新。维护公共策略前阅读 [shared/scripts/AGENTS.md](../shared/scripts/AGENTS.md)，写脚本查 [Lua API](LUA_API.md)。

同层移动、单根绳梯和门户都有场景前提。缺能力或静态资料时按实际错误与[缺口索引](CLIENT_LIMITATIONS.md)处理，未知事实保留原样。

## GUI 与首次登录的边界

需要 GUI 特有操作时，先完成账号和控制权交接，再按 [GUI 准备](CLI.md#原版-gui)从对应工作台启动：

```bash
private/workbenches/workbench /external/gui-workbench open
private/workbenches/workbench /external/gui-workbench snapshot
```

GUI 工作目录在 `workbench.json` 选择 `backend="beidou"`，与无头端一样使用自己的 `default` 实例；账号只支持 `world=0`，按角色ID和频道正常登录。两端共享 CLI，但各自保留能力范围。GUI 的 `--character/--character-index/--channel` 和固定账号/名称文件已退役。

通过当前 `snapshot`、`inspect stage` 和 `screenshot` 定位界面，优先使用新鲜对话正文与引用。根桌面 `click X Y` 必须依据当次截图。需要滚轮原语时，在所属 GUI 容器内执行，例如：

```bash
docker exec --user 1000:1000 CONTAINER python3 -m beidou_pilot.engines.desktop scroll down --ticks 1
```

原语直接操作该容器的显示环境，仅用于没有原生入口的界面操作。首次登录与建角走独立命令，由原生桥调用原版客户端内部动作；手工键鼠只在原生入口无法操作时作为兜底，并须先确认账号、身份与选择意图。未知选择按当前记录处理。

当前统一 `open` 要求真实已有角色 CID，无角色账号的启动模式作为独立能力跟踪。已有且归属正确的 GUI 会话可以接续正常首次流程；全新账号需先建立可接续会话，再按该流程继续。

## 停止、下线与交接

`script run` 的同步等待或 `script start` 的受理等待收到 Ctrl+C、SIGINT 或 SIGTERM 时，宿主薄入口向该次容器内 CLI 转发信号，只结束等待，已受理脚本继续运行。等待超时或观察失败只结束 CLI 等待，任务是否停止以当前脚本状态为准。中断或失败后先用 `script status` 观察当前任务及 `script.id`，核对受理和执行事实后再决定后续；Lua 执行期限及原生停止规则仍由 Runtime 处理。

需要停止脚本时按当前 `script.id` 显式 `script cancel --session SCRIPT_ID`，核对终态和放键后再交接；客户端关闭另用 `close`。harness 的 `pause/stop` 只管理 LLM 会话，客户端和脚本继续运行；重新接入先观察已有任务。详情见 [控制协议](CONTROL.md#控制权期限与取消)和 [harness 协作](HARNESS.md#开发-ai-的协作通道)。

```bash
private/workbenches/workbench /external/workbench script status
private/workbenches/workbench /external/workbench script cancel --session SCRIPT_ID
private/workbenches/workbench /external/workbench bridge status
private/workbenches/workbench /external/workbench close
private/workbenches/workbench /external/workbench status
```

取消后核对同一原生身份下的终态和 `held_keys=[]`；有惯性或动画时继续观察。空闲遗留控制可用 `stop`，活动控制者的控制权保持。短脚本结束保留客户端；宿主 `close` 才经 Docker 正常关闭、核实退出并回收。容器内 `close` 会提示使用宿主生命周期入口。危险区域结束有界执行后，先进入已验证安全位置或关闭所属实例，再长时间分析。

交接保留账号角色的计划、实际进度、下一步、所用源码/镜像/桥版本与必要证据引用。公开记录只给无私密结论。离线检查、构建、入图、移动、战斗和恢复分别报告，各端结果按本端真实结果记录。
