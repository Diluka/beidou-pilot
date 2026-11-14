# 业务地图

这套地图面向操作者、Lua 策略作者、游戏 AI 接入者和客户端维护者，按当前实现承担的业务责任组织。每个领域的 YAML 定义一个独立领域根，八份文件共同组成一张 Semantic Atlas 图；跨领域共享概念只在拥有方定义一次。

地图提供业务导航和调查线索。行为判断仍需回到锚点所指的当前源码、测试及正式文档；这里不记录账号、角色运行数据或实际游戏验收结论。

## 领域与责任

| 领域 | 受益者与可依赖的结果 | 拥有的决定及生命周期 | 地图 |
| --- | --- | --- | --- |
| 客户端会话与实例 | 操作者连接已核验目标的已有角色，并只关闭所属实例 | 目标/profile 核验、实例登记及身份；新建或匹配复用、入图等待、持续运行、关闭与退出归档 | [client-session.yaml](client-session.yaml) |
| 外部资源与静态资料 | 维护者准备客户端输入，消费者查询已知名称、物品和地形 | 外部资源路径、共享 IMG 解析、原件只读、GUI 运行副本与静态资料缺失语义 | [game-resources.yaml](game-resources.yaml) |
| 游戏事实观察 | 操作者和 AI 读取带来源、身份及时效的本端事实 | 原生领域请求、能力声明、快照及短引用；取样、不可用/不支持、过期与上下文变化 | [game-observation.yaml](game-observation.yaml) |
| Lua 脚本执行 | 策略作者运行、观察和取消指定实例中的 tick 脚本 | 会话、档位调度与输入所有权；装载、等待、取消、终态及真实放键 | [script-execution.yaml](script-execution.yaml) |
| 动作意图与效果确认 | 脚本作者通过 tick Lua 提交方向与动作意图并核对结果 | 共享 player、单动作槽、运动观察、所属输入释放与效果边界；不提供寻路或内置打法 | [field-play.yaml](field-play.yaml) |
| 世界交互与交易 | 操作者处理当前 NPC 正文和普通商店买卖 | 对话选择、当前窗口上下文、报价与交易结果核对；打开、推进、需决策时停下、买卖及关闭 | [world-interaction.yaml](world-interaction.yaml) |
| 角色维护 | 操作者在原版 GUI 中换装、复活并配置快捷键 | 每项变更的前提与结果确认；GUI 专属支持范围，无 AP/SP 自动分配或药品命令 | [character-care.yaml](character-care.yaml) |
| 游戏 AI 决策与协作 | 操作者维持独立游戏 AI 会话，并随时调整或暂停模型决策 | 模型会话、角色指令、当前目标与私密经历记录；建立/续接、观察决策、询问、暂停/恢复及停止 | [game-ai.yaml](game-ai.yaml) |

GUI 与无头是各领域的实现及支持面。Lua 执行管理通用控制生命周期，动作领域决定意图与效果边界；世界交互处理当前正文与交易，角色维护决定特定角色变更的确认方式。独立 harness 消费客户端能力，保留自身模型会话与协作状态。

游戏服务器拥有真实游戏状态和不可逆结果，服务端与数据库业务由游戏服务器承担。Docker、Codex app-server、外部原客户端及第三方引擎是协作者；图中只描述本仓库可证实的集成责任。

## 从使用场景检查覆盖

下面从公开入口和状态变更出发检查覆盖，完整性按业务责任核对。

| 场景或生命周期责任 | 归属与关键源码 | 地图表达或范围说明 |
| --- | --- | --- |
| 按实例名新建、复用或拒绝不匹配角色 | 客户端会话；[headless.py](../../cli/beidou_pilot/headless.py)、[session.py](../../cli/beidou_pilot/session.py) | 打开场景；GUI 默认单实例、无头命名实例，保留目标核验与角色排他规则 |
| 活动 Lua 期间关闭、保存退出原因 | 客户端会话；[headless.py](../../cli/beidou_pilot/headless.py)、[instances.py](../../cli/beidou_pilot/instances.py) | 独立关闭场景；Lua 结束时容器继续运行，GUI 网络清理按当前实现跟踪 |
| 配置、只读核验原版 IMG 与装配 GUI 副本 | 外部资源；[架构资源说明](../ARCHITECTURE.md#外部资源与配置)、[prepare-client.sh](../../docker/gui/prepare-client.sh) | 运行时资源读取和运行副本操作；原件保持只读 |
| 名称、NPC 点击范围、地形和物品恢复类型查询 | 外部资源；[catalog.py](../../cli/beidou_pilot/catalog.py) | 静态查询和资料数据；缺资料保持未知，实时对象以现场观察为准 |
| 查询本端领域、能力、快照及持续观察 | 游戏事实观察；[observations.py](../../cli/beidou_pilot/observations.py)、[snapshot.py](../../cli/beidou_pilot/snapshot.py)、[cli.py](../../cli/beidou_pilot/cli.py) | 观察操作和快照流程；无头任务仅登录快照，CLI 观察面与 Lua 状态面分别判断 |
| tick 文件运行、会话状态查询与取消 | Lua 执行；[bridge.py](../../cli/beidou_pilot/bridge.py)、[cli.py](../../cli/beidou_pilot/cli.py)、[TickRuntime.cpp](../../shared/lua-runtime/TickRuntime.cpp) | 执行与取消流程；按 script.id 定位会话，等待失败时按现状继续 |
| 取消、期限到达、错误及输入释放 | Lua 执行；[TickRuntime.h](../../shared/lua-runtime/TickRuntime.h)、[TickRuntime.cpp](../../shared/lua-runtime/TickRuntime.cpp) | 所有权和效果边界；会话取消、容器关闭分别拥有生命周期 |
| 方向与动作意图提交及运动观察 | 动作领域；[LUA_TICK_API.md](../LUA_TICK_API.md)、[shared/scripts/examples](../../shared/scripts/examples/) | 共享 player 与单动作槽；派发、动画与游戏效果分别判断 |
| 打开 NPC、推进对话、当前引用操作和窗口焦点 | 世界交互；[dialogs.py](../../cli/beidou_pilot/dialogs.py)、[ui.py](../../cli/beidou_pilot/ui.py) | 当前上下文与对话流程；任务、奖励与文本输入的选择由操作者确认 |
| 买卖、数量框和关店 | 世界交互；[shop.py](../../cli/beidou_pilot/shop.py) | 普通交易和关闭流程；库存与金币双确认，未确认时先观察 |
| GUI 背包换装、复活与快捷键绑定 | 角色维护；[items.py](../../cli/beidou_pilot/items.py)、[hotkeys.py](../../cli/beidou_pilot/hotkeys.py)、[cli.py](../../cli/beidou_pilot/cli.py) | GUI 操作与结果确认；无头明确拒绝，Lua 不提供窗口动作 |
| tick 动作槽中的技能与用药意图 | 动作领域；[LUA_TICK_API.md](../LUA_TICK_API.md)、[TickRuntime.cpp](../../shared/lua-runtime/TickRuntime.cpp) | 只提交持续输入意图；消耗、恢复与命中由现场观察确认 |
| 独立模型会话、目标调整、询问回答、暂停和停止 | 游戏 AI；[controller.py](../../harness/beidou_game_ai/controller.py)、[client.py](../../harness/beidou_game_ai/client.py) | 三个主要流程；固定客户端绑定，客户端开关由统一入口管理，长期记忆以私密经历记录为准 |
| 有限命令批次 | 既有领域入口；[cli.py](../../cli/beidou_pilot/cli.py) | 批次是同实例的有限编排，遇错即停；按键与技能命令已退役，动作写 tick Lua |
| 截图及有界录制 | 观察支持；[desktop.py](../../cli/beidou_pilot/engines/desktop.py)、[record.py](../../cli/beidou_pilot/engines/record.py) | GUI 画面证据，无头端按结构化观察交付 |
| 镜像构建、CI 和依赖维护 | 工程交付支持；[workbench](../../private/workbenches/workbench)、[CI.md](../CI.md)、[DEPENDENCIES.md](../DEPENDENCIES.md) | 工程交付支持，游戏结果由各业务领域负责；客户端交付统一经版本化镜像入口 |

## 阅读与查询

从仓库根运行已安装的 Semantic Atlas CLI：

```bash
semantic-atlas search "取消脚本并确认释放输入" --repo "$PWD"
semantic-atlas context script-execution --repo "$PWD"
semantic-atlas context world-interaction --repo "$PWD"
semantic-atlas validate --repo "$PWD"
semantic-atlas web --repo "$PWD" --no-open
```

`search` 返回候选概念；按业务含义选择稳定 ID 后用 `context` 查看所属领域、协作者、源码锚点及相关分支流程。Viewer 按领域根切换，并保留跨文件的外域邻居。查看命令输出的本地地址即可打开交互地图。

需要独立 HTML 时，按开发目录约定将产物放入忽略的任务目录：

```bash
mkdir -p tmp/business-map/artifacts
semantic-atlas render --repo "$PWD" \
  --output "$PWD/tmp/business-map/artifacts/business-map.html"
```

## 维护边界

- 依据当前源码、合同测试和正式文档维护，功能状态以已交付实现为准。新增独立责任再增加领域；同一责任下的细化使用能力、场景和操作。
- 关系在 `from` 节点所属文件维护，流程与所属场景同文件；概念 ID 跨文件唯一，业务身份未变时保留 ID。
- 操作优先绑定 `file` 与已核实的函数/方法名；数据和长期规则使用文件或文档锚点。路径和符号是导航线索，修改前以当前实现为准。
- 改动后校验完整图并检查对应 Viewer 领域和流程，同时复核本页的场景覆盖。结构合法性与业务结论准确性分别审查。
- 支持矩阵和未知语义以 [ARCHITECTURE.md](../ARCHITECTURE.md)、[CLI.md](../CLI.md)、[LUA_API.md](../LUA_API.md)、[CONTROL.md](../CONTROL.md) 及当前 `capabilities` 为准；tick 示例遵循 [shared/scripts/AGENTS.md](../../shared/scripts/AGENTS.md)。
- 地图只记录已核实事实；真实游戏、资源转换与模型试用的结论由对应验收记录提供。纯文档维护按仓库简易流程交付，游戏效果以真实试用为准。
