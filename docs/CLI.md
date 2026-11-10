# 命令使用

根入口为 `./cli/beidou-pilot`，支持任意当前目录；精确参数以当前 `--help` 和子命令 `--help` 为准。默认后端是 `beidou`，自动化调用应显式选端和使用 `--json`。

## 实例与输出

公共选项可以放在命令前后：`--backend beidou|headless`、`--instance NAME`、`--root PATH`、`--json`、`--debug`。`--root` 指定运行目录，不改变当前加载的代码与内置 Lua 来源。

命名实例只支持无头端，省略为 `default`；名字为1至48位小写字母、数字、下划线或连字符，首位为字母或数字。GUI只使用默认单实例。每个无头实例独立持有容器、登记、日志和桥目录，同一目标同一角色只能由一个实例接管。

普通成功结果为单个 JSON，包含 `ok/command/backend/instance/data`。失败对象包含 `error.code/message/details`；显式 `--json` 时错误也写 stdout，否则写 stderr。已识别的失败退出码为2，中断为130，正常返回为0。独立 `watch` 输出 JSONL；原版 `snapshot` 无 `--json` 时为简洁文本，无头 `snapshot` 仍为 JSON。

## 启动、观察与关闭

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json open \
  --target /external/target.json --profile /private/account.private.json
./cli/beidou-pilot --backend headless --instance worker-a --json snapshot
./cli/beidou-pilot --backend headless --instance worker-a --json close
```

无头新实例必须显式给出 target 与权限0600的 profile；已有匹配实例可 `open` 复用。target 格式见 [target.example.json](../cli/config/target.example.json)，当前按 Docker Compose 项目/服务、精确应用镜像和 internal 网络核验，不自动启动游戏服务端。

已核验目标公告的频道 IPv4 位于 `127.0.0.0/8` 时，无头客户端使用该目标的内部 IP 连接频道，并保留服务器公告的端口。其他频道地址沿用公告值。该映射只发生在无头频道连接阶段，不需要修改服务端、原客户端资源或容器网络权限；目标核验失败时仍拒绝启动。

profile 需 `username/password/character_id`，可选 `world/channel` 为0基索引。角色必须已经存在，不自动创建。账号文件外置，密码不写到参数中。无头选角与频道来自 profile，不接受 GUI 的 `--character/--character-index/--channel` 选项；旧 `max_seconds` 进程期限字段明确拒绝。`--timeout`只限制启动等待。

GUI `open` 使用普通登录、选频道和选角，可按 `--channel`、`--character` 或 `--character-index` 选择已有角色。它需要已准备的 GUI 运行环境，默认目标配置不代表已获准操作任意服务。

| 命令 | 行为 |
| --- | --- |
| `status`、`doctor` | 读取阶段或检查环境，不启动客户端 |
| `instances` | 列出当前根目录已登记的无头实例 |
| `capabilities` | 在线读取实际原生动作能力；离线 `native_actions=null`，仍列静态观察域 |
| `open`、`close` | 创建/复用实例；正常停止、核验退出并回收实例 |
| `snapshot [-i] [--all]` | 当前角色、场景、领域摘要及引用；`-i`省略怪物行，`--all`包含画外实体 |
| `inspect KIND [ID]` | 领域读数或静态资源，KIND见帮助 |
| `watch --seconds N --interval N` | 持续只读状态，独立调用为JSONL |
| `bridge status`、`script status` | 原生桥、动作或脚本状态，只读 |

容器在命令结束后常驻。短脚本返回或取消不会关闭客户端；无头 `close` 可关闭正在执行 Lua 的实例。关闭使用独立生命周期锁；同一实例正在启停时为 `lifecycle_busy`，活动脚本期间其他动作是 `input_busy`。退出状态保留 `run_dir/exit_code/stop_reason`。失败后先读取原因和实际状态，再决定重开。

## 动作与 Lua

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json walk right --seconds 0.2
./cli/beidou-pilot --backend headless --instance worker-a --json script run --code 'game.log("你好，Lua"); game.sleep(0.1)' --seconds 20
./cli/beidou-pilot --backend headless --instance worker-a --json script run /path/control.lua --seconds 20
./cli/beidou-pilot --backend headless --instance worker-a --json script run /path/control.lua --continuous
```

| 命令 | 支持与结果边界 |
| --- | --- |
| `walk DIR --seconds N`、`face DIR`、`jump` | 有界方向移动、朝向、跳跃尝试 |
| `attack`、`pickup`、`use_item ID` | 原生尝试；`use_item`不等于消耗和恢复已确认 |
| `revive` | 无头发一次正常复活请求并确认同角色恢复；GUI 使用已识别死亡确认框；存活时跳过 |
| `equip ITEM --slot SOURCE --to-slot TARGET [--seconds 3]` | 无头普通装备；明确背包正槽和身上负槽，核对物品 ID 及实际替换结果 |
| `unequip --slot SOURCE --to-slot TARGET [--seconds 3]` | 无头卸下普通装备；明确身上负槽和空背包正槽 |
| `move X`、`climb X --to-y Y`、`portal NAME` | Lua执行同层对齐、单根绳梯或单个门户；不是通用寻路 |
| `fight MOB` | 同层基础Lua策略，支持预算、停级、安全范围、撤退锚点及近距拾取尝试 |
| `use ITEM --count N`、`--until-hp N`、`--until-mp N` | 核对库存消耗与恢复；计数范围和组合以帮助/实际分类为准 |
| `script run FILE`、`script run --code CODE` | 文件或直接源码二选一，使用同一 Lua 执行链；默认限时，持续模式须明确声明 |
| `task add/replace/stop` | 向指定活动Lua会话管理独立任务，不取得整会话动作锁 |
| `task result REQUEST_ID` | 只读查询已保留的任务管理结果，包括超时后的结果 |
| `stop`、`bridge stop` | 无其他活动动作控制者时清理遗留控制 |
| `key KEYS --seconds N`、`skill ID` | 原版专属Lua扩展；无头明确拒绝 |

`--code` 的值是完整 Lua 源码，按 shell 的引号规则作为一个参数传入；源码以 `--` 注释开头时使用 `--code='-- 注释…'` 的等号形式。CLI 不拼接、展开或改写源码。文件方式每次读取当前 UTF-8 内容。两种方式都可在已运行实例中提交，无需重新构建或重启客户端，沿用相同 `game` API、错误、时限和取消规则。`script status` 不接收文件或 `--code`。源码模式的结果中 `script_file` 为 `null`；日志由原生端写入所属实例桥目录的 `script-events.jsonl`，不作为游戏效果确认。

在已有脚本会话中调整一项任务，先用 `script status` 取得 `script.id` 和该任务的 `revision`，再明确传给任务管理入口：

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json task add observer \
  --session SCRIPT_ID --priority 0 --code 'while true do game.log("观察中"); game.sleep(1) end'
./cli/beidou-pilot --backend headless --instance worker-a --json task replace chase /path/chase.lua \
  --session SCRIPT_ID --revision 2 --priority 10
./cli/beidou-pilot --backend headless --instance worker-a --json task stop chase \
  --session SCRIPT_ID --revision 3
./cli/beidou-pilot --backend headless --instance worker-a --json task result REQUEST_ID
```

新增和替换必须提供 `--priority` 与文件或 `--code`，停止只提供任务名、`--session` 和预期 `--revision`。任务名是1至64字节的非NUL文本，可包含中文和空格；`main` 由整会话入口管理。新增不能复用会话历史中的名称；替换为同名的新版本，分配新的 `revision`，旧版本历史仍可查看。停止已结束的当前版本返回 `changed=false`；旧版本请求被拒绝，不会停止新版本。

任务源码直接作为独立chunk运行，共享本次会话的全局变量和 `game` API，不能访问旧任务的局部变量。动作任务先 `game.acquire()`，取得控制后重新采样与规划；原会话中已有的动作逻辑也需遵守这一多任务约定。替换先编译，编译失败保留旧任务及其输入；编译成功后停止旧版本，确认其输入释放后安装新版本。任一任务运行后的Lua错误继续停止整个会话，不能把替换理解为执行副作用可回滚。

管理结果的 `completed` 表示任务已安装或指定版本已停止并完成其释放确认，实际游戏效果需另行观察；`control_released` 只针对被替换或停止的旧任务，其他任务仍可持有输入。`--timeout` 默认3秒，只限制本次管理等待。

请求发布前，例如等待 `task.lock` 时，Ctrl+C/SIGTERM返回通用 `interrupted` 和退出码130，此时没有已发布的 `request_id`；等待管理锁超时返回 `task_management_busy`。请求发布后，等待结果超时返回 `task_result_unconfirmed`，Ctrl+C/SIGTERM返回 `task_request_interrupted` 和退出码130，这两种结果都保留已发布的 `request_id`。管理等待失败不停止整会话，也不自动重放请求；已发布的请求可用 `task result` 查询最终结果，再决定后续操作。查询结果属于响应中记录的历史实例和会话，不代表当前角色效果。

移动和战斗参数只对当前场景有效。门户和部分规划依赖可选静态 WZ XML，资料不足时明确拒绝；换层、身份变化、低HP或未确认到达会停止后续动作。基础 `fight` 受转职节点限制，特殊任务、材料或职业技能策略应自行写Lua，没有未实现的占位选项。

无头 `use` 接受数字ID的200类药品和201类食品。两端普通200类药品均走Lua原生用药，不要求快捷键绑定；按次数使用可不依赖XML，带HP/MP目标时需要资料已知恢复类型。

无头201类食品不带HP/MP目标时为明确单次消费，仅接受 `--count 1`（默认值），满HP/MP仍会提交一次。它不依赖可选XML；结果 `effect="consumption"`、`effect_confirmed=true` 只表示库存已恰减一。前后HP/MP分别保留，观察到增长时 `recovery_confirmed=true`，否则为 `null`，不能把满血消费说成恢复成功。`healing_metadata_known` 与 `metadata_unavailable` 说明静态恢复资料的已知范围。带HP/MP目标时沿用有界恢复流程，仍需资料已知恢复类型。

`use_item ID` 及 `game.use_item(ID)` 只报告单次原生派发，食品消耗和恢复须由后续观察确认。GUI其他已支持恢复品保留背包工作流；203类传送卷仅支持GUI单次使用，不接受HP/MP目标。

无头 `equip` 要求数字物品 ID、装备背包源正槽和身上目标负槽；Lua 先读取库存，核对该源槽仍是明确指定的物品。目标已有普通装备时，正常替换将其放回源槽。`unequip` 要求明确源负槽和空背包目标正槽。两者通过共享 Lua 发起一次正常装备请求，在无头原生更新中等待源、目的槽位对象变化。`--seconds` 默认3秒，范围为0.001至30秒；超时、取消、接管或换图保持未确认事实，不自动重试，也不撤销已派发请求。随后先读取最新背包和身上槽位，再决定下一步。

CLI 仅在脚本 `status="completed"` 且最终 `action_result.effect="confirmed"` 时返回 `confirmed=true`。脚本正常完成但槽位效果未知时，报 `equipment_change_unconfirmed`，错误详情保留本次结果；`cancelled` 等终态不会被标为确认成功。Python 只负责参数、Lua 装载/取消和终态投影，不轮询执行换装反馈。

原版 `equip ITEM` 保留原有 GUI 工作流，新增原生槽位参数供无头使用；原版不支持 `unequip`。换装只覆盖普通装备，不扩展强化、现金外观或其他装备操作。

`skill`返回 `native_result`：0为本地拒绝，非零不能证明命中或服务器确认。对活动脚本发送原CLI的Ctrl+C/SIGTERM取消并等待放键；不要用第二个动作命令抢占。脚本能力及效果判断见 [CONTROL](CONTROL.md)。

无头 `snapshot` 与 `bridge status` 提供 `dead/revive_requestable`：死亡来自已就绪角色的原生 HP=0；读数不可用时保持未知。`revive_requestable` 只表示客户端请求前置已满足，不能预判事件脚本许可。无头 `revive` 通过共享 Lua 默认等待至多6秒，只有同角色 HP>0 且地图、位置有效才返回 `revived`；存活返回 `already_alive`，均无重复请求。未确认返回 `revive_not_confirmed`，取消/断线保留实际结果；检测到死亡本身不触发复活或重连。参数化等待及脚本用法见 [Lua API](LUA_API.md#无头正常复活)。

## 原版 GUI

从项目根构建独立 GUI 镜像：

```bash
docker build -t local/beidou-v17-client:intel docker/gui
```

在 `cli/config/resources.json` 配置 `gui_client` 为匹配 V17 的原客户端目录、`gui_dll` 为已构建的桥接 DLL；配置文件和原资源均不入库。默认镜像名为 `local/beidou-v17-client:intel`，可用 `CLIENT_IMAGE` 选择已准备的 GUI 镜像。把对应工件的 `manifest.json` 复制到 `cli/state/agent-bridge-build.json`，供 EXE、`2ijl15.dll` 与桥接 DLL 的版本核验；桥 DLL 继续从 `gui_dll` 指定的外部位置读取。

CLI 使用 [Compose](../docker/compose.yaml) 的 `client` 服务，并从资源配置和已核验 target 注入客户端路径、目标网络及本次 `RUN_ID`。原客户端只读挂到 `/client`，选定 DLL 只读挂到 `/overrides/ijl15.dll`；容器内 `/work/client` 是可写运行副本，其中 `Data/` 继续读取只读源，外部 `ijl15.dll` 不被覆盖。`2ijl15.dll` 仍需保留。

GUI 容器在自己的网络命名空间启用 `net.ipv4.conf.all.route_localnet=1`，让原客户端访问 `127.0.0.1` 的游戏端口时，经既有 DNAT/MASQUERADE 连接已核验目标；目标地址与端口过滤仍由容器入口配置。

Wine prefix、运行日志、桥数据分别位于 `cli/runtime/prefix`、`cli/runtime/runs`、`cli/runtime/bridge`。容器内 GUI 进程使用 `1000:1000`，这些目录须允许该身份读写。当前硬件路径需要 `/dev/dri/renderD128`，画面由容器内 `DISPLAY=:97` 的 `1920x1080x24` Xvfb 和窗口管理器提供，VirtualGL 使用 EGL 渲染。游戏通过 `wine explorer /desktop=beidou,1920x1080 BeiDou.exe` 在标准 Wine 虚拟桌面中启动，由虚拟桌面提供客户端初始化所需的 `1280×720@60Hz` 等兼容显示模式。

需要 Wine 启动诊断时，可在启动命令前设置 `WINEDEBUG='+loaddll,+seh,+d3d8,+d3d'`；该值传入容器并在降权后保留，未指定时默认为 `-all`。日志写入所属运行目录的 `wine.log`，原始诊断保留在本地环境。

准备权限为 `0600` 的 `cli/account.private.json`（含 `name`、`password`），以及已授权的隔离 target 和专用角色，然后使用统一入口：

```bash
./cli/beidou-pilot --backend beidou --json doctor
./cli/beidou-pilot --backend beidou --json open --target /external/target.json
./cli/beidou-pilot --backend beidou --json snapshot
./cli/beidou-pilot --backend beidou --json close
```

构建成功、环境检查通过和实际登录入图分别记录；涉及观察或动作时，还需核对对应的游戏结果。GUI 输入只允许一名明确操作者。

以下操作不由无头端提供，CLI会明确报不支持：

| 命令组 | 用途 |
| --- | --- |
| `talk TARGET`、`dialog`、`click REF` | 打开NPC对话、按当前正文选择、操作当前引用 |
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
