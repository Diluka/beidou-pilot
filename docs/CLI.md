# 命令使用

宿主入口为仓库根的 `./beidou-pilot`，精确参数查 `--help`。它只管理工作台、Git 构建输入和 Docker；两个镜像内安装相同的 `beidou-pilot` Python CLI，游戏操作与内置 Lua 不从宿主源码加载。

## 工作台、版本与输出

宿主公共选项放在命令前：`--workbench DIR`、`--instance NAME`、`--backend headless|beidou`、`--ref REF`、`--json`。工作台目录必须已存在；默认实例为 `default`，默认新建后端为 `headless`。GUI 在一个工作台中只使用 `default`，多个工作台分别拥有容器。同一目标同一角色只能有一个控制者。

工作台最少提供 `account.private.json`、`resources.json`，以及需要时的 `target.json`。新建实例默认一次解析 `main` 的已提交 SHA，以该树及固定子模块构建或复用对应后端镜像。显式 `--ref COMMIT` 供开发验收；构建期间代码更新不改变这次输入。已有实例后续命令只路由到所属容器；不会因宿主切换分支或 `main` 更新而换版本。

`build` 只准备镜像，`plan` 只读核对目标，`open` 创建实例并调用容器内 CLI 等待或完成登录。`build/plan/open` 可显式传 `--target PATH`、`--profile PATH`、`--resources PATH`、`--bridge-artifact DIR`、`--workspace-server`、`--timeout SECONDS`；前三个路径默认取工作台中的同名文件，GUI 桥工件目录默认从资源配置的 `gui_dll` 推导。已有实例的 `open` 核对显式请求后继续原会话，不重新构建。

宿主保存 `runtime/INSTANCE/host.json`，每次运行的数据位于其下的独立目录，并挂到容器 `/work`。容器的 `status/instances` 提供源码提交、实际镜像和 `run_id`；原生桥继续核对 `instance_id/run_id`。容器内公共参数 `--root/--backend/--instance` 只用于核对本容器，不能切到其他实例。直接调用可用 `docker exec CONTAINER beidou-pilot --json status`；GUI CLI 入口按客户端用户降权。动作与取消优先使用宿主薄入口以获得定向信号转发。

普通结果为 JSON 信封，含 `ok/command/data`，容器命令另带 `backend/instance`；失败含 `error.code/message/details`。已识别的失败退出码为 2，中断为 130。宿主入口转发命令时使用 JSON；独立 `watch` 输出 JSONL。直接调用容器 CLI 的 `snapshot` 未加 `--json` 时，GUI 使用简洁文本，无头仍为 JSON。

## 启动、观察与关闭

```bash
./beidou-pilot --workbench /external/workbench --backend headless --instance worker-a --json plan
./beidou-pilot --workbench /external/workbench --backend headless --instance worker-a --json open
./beidou-pilot --workbench /external/workbench --instance worker-a --json snapshot
./beidou-pilot --workbench /external/workbench --instance worker-a --json close
```

目标格式见 [target.example.json](../cli/config/target.example.json)。启动器按 Docker Compose 项目/服务、精确应用镜像和 internal 网络核验，不自动启动游戏服务端。常驻工作区目标必须已有授权并显式传 `--workspace-server`；没有 target 文件时，为该实例创建所属 internal 连接，关闭时只回收其所属网络。隔离目标必须显式提供 target，且不能发布宿主端口。

两端共用权限为 `0600` 的 JSON profile：`username`、`password` 和已有角色的 `character_id`（正 32 位有符号整数）必填；`world` 与 `channel` 为 0 基索引，省略时各为 0，格式范围 0 至 255，实际可选范围由服务器和后端决定。游戏中第 1 频道对应 `channel=0`。GUI 当前仅支持 `world=0` 和第 1 至 20 频道，按 CID 选择已有角色。密码不写到参数或日志中，`open` 不自动建角。

启动器在镜像内验证 profile 并准备本次私密快照，将其只读挂到 `/config/account.private.json`；target 只读挂到 `/config/target.json`。容器启动入口生成内部资源映射和 `state/container.json` 后运行原生进程；容器内 `open --profile /config/account.private.json` 完成或确认登录，`--timeout` 只限制入图等待。

已核验目标公告的频道 IPv4 位于 `127.0.0.0/8` 时，无头端以该目标内部 IP 连接频道并保留公告端口；其他地址沿用公告值。该映射不修改服务端或原始资源。

| 命令 | 行为 |
| --- | --- |
| 宿主 `build`、`plan` | 构建/复用版本镜像；只读核对授权目标 |
| `status` | 宿主可报告已停止实例；运行时由容器 CLI 提供实时阶段和版本 |
| `doctor` | 在已有容器内检查资源与读取能力，不创建新客户端 |
| `instances` | 返回当前容器的实例身份与版本 |
| `capabilities` | 读取当前原生动作能力和静态观察支持范围 |
| 宿主 `open`、`close` | 创建或继续所属实例；正常停止、核验退出并回收容器 |
| `snapshot [-i] [--all]` | 当前角色、场景、领域摘要及引用 |
| `inspect KIND [ID]` | 按需领域读数或静态资源 |
| `watch --seconds N --interval N` | 持续只读状态，输出 JSONL |
| `bridge status`、`script status` | 只读原生桥、动作或脚本状态 |

容器在短脚本返回或取消后常驻。宿主 `close` 使用独立生命周期锁，通过 Docker SIGTERM 让镜像内原生进程收尾，再确认 `Running=false/Pid=0`、保存退出日志并回收；活动 Lua 的输入锁不阻挡关闭。直接在容器内执行 `close` 返回 `host_lifecycle_required`，须改用宿主入口。同一实例正在启停时为 `lifecycle_busy`，活动脚本期间其他动作是 `input_busy`。失败先读实例状态和所属运行日志，再决定是否重开。

## 动作与 Lua

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --json walk right --seconds 0.2
./beidou-pilot --workbench /external/workbench --instance worker-a --json script run --code 'game.log("你好，Lua"); game.sleep(0.1)' --seconds 20
./beidou-pilot --workbench /external/workbench --instance worker-a --json script run /scripts/control.lua --seconds 20
./beidou-pilot --workbench /external/workbench --instance worker-a --json script run /scripts/control.lua --continuous
```

| 命令 | 支持与结果边界 |
| --- | --- |
| `walk DIR --seconds N`、`face DIR`、`jump` | 有界方向移动、朝向、跳跃尝试 |
| `attack`、`pickup`、`use_item ID` | 原生尝试；`use_item`不等于消耗和恢复已确认 |
| `revive` | 无头发一次正常复活请求并确认同角色恢复；GUI 使用已识别死亡确认框；存活时跳过 |
| `click REF` | 无头激活当前原生控件或NPC目标引用；GUI保留既有引用与桌面点击流程 |
| `equip ITEM --slot SOURCE --to-slot TARGET [--seconds 3]` | 无头普通装备；明确背包正槽和身上负槽，核对物品 ID 及实际替换结果 |
| `unequip --slot SOURCE --to-slot TARGET [--seconds 3]` | 无头卸下普通装备；明确身上负槽和空背包正槽 |
| `move X`、`climb X --to-y Y`、`portal NAME` | Lua执行同层对齐、单根绳梯或单个门户；不是通用寻路 |
| `fight MOB` | 同层基础Lua策略，支持预算、停级、安全范围、撤退锚点及近距拾取尝试 |
| `hunt [MOB\|all]` | 单场景自主找怪、可达跨平台和连续战斗；支持 `--skill ID`、`--range N`、限时或 `--continuous` |
| `use ITEM --count N`、`--until-hp N`、`--until-mp N` | 核对库存消耗与恢复；计数范围和组合以帮助/实际分类为准 |
| `script run FILE`、`script run --code CODE` | 文件或直接源码二选一，使用同一 Lua 执行链；默认限时，持续模式须明确声明 |
| `task add/replace/stop` | 向指定活动Lua会话管理独立任务，不取得整会话动作锁 |
| `task result REQUEST_ID` | 只读查询已保留的任务管理结果，包括超时后的结果 |
| `stop`、`bridge stop` | 无其他活动动作控制者时清理遗留控制 |
| `key KEYS --seconds N` | 原版按键扩展；无头明确拒绝 |
| `skill ID` | 原生技能请求；无头首批1001004/1001005，其他类型明确不支持 |

`--code` 的值是完整 Lua 源码，按 shell 的引号规则作为一个参数传入；源码以 `--` 注释开头时使用 `--code='-- 注释…'` 的等号形式。CLI 不拼接、展开或改写源码。文件路径按容器内部解析；工作台可选的 `scripts/` 只读挂到 `/scripts`，文件方式每次读取当前 UTF-8 内容。两种方式都可在已运行实例中提交，无需重新构建或重启客户端，沿用相同 `game` API、错误、时限和取消规则。`script status` 不接收文件或 `--code`。源码模式的结果中 `script_file` 为 `null`；日志由原生端写入所属实例桥目录的 `script-events.jsonl`，不作为游戏效果确认。

在已有脚本会话中调整一项任务，先用 `script status` 取得 `script.id` 和该任务的 `revision`，再明确传给任务管理入口：

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --json task add observer \
  --session SCRIPT_ID --priority 0 --code 'while true do game.log("观察中"); game.sleep(1) end'
./beidou-pilot --workbench /external/workbench --instance worker-a --json task replace chase /scripts/chase.lua \
  --session SCRIPT_ID --revision 2 --priority 10
./beidou-pilot --workbench /external/workbench --instance worker-a --json task stop chase \
  --session SCRIPT_ID --revision 3
./beidou-pilot --workbench /external/workbench --instance worker-a --json task result REQUEST_ID
```

新增和替换必须提供 `--priority` 与文件或 `--code`，停止只提供任务名、`--session` 和预期 `--revision`。任务名是1至64字节的非NUL文本，可包含中文和空格；`main` 由整会话入口管理。新增不能复用会话历史中的名称；替换为同名的新版本，分配新的 `revision`，旧版本历史仍可查看。停止已结束的当前版本返回 `changed=false`；旧版本请求被拒绝，不会停止新版本。

任务源码直接作为独立chunk运行，共享本次会话的全局变量和 `game` API，不能访问旧任务的局部变量。动作任务先 `game.acquire()`，取得控制后重新采样与规划；原会话中已有的动作逻辑也需遵守这一多任务约定。替换先编译，编译失败保留旧任务及其输入；编译成功后停止旧版本，确认其输入释放后安装新版本。任一任务运行后的Lua错误继续停止整个会话，不能把替换理解为执行副作用可回滚。

管理结果的 `completed` 表示任务已安装或指定版本已停止并完成其释放确认，实际游戏效果需另行观察；`control_released` 只针对被替换或停止的旧任务，其他任务仍可持有输入。`--timeout` 默认3秒，只限制本次管理等待。

请求发布前，例如等待 `task.lock` 时，Ctrl+C/SIGTERM返回通用 `interrupted` 和退出码130，此时没有已发布的 `request_id`；等待管理锁超时返回 `task_management_busy`。请求发布后，等待结果超时返回 `task_result_unconfirmed`，Ctrl+C/SIGTERM返回 `task_request_interrupted` 和退出码130，这两种结果都保留已发布的 `request_id`。管理等待失败不停止整会话，也不自动重放请求；已发布的请求可用 `task result` 查询最终结果，再决定后续操作。查询结果属于响应中记录的历史实例和会话，不代表当前角色效果。

移动和战斗参数只对当前场景有效。地形与恢复属性优先使用已配置 XML，缺少对应 XML 时使用同源 NX；资料缺失或未支持时明确拒绝。基础 `fight` 保留同层预算与撤退行为；`hunt` 根据当前位置在本场景连续寻找可达目标，允许正常换平台和空中攻击，地图或场景代次变化则停止。两者均保留成长节点限制。

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --json hunt all --seconds 60
./beidou-pilot --workbench /external/workbench --instance worker-a --json hunt 100100 --continuous --hp-item 2000000
./beidou-pilot --workbench /external/workbench --instance worker-a --json hunt all --skill 1001004 --range 60 --seconds 30
```

`hunt` 默认普攻、全部怪物、60秒，`--bounds MIN MAX` 可限定横向区域，`--until-level` 指定停级，`--min-hp-ratio` 默认0.35。`--hp-item` 仅使用明确指定、库存已知的恢复品，不购买或替换药品。技能必须已学且当前后端支持；无头首批仅支持战士 `1001004/1001005`，其他类型明确拒绝。攻击距离是策略接近参数，不保证命中。无可确认的进展、无法通过的地形、生命下限或取消都有明确停止；原始日志保留所属实例，最终经验跨级时不直接相减。

已知近距 `pt7` 脚本门户由原生 Up 输入走正常脚本门户请求，静态目标未知时保留未知，到达以在线地图和位置确认。它不补齐通用路线规划或缺失的静态查询资料。

无头 `use` 接受数字ID的200类药品和201类食品。两端普通200类药品均走Lua原生用药，不要求快捷键绑定；按次数使用可不依赖XML，带HP/MP目标时需要资料已知恢复类型。

无头201类食品不带HP/MP目标时为明确单次消费，仅接受 `--count 1`（默认值），满HP/MP仍会提交一次。它不依赖可选XML；结果 `effect="consumption"`、`effect_confirmed=true` 只表示库存已恰减一。前后HP/MP分别保留，观察到增长时 `recovery_confirmed=true`，否则为 `null`，不能把满血消费说成恢复成功。`healing_metadata_known` 与 `metadata_unavailable` 说明静态恢复资料的已知范围。带HP/MP目标时沿用有界恢复流程，仍需资料已知恢复类型。

`use_item ID` 及 `game.use_item(ID)` 只报告单次原生派发，食品消耗和恢复须由后续观察确认。GUI其他已支持恢复品保留背包工作流；203类传送卷仅支持GUI单次使用，不接受HP/MP目标。

无头 `equip` 要求数字物品 ID、装备背包源正槽和身上目标负槽；Lua 先读取库存，核对该源槽仍是明确指定的物品。目标已有普通装备时，正常替换将其放回源槽。`unequip` 要求明确源负槽和空背包目标正槽。两者通过共享 Lua 发起一次正常装备请求，在无头原生更新中等待源、目的槽位对象变化。`--seconds` 默认3秒，范围为0.001至30秒；超时、取消、接管或换图保持未确认事实，不自动重试，也不撤销已派发请求。随后先读取最新背包和身上槽位，再决定下一步。

CLI 仅在脚本 `status="completed"` 且最终 `action_result.effect="confirmed"` 时返回 `confirmed=true`。脚本正常完成但槽位效果未知时，报 `equipment_change_unconfirmed`，错误详情保留本次结果；`cancelled` 等终态不会被标为确认成功。Python 只负责参数、Lua 装载/取消和终态投影，不轮询执行换装反馈。

原版 `equip ITEM` 保留原有 GUI 工作流，新增原生槽位参数供无头使用；原版不支持 `unequip`。换装只覆盖普通装备，不扩展强化、现金外观或其他装备操作。

`skill` 保留 `native_result`、`dispatched/skill_reason` 和未知效果，顶层 `reason` 继续表达脚本终态。原生数值含义随后端不同：无头枚举0表示准入，GUI保留原返回值，不能仅凭零或非零判断命中。对活动脚本发送原CLI的Ctrl+C/SIGTERM取消并等待放键；不要用第二个动作命令抢占。脚本能力及效果判断见 [CONTROL](CONTROL.md)。

无头 `snapshot` 与 `bridge status` 提供 `dead/revive_requestable`：死亡来自已就绪角色的原生 HP=0；读数不可用时保持未知。`revive_requestable` 只表示客户端请求前置已满足，不能预判事件脚本许可。无头 `revive` 通过共享 Lua 默认等待至多6秒，只有同角色 HP>0 且地图、位置有效才返回 `revived`；存活返回 `already_alive`，均无重复请求。未确认返回 `revive_not_confirmed`，取消/断线保留实际结果；检测到死亡本身不触发复活或重连。参数化等待及脚本用法见 [Lua API](LUA_API.md#无头正常复活)。

## 无头控件交互

先用 `snapshot` 观察 `interaction.page` 的正文和控件，再对选定控件执行一次 `click REF`；场景NPC的原生 `ref` 也使用同一激活入口。`REF` 必须替换为当前观察到的引用：

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --json snapshot
./beidou-pilot --workbench /external/workbench --instance worker-a --json click CONTROL_REF
```

页面只有 `source/title/text/controls`，控件只有 `role/text/enabled/ref`。正文或控件未知时为 `null`，`enabled=null` 不改成 `false`。引用由原生单点生产和验证；CLI不解析引用、不按控件角色拼协议参数，也不自动重新选择或重放失效引用。`--double` 与坐标点击仍仅GUI可用。

激活只报告控件处理或页面变化，不能当作任务完成、奖励或消费到账；随后用当前交互页、`inspect quests`、背包及角色核对。服务端普通脚本页和客户端本地任务页使用同一入口。本地页只显示当前状态能证明的任务条目，先读取真实资料详情，再激活确认控件；无法确认的资格不产生可用确认。缺少 `Quest.nx` 只影响本地任务界面；不根据任务ID制造菜单，不增加直接接交的内容命令。

任务观察已合并完整角色包与本端正常增量，`live_updates=true`，`live_update_kinds` 为 `not_started/started/completed`。原生观察保留原始进度串，关联语义未核实，`linked_progress=null`；不靠重登刷新代替持续观察。

## 原版 GUI

GUI 是独立的完整客户端镜像，包含与无头端相同的 CLI 和 Lua，以及 Wine/VirtualGL 和已核验的桥 DLL。使用工作台的 `resources.json` 配置 `gui_client` 与同源 `headless_resources`。构建需外部 GUI 工件目录中的 `ijl15.dll` 和 `manifest.json`，用 `--bridge-artifact DIR` 显式指定，或从 `gui_dll` 路径推导。启动器核对所选提交的原生构建输入，输入不同须先取得匹配的 Windows 工件，不能给旧 DLL 换版本标签后使用。

```bash
./beidou-pilot --workbench /external/gui-workbench --backend beidou --json build \
  --bridge-artifact /external/agent-bridge
./beidou-pilot --workbench /external/gui-workbench --backend beidou --json open
./beidou-pilot --workbench /external/gui-workbench --json doctor
./beidou-pilot --workbench /external/gui-workbench --json snapshot
./beidou-pilot --workbench /external/gui-workbench --json close
```

[Compose](../docker/compose.yaml) 装配所选版本的 GUI 实例。原客户端只读挂到 `/client`，镜像内的桥位于 `/opt/beidou-pilot/native/ijl15.dll`。容器在 `/work/client` 生成可写运行副本，`Data/` 读取原只读目录，`2ijl15.dll` 图片库仍保留；外部原始文件不被修改。CLI、桌面输入和录制直接使用本容器的桥和显示环境，无 Docker socket。

GUI 容器在自身网络命名空间启用回环游戏端口 NAT，连接已核验目标，不修改服务端公告地址。Wine prefix、运行日志和桥数据位于容器 `/work/runtime/`，由本次工作台运行目录持久化，需允许 `1000:1000` 读写。硬件路径使用 `/dev/dri/renderD128`、`DISPLAY=:97` 的 `1920x1080x24` Xvfb 和窗口管理器、VirtualGL EGL；Wine 虚拟桌面提供原客户端所需显示模式。`WINEDEBUG` 可在启动时设置，日志写入本次运行目录。

构建成功、环境检查和实际入图分别记录；涉及动作时另核对实际游戏结果。GUI 输入仍只允许一名明确操作者。

以下操作不由无头端提供，CLI会明确报不支持：

| 命令组 | 用途 |
| --- | --- |
| `talk TARGET`、`dialog` | 原版已有NPC桌面消费者；无头使用通用控件交互 |
| `ui read/open/close/focus` | 已识别窗口和输入焦点；`ui close all`同时处理普通商店 |
| `equip ITEM` | 正常 GUI 穿戴并核对结果，不接受无头槽位参数 |
| `stats`、`skills` | 正常GUI AP/SP操作，并核对结果 |
| `hotkeys`、`bind`、`press` | 读取、拖放绑定和按已有物品/技能快捷键 |
| `shop read/buy/sell/close` | 普通商店读取与指定买卖；数量框和关店按实际UI收尾 |
| `screenshot [NAME]`、`record NAME` | 当前窗口截图或有界逐帧记录，不发游戏输入 |

引用来自本次快照，换图、对话翻页、重登或目标变化后重新读取。任务/奖励、消费、加点和交易不能因派发成功就重放；以当前完整正文和实际变化判断。GUI输入只允许一名明确操作者。

## 有限批次

`batch [--file PATH]` 接受非空JSON参数数组，先解析全部CLI参数，再顺序执行。禁止嵌套batch，不能切换root、backend或instance。进度写stderr，最终仍是单个JSON；批内watch收为最终状态。

某一步抛错时立即停止，错误详情含从0开始的 `index`、此前 `completed` 和原始 `cause`，不回滚已发生效果。子命令正常返回预算停止或取消状态不会自动终止批次；只批量编排无需中途决策的有限步骤，持续控制写Lua。
