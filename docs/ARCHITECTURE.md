# 架构与支持范围

## 代码职责

| 位置 | 职责 |
| --- | --- |
| `workbenches/` | 宿主入口、开发服装配与无私密配置示例；定位角色、按提交构建客户端、核验分区目标并管理容器 |
| `cli/beidou-pilot`、`cli/beidou_pilot/` | 两个镜像共用的容器内 CLI、原生观察投影、参数和结果边界 |
| `shared/scripts/` | 随镜像固定的 tick 示例与有界运动校准探针；不含内置策略或函数库 |
| `shared/lua-runtime/` | 两端共用的 tick Lua 运行环境：调度、预算、只读领域、共享 player 状态机及输入生命周期 |
| `headless/src/` | 无渲染登录、网络与游戏更新宿主、共享桥适配 |
| `docker/` | 无头与 GUI 客户端镜像构建、GUI 资源装配和容器启动；`dev-server/` 单独部署开发服 |
| `beidou-ijl15/` | 北斗客户端 `ijl15.dll` 工程，新增桥直接实现共同契约，保留必要原生逻辑 |
| `third_party/` | 固定上游依赖与包含本地适配的派生引擎/资源转换器 |
| `cli/test/` | 客户端离线合同测试 |

Python 负责参数、静态资料规划、脚本装载/取消和最终结果。持续角色判断在客户端更新线程的 Lua 中执行，各适配器调用自己的原生游戏逻辑。普通命令与观察直接使用原生接口。

客户端只有 tick 引擎：脚本无需声明引擎，前导注释按需写 `@tick.gear/budget_ms/overrun/abort_commit`。每个会话有独立上下文，所有会话共享客户端唯一的 player 状态机；GUI 在应用更新返回后推进，无头在逻辑步进后推进，不假设两端帧长一致。CLI 只负责受理和按会话 ID 观察/取消，不逐帧控制。运行契约与能力边界见 [Lua API](LUA_TICK_API.md#tick-环境)和[控制协议](CONTROL.md)。

客户端提供观察和执行能力，操作者通过统一 CLI 获取事实、调度 Lua 并核对结果。游戏服负责游戏状态；仓库仅管理开发服的部署与访问入口，不包含服务端实现、存档或数据库。

## 容器、版本与控制生命周期

客户端交付为两个镜像：无头端包含原生无渲染客户端，GUI 端包含 Wine/VirtualGL 和桥 DLL；两者安装同一份 Python CLI、辅助引擎、共享 Runtime 和内置 Lua。运行中直接使用镜像内代码，进程与资源管理由宿主入口负责。

宿主入口按 `live/NAME` 或 `dev/NAME` 选择角色，绑定该分区的服务器。每个角色有自己的 `default` 实例；客户端后端、构建提交等从角色目录的 `workbench.json` 读取。新实例解析 `ref`（默认 `main`）并用对应 Git 树和固定子模块构建或复用镜像；GUI Compose 使用当前宿主启动器的版本。运行登记记录实际源码、镜像、后端、目标、角色和 `run_id`；已有实例继续使用启动时的镜像。

常驻服与半常驻开发服的网络和数据独立，客户端只连接本分区已核验的目标。`server dev up|stop|status|cli` 管理开发服；角色 `close` 不会停服，开发服日常停服保留数据。

每个工作目录拥有自己的 `default` 容器、运行目录、桥和控制锁。同一目标同一角色仍禁止并发接管。原生 `instance_id/run_id` 继续保证请求、取消与结果属于本次运行，真实断线或错误会退出并保留事实，不自动重连或重放。

容器入口从本次 `CLIENT_ROOT=/work/runtime/default/RUN_ID` 读取 `account.json`、`server.json`，生成内部资源映射与 `state/container.json`，随后保持 PID 交给对应原生进程。容器内 CLI 通过登记、进程和原生桥直接观察、执行桌面原语与登录。`open` 完成或确认本容器入图，进程已由宿主启动器创建。

宿主启动器负责 Docker 构建、创建和正常关闭。`close` 经 Docker SIGTERM 让镜像内原生客户端或 GUI bootstrap 取消、放键并退出，核对 `Running=false/Pid=0` 后保留日志并回收所属容器；容器内 `close` 明确返回 `host_lifecycle_required`。生命周期锁独立于 Lua 输入锁，活动脚本期间仍可正常关闭。

中断宿主命令时，启动器按本次执行 token 向对应容器内 CLI 转发信号。`script run` 的结果等待和 `script start` 的受理等待被中断时，仅结束本次等待；等待超时或观察失败时，已发布的原生任务继续运行。脚本会话继续由客户端 Runtime 持有，其执行期限与原生停止规则独立于 CLI 等待。结果未知时先用 `script status` 核对当前任务及 `script.id`，再决定是否重新启动；需要取消时显式 `script cancel --session SCRIPT_ID`，并核对同一原生身份下的终态与放键。客户端关闭另用 `close`。

[无头 Dockerfile](../docker/headless/Dockerfile) 在 builder 编译，在运行层使用发行版依赖。[GUI Dockerfile](../docker/gui/Dockerfile) 以根上下文构建 GUI 客户端，[GUI Compose](../docker/compose.yaml) 装配设备、只读资源与角色工作目录。开发服部署与客户端镜像分离，见[工作台指南](../workbenches/README.md)。

GUI DLL 仍由 Windows/MSVC、SDK 和匹配 Detours 库构建。完整 GUI 镜像默认通过 `gh` 获取所选提交成功 CI 的 DLL 与清单，开发时可在 `workbench.json.bridge_artifact` 指定匹配工件。启动器核对原生构建输入，匹配后接受；显式工件路径直接使用，无需 `gh`。

## 外部资源与配置

游戏资源不随源码或镜像分发。无头客户端、Quest、GUI 静态查询与 Python Catalog 共用原版 `Data/**/*.img`。无头端通过 `nl::node` 内存视图消费属性和几何元数据，不保留像素或音频内容。

宿主从主检出目录的 `private/workbenches/config/resources.json` 读取外部路径；开发 worktree 共用该配置，相对路径按配置文件目录解析。配置只保留必要的原版数据目录与 GUI 客户端目录：

```bash
workbenches/workbench dev/NAME resources-check
```

`resources-check` 将配置的原版 `Data/` 以只读方式挂入无网络短时容器，不需要服务器或账号。原件保持只读，`private/` 中的真实配置与数据不纳入 Git。

| 字段 | 用途 |
| --- | --- |
| `game_data` | 原版 `Data/` 目录，两端只读挂到 `/data`，供运行时节点视图与静态查询共用 |
| `gui_client` | 匹配 V17 的外部原客户端目录，只读挂到 GUI 容器 `/client` |

角色目录整体读写挂载到 `/work`。账号来自该目录的 `account.json`，目标来自主检出 `private/workbenches/config/` 中所属分区的 `live.server.json` 或 `dev.server.json`，不从角色配置选服。本次快照保存在 `/work/runtime/default/RUN_ID/`，`CLIENT_ROOT` 指向该目录。容器入口在其 `config/resources.json` 生成资源映射，`MAPLE_RESOURCES_CONFIG` 指向该文件；`gui_dll` 固定为 `/opt/beidou-pilot/native/ijl15.dll`，清单登记在该运行根的 `state/agent-bridge-build.json`。配置、角色记录和运行数据均不进入镜像。字段与入口见 [CLI](CLI.md)。

GUI 保留 `/client` 只读挂载用于启动原版客户端；原版 `Data/` 另以 `/data` 只读挂载，Python Catalog 与无头客户端从同一配置读取。客户端运行副本的 `Data/` 仍映射到原件，不写入资源目录。

用户 Lua 随所选角色目录挂载；脚本命令从 `/work/scripts` 解析相对路径，也接受显式容器绝对路径。内置 `shared/scripts/` 只含随镜像固定的 tick 示例与运动校准探针。

名称、物品恢复属性、NPC 范围和地图地形由同一个 `Catalog` 投影，现有 `inspect` 与静态查询共用；tick 脚本通过 `context.scene` 读取本图地形。Catalog 通过无头镜像和 GUI 镜像共同打包的原生 IMG 解析库查询属性、Canvas 尺寸、origin、帧时序和几何，不读取像素或音频。结果列出实际消费的 IMG 路径及 SHA256；`resource_version=null` 表示没有可证明的游戏版本，客户端版本另行核对。Map 类别按资源目录中的 `Map002/`、`Map/` 顺序选择；缺少文件或链接目标时保留未知。

原版 GUI 在本次 `$CLIENT_ROOT/client` 组装运行副本：复制原客户端的运行文件，`Data/` 链接到只读 `/client/Data`，再用镜像内已核验的桥替换运行副本中的 `ijl15.dll`。原客户端目录保持只读，运行副本使用独立运行文件。图片库 `2ijl15.dll` 仍是桥接 DLL 的运行依赖，必须保留。

宿主工作台整体挂为 `/work`，本次实例运行根为 `/work/runtime/default/RUN_ID`。GUI 的 Wine prefix、日志与桥位于 `$CLIENT_ROOT/runtime/prefix`、`$CLIENT_ROOT/runtime/runs` 和 `$CLIENT_ROOT/runtime/bridge`；无头路径沿用 `InstancePaths` 的后端/实例布局。GUI 生成文件允许容器内 `1000:1000` 读写。GUI 使用 `DISPLAY=:97`、Xvfb/窗口管理器、VirtualGL EGL 和 `/dev/dri/renderD128`；原资源只读、硬件初始化及真实游戏效果分别验收。

GUI 准备和统一入口见 [CLI](CLI.md#原版-gui)。

## 两端能力

| 能力 | 北斗 GUI | 无头端 |
| --- | --- | --- |
| 已有角色登录、退出、状态与实例管理 | 默认单实例；普通 GUI 登录 | 每工作目录独立容器；账号配置指定已有角色 |
| 阶段、角色、场景、背包、装备、金币与技能记录 | 原生观察 | 原生对象观察；技能读取与施放能力分别声明 |
| 同图其他玩家观察 | 原生用户池；含场景引用、角色标识、显示名、等级、位置与朝向 | 原生角色对象；同一字段口径 |
| 任务观察 | 当前原生任务对象 | 完整角色包与同会话正常增量；原始进度与未核实关联不推断 |
| 方向与动作意图（移动、跳跃、普攻、技能、拾取、用药） | tick Lua `player` 动作槽 | tick Lua `player` 动作槽 |
| 用药与食品 | tick Lua `player.use_item` 持续用药意图；原版 GUI 其他已支持物品按各自路径 | tick Lua `player.use_item`；200 类药剂与 201 类食品按本端能力，消耗与恢复分别确认 |
| 自定义移动、战斗与交互脚本 | 由用户 tick Lua 按场景能力组合动作 | 同左；受自身物理及资源支持范围约束 |
| 原始按键 | 原版扩展 | 不支持 |
| 按 ID 技能与方向同窗保持 | tick Lua `player.skill` 持续意图；原生规则决定实际施放 | 同左；首批战士 1001004/1001005，其他类型按本端能力 |
| 单场景连续狩猎 | 无内置策略；需要时由用户 tick Lua 自行实现 | 同左 |
| 服务端目标HP百分比 | 当前未知 | 已收到目标HP包后提供百分比、对象内序号及来源；攻击归因需结合上下文判断 |
| 普通装备穿戴、替换 | 原版 GUI 背包点击换装并核对槽位；无头不支持 | 不支持 |
| 死亡观察与正常复活 | 两端观察 `dead/revive_requestable`；复活由 GUI 确认框执行并核对同角色恢复 | 观察死亡事实；复活命令不支持 |
| 通用控件交互 | 原版 GUI 激活当前引用；无头端无桌面输入入口 | 只读返回 `interaction` 页面与控件引用，不支持激活 |
| 明确 AP/SP 分配 | 不提供自动分配命令 | 不提供自动分配命令 |
| 必要 GUI 窗口 | 原版 GUI 命令内部使用背包等必要窗口；只提供 `ui read` 读取 | 不支持 GUI 窗口 |
| 内容专属NPC命令、快捷键、商店 | 既有 GUI 工作流 | 不支持 |
| 截图、录制 | 当前游戏窗口采集 | 无画面采集，按结构化观察交付 |

支持范围以 `capabilities`、领域响应及当前命令实际结果为准。缺能力明确拒绝，未知值保持未知，服务端或其他客户端的事实另行核对。

tick Lua 以只读领域获取上表已有原生观察，覆盖角色、场景、背包、任务以及 GUI 的对话、商店和快捷键读数；观察结果保留本端来源、支持状态与时效。原生观察、CLI 工作流与 tick 动作仍是不同的支持面：商店与任务的完整交互界面由 GUI 命令处理，无头端仅只读观察。领域支持差异以 [tick API](LUA_TICK_API.md#独立只读领域) 为准。

会增加操作成本的现有边界及后续独立用户结果见[客户端能力边界与缺口索引](CLIENT_LIMITATIONS.md)。其中资源准备、目标交互、连续路线与结果反馈分别跟踪；入池不改变当前能力声明，有界玩法在现有能力内继续推进。

两端已通过本端原生对象提供 `scene` 的 `players`：无头端解析玩家出现封包后用原生角色对象，GUI 端读取原版客户端用户池，字段口径一致。tick 脚本可在有界场景内组合基础移动、跳跃与攻击，通用寻路、全职业与完整自主日程属于后续能力；两端物理与技能效果按各自原生规则判定。同服多账号容量和长期压力需要单独验证。

## 验证与镜像交付

离线合同、镜像构建和实际游戏结果分别判断。IPC 对端测试覆盖请求与取消；命中、掉落、存档和长期稳定性以真实客户端结果为准。开发服可准备并记录与验收匹配的场景，按所需后端核对；常驻服按角色自然进度使用。退出后核对所属资源及必要存档。

客户端构建使用 `workbenches/workbench dev/NAME build` 或对应的 `live/NAME`；镜像按所选 Git 提交交付。依赖来源和更新规则见 [DEPENDENCIES](DEPENDENCIES.md)。
