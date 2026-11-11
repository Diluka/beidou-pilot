# 架构与支持范围

## 代码职责

| 位置 | 职责 |
| --- | --- |
| 根 `beidou-pilot` | 宿主 Bash 薄入口；从提交构建、核验目标、管理 Docker 生命周期与 exec 路由 |
| `cli/beidou-pilot`、`cli/beidou_pilot/` | 两个镜像共用的容器内 CLI、原生观察投影、参数和结果边界 |
| `shared/scripts/` | 按travel/combat/recovery分类的复合能力，examples保存少量公共API示例 |
| `shared/lua-runtime/` | 两端共用的Lua调度、预算、状态模型与game API，独立于具体客户端 |
| `headless/src/` | 无渲染登录、网络与游戏更新宿主、共享桥适配 |
| `docker/` | 无头与 GUI 镜像构建定义、GUI Compose、资源装配和容器启动脚本；`docker/harness/` 构建独立 Codex 环境 |
| `harness/` | 宿主薄控制器、模型会话、角色设定与经历、开发 AI 专用协作；通过既有 CLI 消费客户端 |
| `beidou-ijl15/` | 北斗客户端 `ijl15.dll` 工程，新增桥直接实现共同契约，保留必要原生逻辑 |
| `third_party/` | 固定上游依赖与包含本地适配的派生引擎/资源转换器 |
| `cli/test/` | 客户端离线合同测试 |

Python 负责参数、静态资料规划、脚本装载/取消和最终结果。持续角色判断在客户端更新线程的 Lua 中执行，各适配器调用自己的原生游戏逻辑。普通命令与观察不会逐帧经过模型或截图。

客户端运行体只拥有执行和观察能力，主要由 Lua 脚本驱动。同仓 `harness/` 是独立的决策消费者，持有模型会话、角色设定、目标与游戏经历，通过既有 CLI 获取观察并调度脚本；`cli/beidou_pilot/`、原生适配器及共享 Lua Runtime 不依赖模型或角色记忆。服务端和数据库不纳入本仓库。

Codex app-server 在独立 harness 容器中运行，宿主薄控制器分派少量动态游戏工具，固定工作台与实例，通过宿主薄入口调用所属客户端容器内的 CLI。模型容器不挂开发仓库、宿主 Codex 配置或 Docker socket。客户端和 harness 各有生命周期；暂停或停止玩法需取消原 Lua CLI 并确认所属实例放键，停止 harness 不关闭客户端。具体配置与协作入口见 [HARNESS](HARNESS.md)。

## 容器、版本与控制生命周期

客户端交付为两个镜像：无头端包含原生无渲染客户端，GUI 端包含 Wine/VirtualGL 和桥 DLL；两者安装同一份 Python CLI、辅助引擎、共享 Runtime 和内置 Lua。运行中不挂载宿主开发源码，客户端内也不需要 Docker socket。

宿主根入口以工作台与实例名选择容器。新实例一次解析 `main` 的已提交 SHA，导出该树和固定子模块构建或复用镜像；开发验收可显式指定 `--ref`。构建输入不混入后续 `main` 更新或未提交内容。运行登记保留源码版本、实际镜像、后端、目标、角色和 `run_id`。已有实例的观察、脚本和取消都经 `docker exec` 使用原镜像代码；更新主检出不会改变其内置策略。

每个工作台实例拥有独立容器、运行目录、桥和控制锁。GUI 在一个工作台中只使用 `default`；无头可按名字建实例。同一目标同一角色仍禁止并发接管。原生 `instance_id/run_id` 继续保证请求、取消与结果属于本次运行，真实断线或错误会退出并保留事实，不自动重连或重放。

容器入口从本次 `CLIENT_ROOT=/work/runtime/INSTANCE/RUN_ID` 读取 `account.json`、`server.json`，生成内部资源映射与 `state/container.json`，随后保持 PID 交给对应原生进程。容器内 CLI 通过登记、进程和原生桥直接观察、执行桌面原语与登录。`open` 完成或确认本容器入图，不再调用 Docker 创建进程。

宿主启动器负责 Docker 构建、创建和正常关闭。`close` 经 Docker SIGTERM 让镜像内原生客户端或 GUI bootstrap 取消、放键并退出，核对 `Running=false/Pid=0` 后保留日志并回收所属容器；容器内 `close` 明确返回 `host_lifecycle_required`。生命周期锁独立于 Lua 输入锁，活动脚本不阻挡关闭。取消原宿主命令时，启动器按本次执行 token 向对应容器内 CLI 转发信号，并等待其原生放键确认。

[无头 Dockerfile](../docker/headless/Dockerfile) 是无头镜像唯一构建入口，builder 编译，运行层使用标准发行版运行依赖。[GUI Dockerfile](../docker/gui/Dockerfile) 以根上下文构建完整 GUI 客户端，唯一的 [Compose](../docker/compose.yaml) 装配设备、只读资源与整个工作台；用户脚本和配置直接使用工作台中的路径。所有定义放在 `docker/`，根 `.dockerignore` 只保留两端构建必需的源码与明确桥工件输入。

GUI DLL 仍由 Windows/MSVC、SDK 和匹配 Detours 库构建。完整 GUI 镜像默认通过 `gh` 获取所选提交成功 CI 的 DLL 与清单，开发时可用 `--bridge-artifact` 显式复用现有工件。启动器核对原生构建输入，无法匹配时明确拒绝；显式工件路径无需 `gh`。

## 外部资源与配置

游戏资源不随源码或镜像分发。无头端当前读取由外部北斗 `Data/` 转换的 metadata-only NX；保留玩法所需属性、帧时序和几何数据，没有可绘制像素或可播放音频。

转换时显式指定外部客户端，输出必须位于原资源目录之外：

```bash
python3 headless/tools/prepare_resources.py \
  --client-root /external/BeiDou-Client \
  --output /external/headless-nx
./beidou-pilot --workbench /external/workbench --backend headless resources-check \
  --resources /external/resources.json
```

转换工具需要本机 C++17 编译器；已有 NX 时无需转换。统一的 `resources-check` 根据外部配置找到 NX，使用所选提交的无头镜像和无网络短时容器离线检查，不需要服务器或账号配置。

宿主从工作台 `resources.json` 读取外部路径，也可由宿主 `--resources PATH` 指定；相对路径按该配置文件目录解析。它不含账号，不提交。字段如下：

| 字段 | 用途 |
| --- | --- |
| `headless_resources` | 同源外部 NX 目录，两端只读挂到 `/data`，用于原生无头运行、静态查询和策略装载 |
| `metadata_root` | 可选 WZ XML，只读挂到 `/metadata`；对应资料不存在时使用同源 NX 或保留未知 |
| `gui_client` | 匹配 V17 的外部原客户端目录，只读挂到 GUI 容器 `/client` |

工作台整体读写挂载到 `/work`，根目录成对维护 `account.json`、`server.json`。本次输入保存在 `/work/runtime/INSTANCE/RUN_ID/`，`CLIENT_ROOT` 指向该目录。容器入口在其 `config/resources.json` 生成资源映射，`MAPLE_RESOURCES_CONFIG` 指向该文件；内部 `gui_dll` 固定为镜像内 `/opt/beidou-pilot/native/ijl15.dll`，清单登记在该运行根的 `state/agent-bridge-build.json`。配置、角色计划和运行数据均不进入镜像。字段与入口见 [CLI](CLI.md)。

原版 `/client`、NX `/data` 的来源、格式和只读挂载保持不变。原始 IMG 直读尚在研究，本次装配更改不合并、复制或迁移资源。GUI 未配置 WZ XML 时，唯一 Compose 使用本次运行目录中的空目录作为 `/metadata` 的挂载源；空目录不提供资料，仍按现有 Catalog 规则使用同源 NX 或保留未知。

用户 Lua 是工作台中的明确输入，直接位于 `/work/scripts`，无需独立挂载。内置 `shared/scripts/` 随镜像固定，用户 Lua 文件与 `--code` 可在运行中提交，不要求重建镜像；它们不改变模型、养成或生命周期职责。

名称、物品恢复属性、NPC范围和地图门户/绳梯/地形由同一个 `Catalog` 投影，现有 `inspect`、旅行、恢复与 `hunt` 共用。NX只读取属性与几何元数据，像素和音频不进入CLI或镜像。结果列出实际资料文件、SHA256及可用转换清单；`resource_version=null` 表示没有可证明的游戏版本，指纹相同不代表已经核实与运行客户端同版。地图来源遵循原生的 `Map002.nx` 优先选择，链接图没有自身地形时明确拒绝，不静默套用别图。

原版 GUI 在本次 `$CLIENT_ROOT/client` 组装运行副本：复制原客户端的运行文件，`Data/` 链接到只读 `/client/Data`，再用镜像内已核验的桥替换运行副本中的 `ijl15.dll`。原客户端目录保持只读，不能用硬链接或可写链接替代独立运行文件。图片库 `2ijl15.dll` 仍是桥接 DLL 的运行依赖，必须保留。

宿主工作台整体挂为 `/work`，本次实例运行根为 `/work/runtime/INSTANCE/RUN_ID`。GUI 的 Wine prefix、日志与桥位于 `$CLIENT_ROOT/runtime/prefix`、`$CLIENT_ROOT/runtime/runs` 和 `$CLIENT_ROOT/runtime/bridge`；无头路径沿用 `InstancePaths` 的后端/实例布局。GUI 生成文件允许容器内 `1000:1000` 读写。GUI 使用 `DISPLAY=:97`、Xvfb/窗口管理器、VirtualGL EGL 和 `/dev/dri/renderD128`；原资源只读、硬件初始化及真实游戏效果分别验收。

GUI 准备和统一入口见 [CLI](CLI.md#原版-gui)。

## 两端能力

| 能力 | 北斗 GUI | 无头端 |
| --- | --- | --- |
| 已有角色登录、退出、状态与实例管理 | 默认单实例；普通 GUI 登录 | 命名多实例；账号配置指定已有角色 |
| 阶段、角色、场景、背包、装备、金币与技能记录 | 原生观察 | 原生对象观察；读取技能不代表可执行技能 |
| 任务观察 | 当前原生任务对象 | 完整角色包与同会话正常增量；原始进度与未核实关联不推断 |
| 移动、朝向、跳跃、普攻、近距拾取、停止 | 共同 Lua 语义 | 共同 Lua 语义 |
| 用药与食品 | 普通200类按ID直接原生调用，无需绑定；其他已支持物品保留GUI工作流 | 200 类药剂与 201 类食品；食品明确单次消费可不依赖 XML，消耗与恢复分别确认 |
| 同层移动、爬绳、单个门户、基础战斗 | 内置 Lua | 内置 Lua；受自身物理及资源支持范围约束 |
| 原始按键 | 原版扩展 | 不支持 |
| 直接技能与移动攻击同窗 | 原生技能入口；语义攻击窗可同时保持方向 | 首批战士1001004/1001005；普攻或支持技能可同时保持方向，原生规则决定实际移动 |
| 单场景连续狩猎 | 共享 `hunt`，从同源地形自主选择可达目标 | 同一策略；绳梯/平台/落层按自身物理确认，换场景停止 |
| 服务端目标HP百分比 | 当前未知 | 已收到目标HP包后提供百分比、对象内序号及来源，不能归因到某次攻击 |
| 普通装备穿戴、替换、卸下 | 既有 CLI GUI 穿戴流程；Lua 两入口不支持 | 共享 Lua 槽位操作，正常库存更新确认源、目的装备对象 |
| 死亡观察与正常复活 | 既有 CLI GUI 确认框；Lua 复活不支持 | 原生 HP 死亡事实、共享 Lua 单次正常复活请求与同角色恢复确认 |
| 通用控件交互 | 新Lua激活未支持；既有桌面消费者保持 | 原生 `interaction` 页面与 `activate(ref)`；服务端普通脚本页和资源支持的本地任务页共用控件模型 |
| 内容专属NPC命令、窗口、快捷键、加点、商店 | 既有 GUI 工作流 | 不支持 |
| 截图、录制 | 当前游戏窗口采集 | 不提供画面 |

支持范围以 `capabilities`、领域响应及当前命令实际结果为准。缺能力明确拒绝，未知值不能按零、关闭、不可见或空集合处理，也不从服务端后台或另一客户端补齐。

Lua 通过按需 `game.observe(domain)` 复用上表已有原生观察，覆盖 NPC、金币、技能、装备与任务，以及 GUI 的窗口、对话、商店和快捷键；`game.state()` 继续提供轻量基础状态。原生观察、CLI 工作流与 Lua 动作仍是不同的支持面：读取商店或任务不表示已具备完整交互界面。无头新增交互复用“观察当前页面→激活控件引用”，协议细节留在原生组件；普通换装继续使用已有槽位操作。领域支持、来源和时效保留各端差异，详见 [Lua API](LUA_API.md#按需领域观察)。

会增加操作成本的现有边界及后续独立用户结果见[客户端能力边界与缺口索引](CLIENT_LIMITATIONS.md)。其中资源准备、目标交互、连续路线与结果反馈分别跟踪；入池不改变当前能力声明，也不表示需要先完成全部能力才可继续有界玩法。

无头端尚有其他玩家出现封包的解析缺口，scene 目前不提供其他玩家列表。当前基础战斗和有限移动不等于通用寻路、全职业或完整自主日程；两端物理与技能效果不承诺精确等价。同服多账号容量和长期压力需要单独验证。

## 验证与镜像交付

离线合同、镜像构建和实际游戏结果分别判断。IPC 对端测试只能证明请求/取消契约，不能证明命中、掉落、存档或长期稳定性。实际玩法使用授权专用角色和隔离目标，退出后核对所属资源及必要存档。

客户端构建统一使用根 `beidou-pilot build`；启动器从 Git 提交及其子模块准备固定输入，再调用对应 Dockerfile。客户端以版本化镜像交付，工作台保存其配置、计划与运行数据。依赖来源和更新规则见 [DEPENDENCIES](DEPENDENCIES.md)。
