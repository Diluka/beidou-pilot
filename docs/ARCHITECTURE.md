# 架构与支持范围

## 代码职责

| 位置 | 职责 |
| --- | --- |
| `cli/beidou-pilot`、`cli/beidou_pilot/` | CLI、实例生命周期、原生观察投影、参数和结果边界 |
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

Codex app-server 在独立 harness 容器中运行，宿主薄控制器分派少量动态游戏工具并调用固定 root/backend/instance 的 CLI。模型容器不挂开发仓库、宿主 Codex 配置或 Docker socket。客户端和 harness 各有生命周期；暂停或停止玩法需取消原 Lua CLI 并确认所属实例放键，停止 harness 不关闭客户端。具体配置与协作入口见 [HARNESS](HARNESS.md)。

## 容器与控制生命周期

每个命名无头实例是一个后台 Docker 容器，拥有独立登记、运行日志、桥目录和控制锁。`open` 创建或复用实例并等待实际入图；Lua 返回或取消后容器继续运行。`close` 经 Docker 正常停止、核验退出并回收容器，允许关闭正在运行 Lua 的实例。

容器启停与动作输入使用独立的锁。一个实例的 Lua、取消或关闭不向另一实例派发控制；同一目标的同一角色禁止被多个实例同时接管。真实断线或原生错误保留退出事实，不自动重连、重放或把旧动作转交新进程。

[无头 Dockerfile](../docker/headless/Dockerfile) 是无头镜像唯一构建入口，builder 内完成编译，运行层执行原生客户端主进程并接收 SIGTERM。[GUI Dockerfile](../docker/gui/Dockerfile) 构建独立 Wine/VirtualGL 环境，[Compose](../docker/compose.yaml) 定义 GUI 的资源挂载、设备和网络。两端构建定义与 GUI 启动脚本统一放在 `docker/`；根 `.dockerignore` 对应无头镜像使用的项目根构建上下文。CLI 负责目标与实例核验、Docker 调用和桥控制，不启动宿主游戏进程。

## 外部资源与配置

游戏资源不随源码或镜像分发。无头端当前读取由外部北斗 `Data/` 转换的 metadata-only NX；保留玩法所需属性、帧时序和几何数据，没有可绘制像素或可播放音频。

转换时显式指定外部客户端，输出必须位于原资源目录之外：

```bash
python3 headless/tools/prepare_resources.py \
  --client-root /external/BeiDou-Client \
  --output /external/headless-nx
./headless/agent check /external/headless-nx
```

转换工具需要本机 C++17 编译器；已有 NX 时无需转换。资源检查使用无网络的短时 Docker 容器，不登录游戏。

资源配置入口是 `cli/config/resources.json`，可用 `MAPLE_RESOURCES_CONFIG` 指向另一份文件；相对路径按配置文件目录解析。字段含义如下：

| 字段 | 用途 |
| --- | --- |
| `headless_resources` | 外部 NX 目录，只读挂载到无头容器 `/data`，可由多个实例共享 |
| `metadata_root` | 可选 WZ XML，用于名称、物品分类及地形规划；缺失资料保留未知 |
| `gui_client` | 匹配 V17 的外部原客户端目录，只读挂载到 GUI 容器 `/client` |
| `gui_dll` | 已构建的桥接 `ijl15.dll`，只读挂载到 GUI 容器 `/overrides/ijl15.dll` |

未配置时只使用本项目默认目录，不自动搜索其他工作区。资源路径配置不含账号且不入库。每实例的私密 profile 单独只读挂载，桥目录独立可写；target 和 profile 的字段及入口见 [CLI](CLI.md)。

原版 GUI 在容器私有目录 `/work/client` 组装运行副本：复制原客户端的运行文件，`Data/` 链接到只读 `/client/Data`，再用选定的 `gui_dll` 替换运行副本中的 `ijl15.dll`。原客户端目录保持只读，不能用硬链接或可写链接替代独立运行文件。图片库 `2ijl15.dll` 仍是桥接 DLL 的运行依赖，必须保留。

Wine prefix、日志与桥目录分别外置到 `cli/runtime/prefix`、`cli/runtime/runs`、`cli/runtime/bridge`，这些目录需要允许容器内 `1000:1000` 读写。GUI 使用 `DISPLAY=:97` 的 Xvfb/窗口管理器、VirtualGL EGL 和 `/dev/dri/renderD128`；硬件与真实游戏效果分别验收。CLI 从同一份资源配置取得挂载路径并核验 EXE、图片库和所选 DLL，桥构建清单登记在 `cli/state/agent-bridge-build.json`。

DLL 构建仍需 Windows/MSVC、SDK 及匹配 Detours 库；这些材料不由客户端运行镜像提供。GUI 准备和统一 CLI 操作见 [CLI](CLI.md#原版-gui)。

## 两端能力

| 能力 | 北斗 GUI | 无头端 |
| --- | --- | --- |
| 已有角色登录、退出、状态与实例管理 | 默认单实例；普通 GUI 登录 | 命名多实例；profile 指定已有角色 |
| 阶段、角色、场景、背包、装备、金币与技能记录 | 原生观察 | 原生对象观察；读取技能不代表可执行技能 |
| 任务观察 | 当前原生任务对象 | 角色完整包快照，`live_updates=false`，无实时增量 |
| 移动、朝向、跳跃、普攻、近距拾取、停止 | 共同 Lua 语义 | 共同 Lua 语义 |
| 用药 | `use_item` 需已有绑定；`use` 可按条件使用 GUI | 普通 200 类 HP/MP 药剂；按次数使用可不依赖 XML |
| 同层移动、爬绳、单个门户、基础战斗 | 内置 Lua | 内置 Lua；受自身物理及资源支持范围约束 |
| 原始按键、直接技能调用 | 原版扩展 | 不支持 |
| NPC 对话、窗口、快捷键、加点、装备操作、商店、复活 | 既有 GUI 工作流 | 不支持 |
| 截图、录制 | 当前游戏窗口采集 | 不提供画面 |

支持范围以 `capabilities`、领域响应及当前命令实际结果为准。缺能力明确拒绝，未知值不能按零、关闭、不可见或空集合处理，也不从服务端后台或另一客户端补齐。

上表中的原生观察、CLI 工作流与 Lua 接口是不同的支持面。CLI 已能查询某个领域，不表示 `game.state()` 已包含它；GUI 已有对话、交易或养成流程，也不表示无头或 Lua 已提供相同语义操作。Lua 的实际消费范围及前置条件以 [Lua API](LUA_API.md) 为准。

会增加操作成本的现有边界及后续独立用户结果见[客户端能力边界与缺口索引](CLIENT_LIMITATIONS.md)。其中资源准备、目标交互、连续路线与结果反馈分别跟踪；入池不改变当前能力声明，也不表示需要先完成全部能力才可继续有界玩法。

无头端尚有其他玩家出现封包的解析缺口，scene 目前不提供其他玩家列表。当前基础战斗和有限移动不等于通用寻路、全职业或完整自主日程；两端物理与技能效果不承诺精确等价。同服多账号容量和长期压力需要单独验证。

## 验证与源码交付

离线合同、镜像构建和实际游戏结果分别判断。IPC 对端测试只能证明请求/取消契约，不能证明命中、掉落、存档或长期稳定性。实际玩法使用授权专用角色和隔离目标，退出后核对所属资源及必要存档。

源码导出使用 `python3 cli/tools/export_prototype.py --output 新目录`，目标目录须不存在。工具按白名单生成源码及校验清单，展开构建所需依赖，不携带 Git 元数据、账号、运行状态、游戏资源或安装器。依赖来源和更新规则见 [DEPENDENCIES](DEPENDENCIES.md)。
