# 架构与支持范围

## 代码职责

| 位置 | 职责 |
| --- | --- |
| `private/workbenches/workbench` | 宿主 Bash 薄入口；从提交构建、核验目标、管理 Docker 生命周期与 exec 路由 |
| `cli/beidou-pilot`、`cli/beidou_pilot/` | 两个镜像共用的容器内 CLI、原生观察投影、参数和结果边界 |
| `shared/scripts/` | 按travel/combat/recovery分类的复合能力，examples保存少量公共API示例 |
| `shared/lua-runtime/` | 两端共用的Lua调度、预算、状态模型与game API，独立于具体客户端 |
| `headless/src/` | 无渲染登录、网络与游戏更新宿主、共享桥适配 |
| `docker/` | 无头与 GUI 镜像构建定义、唯一 Compose、资源装配和容器启动脚本；`docker/harness/` 从客户端镜像派生 AI 运行环境 |
| `harness/` | 容器内模型会话控制器、角色设定与经历、开发 AI 专用协作；通过同容器 CLI 消费客户端 |
| `beidou-ijl15/` | 北斗客户端 `ijl15.dll` 工程，新增桥直接实现共同契约，保留必要原生逻辑 |
| `third_party/` | 固定上游依赖与包含本地适配的派生引擎/资源转换器 |
| `cli/test/` | 客户端离线合同测试 |

Python 负责参数、静态资料规划、脚本装载/取消和最终结果。持续角色判断在客户端更新线程的 Lua 中执行，各适配器调用自己的原生游戏逻辑。普通命令与观察不会逐帧经过模型或截图。

客户端运行体只拥有执行和观察能力，主要由 Lua 脚本驱动。同仓 `harness/` 是可选的旁路决策消费者，与客户端运行时并行、独立启停，持有模型会话、角色设定、目标与游戏经历，通过既有 CLI 获取观察并调度脚本。客户端与 Lua 在没有 LLM 时仍可持续运行；`cli/beidou_pilot/`、原生适配器及共享 Lua Runtime 不依赖模型或角色记忆。服务端和数据库不纳入本仓库。

启用 harness 的镜像继承所选无头或 GUI 客户端镜像，增加固定版本的 Node/Codex、Python harness 和专用客户端技能，保留原客户端入口与 PID 1。唯一宿主入口 `private/workbenches/workbench DIR ai [harness参数]` 通过 `docker exec` 启动所属客户端容器内的 `beidou-game-ai`；harness 在本容器启动 Codex app-server，模型通过 shell 直接执行 `beidou-pilot`。`read_only` 模式关闭 shell，仅提供 `game_observe` 和 `game_script_status` 两个观察工具。

模型固定工作目录为 `/game`，专用技能放在 `/game/.agents/skills/beidou-pilot-client`，所需公共文档按相对链接布局打包；不复制仓库 `AGENTS.md`、宿主技能或开发 Codex 配置，也不挂开发仓库或 Docker socket。

harness 可在已有活动脚本时接入。`pause/stop` 仅中断并确认当前 LLM turn 终态，不清理后台 shell、不取消 Lua，也不关闭客户端；模型退出后，客户端 PID1、登录会话、容器及已启动的脚本和游戏任务继续运行。`resume` 复用仍存活的 app-server 和 thread，先核对当前实例、`script.id` 及任务状态，避免重复启动或抢占已有执行。重新接入同样先观察；脚本取消与客户端关闭分别由明确命令发起。具体配置与协作入口见 [HARNESS](HARNESS.md)。

`--state`、角色文件和模型配置等路径参数均为容器路径，需长期保留的状态放在 `/work`。模型线程与角色记忆仍由 harness 管理；稳定工作目录、角色与目标绑定一致时，可以在新客户端 run 中续接，原生 `instance_id/run_id` 按本次运行重新核验。旧 `lua-v1`、`hunt-v1` 工具会话明确拒绝恢复。

## 容器、版本与控制生命周期

客户端基础交付为两个镜像：无头端包含原生无渲染客户端，GUI 端包含 Wine/VirtualGL 和桥 DLL；两者安装同一份 Python CLI、辅助引擎、共享 Runtime 和内置 Lua。启用 harness 时分别从对应客户端基础镜像构建衍生镜像，沿用客户端进程及资源装配；镜像继承只用于打包复用，不绑定模型与客户端的生命周期。运行中不挂载宿主开发源码，客户端内也不需要 Docker socket。

唯一宿主入口以工作目录选择容器。每个目录保存一个账号角色，使用固定的 `default` 实例；后端、开发提交和必要新建设置从目录的 `workbench.json` 读取。`harness` 默认 `false`，设为 `true` 时选用对应衍生镜像；`model_proxy` 为可选的 `http://IPv4:port`，未配置不影响客户端及脚本运行。新实例一次解析默认main或配置ref的已提交SHA，导出该树和固定子模块构建或复用镜像。构建期间的代码变化不混入本次输入。运行登记保留实际源码、镜像、后端、目标、角色和run_id；已有实例的观察、脚本和取消均经docker exec使用原镜像，不重新读取新建设置。

只有启用 harness 且 `model_proxy` 非空时，客户端才额外连接 Docker 默认 `bridge` 网络以访问模型代理，GUI 防火墙也仅在此时为指定代理 IPv4 和端口增加放行规则。游戏服务器仍处于原有 internal 网络，游戏连接继续使用已核验目标；模型出口不改变游戏服务器网络和只读资源挂载。

每个工作目录拥有自己的 `default` 容器、运行目录、桥和控制锁。同一目标同一角色仍禁止并发接管。原生 `instance_id/run_id` 继续保证请求、取消与结果属于本次运行，真实断线或错误会退出并保留事实，不自动重连或重放。

普通与只读 harness 的状态目录进程锁仅保护模型会话状态，同一状态目录被占用时返回 `harness_state_busy`。模型进程锁不代表持有角色、Lua 脚本或游戏任务的控制权。

容器入口从本次 `CLIENT_ROOT=/work/runtime/default/RUN_ID` 读取 `account.json`、`server.json`，生成内部资源映射与 `state/container.json`，随后保持 PID 交给对应原生进程。容器内 CLI 通过登记、进程和原生桥直接观察、执行桌面原语与登录。`open` 完成或确认本容器入图，不再调用 Docker 创建进程。

宿主启动器负责 Docker 构建、创建和正常关闭。`close` 经 Docker SIGTERM 让镜像内原生客户端或 GUI bootstrap 取消、放键并退出，核对 `Running=false/Pid=0` 后保留日志并回收所属容器；容器内 `close` 明确返回 `host_lifecycle_required`。生命周期锁独立于 Lua 输入锁，活动脚本不阻挡关闭。

中断宿主命令时，启动器按本次执行 token 向对应容器内 CLI 转发信号。`script run` 的结果等待和 `script start` 的受理等待被中断时，仅结束本次等待；等待超时或观察失败也不自动停止已发布的原生任务。脚本会话继续由客户端 Runtime 持有，其执行期限与原生停止规则独立于 CLI 等待。结果未知时先用 `script status` 核对当前任务及 `script.id`，不重放启动；需要取消时显式 `script cancel --session SCRIPT_ID`，并核对同一原生身份下的终态与放键。客户端关闭另用 `close`。

[无头 Dockerfile](../docker/headless/Dockerfile) 是无头镜像唯一构建入口，builder 编译，运行层使用标准发行版运行依赖。[GUI Dockerfile](../docker/gui/Dockerfile) 以根上下文构建完整 GUI 客户端，唯一的 [Compose](../docker/compose.yaml) 装配设备、只读资源与整个工作台；用户脚本和配置直接使用工作台中的路径。所有定义放在 `docker/`，根 `.dockerignore` 只保留两端构建必需的源码与明确桥工件输入。

GUI DLL 仍由 Windows/MSVC、SDK 和匹配 Detours 库构建。完整 GUI 镜像默认通过 `gh` 获取所选提交成功 CI 的 DLL 与清单，开发时可在 `workbench.json.bridge_artifact` 指定匹配工件。启动器核对原生构建输入，无法匹配时明确拒绝；显式工件路径无需 `gh`。

## 外部资源与配置

游戏资源不随源码或镜像分发。无头客户端、Quest、GUI 静态查询与 Python Catalog 共用原版 `Data/**/*.img`。无头端通过 `nl::node` 内存视图消费属性和几何元数据，不保留像素或音频内容。

宿主从主检出目录的 `private/workbenches/resources.json` 读取外部路径；开发 worktree 共用该配置，相对路径按配置文件目录解析。配置只保留必要的原版数据目录与 GUI 客户端目录：

```bash
cat private/workbenches/resources.json
private/workbenches/workbench /external/workbench resources-check
```

`resources-check` 将配置的原版 `Data/` 以只读方式挂入无网络短时容器，解析现有资源，不需要服务器或账号。资源原件不复制或修改；仅 `private/workbenches/workbench` 纳入 Git，共享资源配置与其他 `private/` 内容保持忽略。

| 字段 | 用途 |
| --- | --- |
| `game_data` | 原版 `Data/` 目录，两端只读挂到 `/data`，供运行时节点视图与静态查询共用 |
| `gui_client` | 匹配 V17 的外部原客户端目录，只读挂到 GUI 容器 `/client` |

工作目录整体读写挂载到 `/work`，根目录维护 `account.json` 和可选新建设置。常驻服务器定义固定在入口；开发隔离目标来自 `workbench.json.server`。本次账号和完整服务器快照保存在 `/work/runtime/default/RUN_ID/`，`CLIENT_ROOT` 指向该目录。容器入口在其 `config/resources.json` 生成资源映射，`MAPLE_RESOURCES_CONFIG` 指向该文件；内部 `gui_dll` 固定为镜像内 `/opt/beidou-pilot/native/ijl15.dll`，清单登记在该运行根的 `state/agent-bridge-build.json`。配置、角色计划和运行数据均不进入镜像。字段与入口见 [CLI](CLI.md)。

GUI 保留 `/client` 只读挂载用于启动原版客户端；原版 `Data/` 另以 `/data` 只读挂载，Python Catalog 与无头客户端从同一配置读取。客户端运行副本的 `Data/` 仍映射到原件，不写入资源目录。

用户 Lua 是工作台中的明确输入，直接位于 `/work/scripts`，无需独立挂载。内置 `shared/scripts/` 随镜像固定，用户 Lua 文件与 `--code` 可在运行中提交，不要求重建镜像；它们不改变模型、养成或生命周期职责。

名称、物品恢复属性、NPC范围和地图门户/绳梯/地形由同一个 `Catalog` 投影，现有 `inspect`、旅行、恢复与 `hunt` 共用。Catalog 通过无头镜像和 GUI 镜像共同打包的原生 IMG 解析库查询属性、Canvas 尺寸、origin、帧时序和几何，不读取像素或音频。结果列出实际消费的 IMG 路径及 SHA256；`resource_version=null` 表示没有可证明的游戏版本，文件指纹不推断客户端版本。Map 类别按资源目录中的 `Map002/`、`Map/` 顺序选择；缺少文件或链接目标时保留未知。

原版 GUI 在本次 `$CLIENT_ROOT/client` 组装运行副本：复制原客户端的运行文件，`Data/` 链接到只读 `/client/Data`，再用镜像内已核验的桥替换运行副本中的 `ijl15.dll`。原客户端目录保持只读，不能用硬链接或可写链接替代独立运行文件。图片库 `2ijl15.dll` 仍是桥接 DLL 的运行依赖，必须保留。

宿主工作台整体挂为 `/work`，本次实例运行根为 `/work/runtime/default/RUN_ID`。GUI 的 Wine prefix、日志与桥位于 `$CLIENT_ROOT/runtime/prefix`、`$CLIENT_ROOT/runtime/runs` 和 `$CLIENT_ROOT/runtime/bridge`；无头路径沿用 `InstancePaths` 的后端/实例布局。GUI 生成文件允许容器内 `1000:1000` 读写。GUI 使用 `DISPLAY=:97`、Xvfb/窗口管理器、VirtualGL EGL 和 `/dev/dri/renderD128`；原资源只读、硬件初始化及真实游戏效果分别验收。

GUI 准备和统一入口见 [CLI](CLI.md#原版-gui)。

## 两端能力

| 能力 | 北斗 GUI | 无头端 |
| --- | --- | --- |
| 已有角色登录、退出、状态与实例管理 | 默认单实例；普通 GUI 登录 | 每工作目录独立容器；账号配置指定已有角色 |
| 阶段、角色、场景、背包、装备、金币与技能记录 | 原生观察 | 原生对象观察；读取技能不代表可执行技能 |
| 任务观察 | 当前原生任务对象 | 完整角色包与同会话正常增量；原始进度与未核实关联不推断 |
| 移动、朝向、跳跃、普攻、近距拾取、停止 | 共同 Lua 语义 | 共同 Lua 语义 |
| 用药与食品 | 普通200类按ID直接原生调用，无需绑定；其他已支持物品保留GUI工作流 | 200 类药剂与 201 类食品；食品明确单次消费不要求恢复资料，消耗与恢复分别确认 |
| 同层移动、爬绳、单个门户、基础战斗 | 内置 Lua | 内置 Lua；受自身物理及资源支持范围约束 |
| 原始按键 | 原版扩展 | 不支持 |
| 直接技能与移动攻击同窗 | 原生技能入口；语义攻击窗可同时保持方向 | 首批战士1001004/1001005；普攻或支持技能可同时保持方向，原生规则决定实际移动 |
| 单场景连续狩猎 | 共享 `hunt`，从同源地形自主选择可达目标 | 同一策略；绳梯/平台/落层按自身物理确认，换场景停止 |
| 服务端目标HP百分比 | 当前未知 | 已收到目标HP包后提供百分比、对象内序号及来源，不能归因到某次攻击 |
| 普通装备穿戴、替换、卸下 | Lua 普通唯一槽位穿戴与对象交换确认；多目标/特殊槽位保留既有 CLI 路径，Lua 卸下不支持 | 共享 Lua 槽位操作，正常库存更新确认源、目的装备对象 |
| 死亡观察与正常复活 | 既有 CLI GUI 确认框；Lua 复活不支持 | 原生 HP 死亡事实、共享 Lua 单次正常复活请求与同角色恢复确认 |
| 通用控件交互 | 新Lua激活未支持；既有桌面消费者保持 | 原生 `interaction` 页面与 `activate(ref)`；服务端普通脚本页和资源支持的本地任务页共用控件模型 |
| 明确 AP/SP 分配 | CLI/Lua 共同逐点双确认，原生技能页资格与必要窗口 | Lua/CLI 逐点双确认；SP 覆盖冒险家普通职业点数池 |
| 必要养成窗口与焦点 | Lua/CLI 的背包、属性、技能窗口及游戏焦点 | 不支持 GUI 窗口 |
| 内容专属NPC命令、快捷键、商店 | 既有 GUI 工作流 | 不支持 |
| 截图、录制 | 当前游戏窗口采集 | 不提供画面 |

支持范围以 `capabilities`、领域响应及当前命令实际结果为准。缺能力明确拒绝，未知值不能按零、关闭、不可见或空集合处理，也不从服务端后台或另一客户端补齐。

Lua 通过按需 `game.observe(domain)` 复用上表已有原生观察，覆盖 NPC、金币、技能、装备与任务，以及 GUI 的窗口、对话、商店和快捷键；`game.state()` 继续提供轻量基础状态。原生观察、CLI 工作流与 Lua 动作仍是不同的支持面：读取商店或任务不表示已具备完整交互界面。无头新增交互复用“观察当前页面→激活控件引用”，协议细节留在原生组件；普通换装继续使用已有槽位操作。领域支持、来源和时效保留各端差异，详见 [Lua API](LUA_API.md#按需领域观察)。

会增加操作成本的现有边界及后续独立用户结果见[客户端能力边界与缺口索引](CLIENT_LIMITATIONS.md)。其中资源准备、目标交互、连续路线与结果反馈分别跟踪；入池不改变当前能力声明，也不表示需要先完成全部能力才可继续有界玩法。

无头端尚有其他玩家出现封包的解析缺口，scene 目前不提供其他玩家列表。当前基础战斗和有限移动不等于通用寻路、全职业或完整自主日程；两端物理与技能效果不承诺精确等价。同服多账号容量和长期压力需要单独验证。

## 验证与镜像交付

离线合同、镜像构建和实际游戏结果分别判断。IPC 对端测试只能证明请求/取消契约，不能证明命中、掉落、存档或长期稳定性。实际玩法默认使用常驻服务器，优先复用已授权的已有账号角色和就绪实例，减少主机内存占用；仅在场景必须时新建账号或角色，隔离服仅用于常驻服无法安全完成验证等特殊情况，并记录原因。退出后核对所属资源及必要存档。

客户端构建统一使用 `private/workbenches/workbench DIR build`；启动器从 Git 提交及其子模块准备固定输入，再调用对应 Dockerfile。客户端以版本化镜像交付，工作台保存其配置、计划与运行数据。依赖来源和更新规则见 [DEPENDENCIES](DEPENDENCIES.md)。
