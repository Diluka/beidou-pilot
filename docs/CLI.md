# 命令使用

宿主使用 [workbench](../workbenches/workbench)；从仓库根调用 `workbenches/workbench live/NAME COMMAND` 或 `workbenches/workbench dev/NAME COMMAND`。`NAME` 是分区内已准备的角色目录名，不传任意宿主路径。两个客户端镜像内都使用 `beidou-pilot`。

## 工作目录配置

角色目录在主检出的 `private/workbenches/{live,dev}/NAME/`。`account.json`、可选 `workbench.json`、`scripts/` 和运行数据归该角色。常驻角色在 `PLAN.md` 接续养成；开发角色在 `STATE.md` 记录可复现条件及最近核验。

共享资源在主检出的 `private/workbenches/config/resources.json`，常驻与开发目标分别在同目录的 `live.server.json` 和 `dev.server.json`。分区决定目标，角色配置不能覆盖；目标缺失或不匹配时不改连另一服。部署步骤、开发服环境文件及公开示例见[工作台指南](../workbenches/README.md)。

`workbench.json` 可省略，默认使用 headless、main 和90秒入图等待。GUI 目录的最小 [配置示例](../workbenches/examples/workbench.example.json) 为：

```json
{"backend":"beidou"}
```

| 设置 | 默认及用途 |
| --- | --- |
| `backend` | `headless`；可选 `headless` 或 `beidou` |
| `ref` | `main`；开发验收可明确指定已提交版本 |
| `timeout` | `90`；5至180的数值，仅限制入图等待 |
| `bridge_artifact` | 可选的匹配 GUI 桥工件目录；相对路径按工作目录解析，省略时经 `gh` 获取相应提交成功 CI 的工件 |
| `cache_dir` | 可选；须位于所属角色目录内的宿主绝对路径，默认 `<workbench>/cache`，读写挂载到容器内固定 `/cache`（客户端进程 `BEIDOU_CACHE_DIR=/cache`），保存版本化原生世界地图缓存 |

开发调试或复现选 `dev/NAME`。用 `server dev status` 核对开发服，需要时显式 `server dev up`。通过 `server dev cli` 使用该服实际提供的命令准备账号、角色和场景条件，再从目标客户端核对。`server dev stop` 保留数据，不重置开发服；常驻服不提供此管理入口，不能用于准备开发样本。

启动设置仅在新建时读取。一个目录对应一个账号角色和容器，宿主实例名固定为 `default`；原生 `instance_id/run_id` 核验继续保留。已有容器的 `status/script/close` 依赖目录下的运行登记和实际容器，新建配置修改后新实例再按新版本构建。

## 版本、挂载与输出

客户端镜像按 `workbench.json.ref`（默认 `main`）的已提交 SHA 及固定子模块构建或复用；GUI 运行时装配使用当前宿主启动器配套的 Compose。已有实例继续运行启动时的 CLI、内置 Lua 和原生组件，实际版本查 `status` 的 `source_revision/image/run_id`。

`build` 保留 `data.image/source_revision/backend`，并在 `data.preparation` 中报告实际执行的准备阶段：

| 阶段 | 可核对的结果 |
| --- | --- |
| `context` | 源码上下文新建或复用，固定提交、源码树及子模块提交 |
| `bridge`（GUI） | CI 下载、已有工件或镜像内清单的来源；直接附带原有 manifest 中的目标指纹、桥指纹、依赖和工具链 |
| `client_image` | 客户端镜像新建或复用，实际标签和镜像 ID |

每个阶段包含 `outcome` 和 `duration_ms`。耗时是本次阶段的实际用时，镜像构建内部的层缓存仍由 Docker 构建日志说明。准备失败保留既有错误码，并在 `error.stage` 定位失败阶段；外部命令诊断写到 stderr，stdout 返回一个 JSON 结果及已完成阶段。

`data.current_instance` 在暂无所属容器时为 `null`，存在时报告实际容器、镜像、运行身份及 `matches_prepared_image`。`native_inputs_match` 按对应后端原生源码输入比较，文档变更导致镜像 ID 不同时也能判断原生输入是否相同；后端不同或本地缺少来源树时为 `null`。这个比较只覆盖原生输入，CLI、策略与整个镜像的差异另行核对。`build` 只准备产物，切换已有实例仍需明确的 `close/open`。

整个工作目录以一个读写挂载进入容器 `/work`。宿主保存 `runtime/default/host.json`，本次 `CLIENT_ROOT=/work/runtime/default/RUN_ID`；桥、锁、日志和自动生成的账号/服务器快照按此隔离。资源 `/client` 和 `/data` 保持各自现有只读格式和来源。用户脚本直接使用 `/work/scripts`。`cache_dir`（默认 `<workbench>/cache`）在创建新实例时创建并解析，不可用时启动失败（`cache_dir_unavailable`）；该目录读写挂到容器 `/cache`，GUI 与 headless 相同，客户端进程以 `BEIDOU_CACHE_DIR=/cache` 写入版本化世界地图缓存。

普通结果为 JSON 信封，含 `ok/command/data`；客户端结果还含 `backend/instance`。失败含 `error.code/message/details`，已识别失败退出码2、中断130。`list` 和 `notes` 输出文本，`watch/events watch` 输出 JSONL，`resources-check` 输出原生资源检查 JSON；`server dev` 的输出来自 Compose 或服务端 CLI。

## 启动、观察与关闭

```bash
workbenches/workbench list dev
workbenches/workbench dev/NAME notes
workbenches/workbench dev/NAME status
workbenches/workbench dev/NAME plan
workbenches/workbench dev/NAME open
workbenches/workbench dev/NAME snapshot
workbenches/workbench dev/NAME close
```

`list [live|dev]` 列出角色。`notes` 读取所选角色的交接资料：常驻角色看养成计划，开发角色看状态记录。`plan` 只核对目标；`build` 准备镜像，`open` 构建或复用后确认入图。`close` 只回收所属客户端，不停止游戏服务器。

两端使用权限为 `0600` 的 `account.json`：必填 `username`、`password`，已有角色的 `open` 还要求真实 `character_id`（正 int32）；`world/channel` 可选、为0基索引，默认各为0。GUI 仅支持世界0、第1至20频道，并按CID选角。密码只从账号文件读取。

### 首次登录与建角

常驻 v1.12 已实测不存在的短 ASCII 用户名登录后自动注册：登录前只读确认无账号，成功后只读确认账号已创建。15 字符 ASCII 用户名尝试后，服务日志记录 name 列过长且账号仍不存在；10 字符成功。建议用户名不超过 10 个 ASCII 字符；JAR 迁移中的 `VARCHAR(13)` 不足以证明现网完整上限。注册与建角、绑定及入图分别确认。

宿主 `login` 启动所选后端的账号会话并等待角色列表；声明同意和账号性别选择需用户明确授权，只在新启动时提供：

```bash
workbenches/workbench dev/NAME login --accept-terms --gender female
workbenches/workbench dev/NAME login
workbenches/workbench dev/NAME character create --name NAME --gender female --job JOB --face FACE --hair HAIR --hair-color COLOR --skin SKIN --top TOP --bottom BOTTOM --shoes SHOES --weapon WEAPON
workbenches/workbench dev/NAME character result REQUEST_ID --instance-id INSTANCE_ID --run-id RUN_ID
```

角色外观等数值须按实际选择填写；`--hair` 是基础发型，`--hair-color` 是独立必填项，不能省略或并入 `--hair`。建角是独立的一次请求，不自动入图。运行中再次 `login` 只观察，不能重新应用启动选项；容器内 `beidou-pilot login [--timeout N]` 不带授权选项时只观察，不接受宿主启动选项。GUI 容器内可显式传 `--gender male|female` 发起首次登录动作，需要同意声明时另加 `--accept-terms`；GUI 动作必须指定性别，无头容器内不接受这些选项。GUI 的账号提交、声明接受、性别、世界、频道与建角步骤由原生桥在游戏线程调用原版客户端内部入口完成，Python 只核对实例身份与页面、保持一次性去重并投影结果，不使用桌面键鼠坐标。已有角色账号若服务端仍要求设置性别，安全收紧后不再依据 CID 隐式选择性别；CID 不代表授权选择。经用户确认后关闭所属实例并核对退出，以 `login --gender male|female` 新启动完成选择并核对角色列表，再关闭该实例、核对退出，最后按真实已有 CID `open`。此迁移路径尚未真实游戏实测。若同时需要接受声明，须另有明确授权并添加 `--accept-terms`。

`character create` 返回请求与实例身份（GUI 的建角步骤由原生桥调用原版客户端内部动作，结果仍以新鲜角色列表的唯一新增 CID 核验）；`completed` 含真实 CID，`rejected` 为拒绝；`accepted` 或 `unknown` 并非完成，保留身份用 `character result` 查询，不重发。宿主 `character result` 要求原容器仍运行；实例退出或身份变化时未终结结果可能变为 `unknown`，无法保证恢复。容器停止后保留已有结果和身份等证据，人工核验，不保证可通过宿主命令查询。宿主仅在完成且账号文件与运行快照匹配、权限正确、绑定无冲突时写入 CID；`binding` 失败不代表建角失败，应依据结果及实际角色列表人工核对恢复，勿重发。完成绑定后，账号模式进程不支持同进程选角；先以工作台 `close` 并核对所属容器退出，再 `open` 并核对实际入图。GUI 建角同样经原生动作完成：打开建角页、确认类别、姓名核查、外观性别与逐槽外观轮转、最终确认；当前仅支持世界 0、第 1 至 20 频道、空角色列表、职业 `job=1` 与可打印 ASCII 角色名，外观候选须在当前界面实际核验，无法到达时停止。GUI 登录或建角超时、页面不明或原生动作拒绝时保留现场与身份，先观察或查询，不重放。

启动器把账号与已解析的服务器配置自动保存到 `runtime/default/RUN_ID/account.json`、`server.json`。容器入口读取该快照、生成内部资源映射与 `state/container.json`，再运行原生进程。随后宿主向容器内 `open` 传入这两个快照路径，完成或确认登录；容器 CLI 的 `--server` 核对已有实例的服务器，连接保持原样。日常只维护工作目录根的账号和新建设置，运行快照由启动器管理。

已核验目标公告频道 IPv4 为 `127.0.0.0/8` 时，无头端使用该目标内部IP并保留公告端口；其他地址沿用公告。该映射不修改服务端或原资源。

| 命令 | 行为 |
| --- | --- |
| `build` | 构建或复用所选版本镜像 |
| `plan` | 只读核对授权目标 |
| `resources-check` | 用headless镜像离线解析配置的只读原版 Data/IMG，仅依赖镜像与资源配置 |
| `status` | 报告未运行实例；运行时由容器CLI读取实时阶段与版本 |
| `doctor` | 在已有容器内检查资源和读取能力 |
| `instances` | 返回当前容器实例身份与版本 |
| `capabilities` | 读取原生能力和静态观察支持范围 |
| `world-map route START GOAL` | 只读查询原生世界门户图的有向跨图路线；不启动、不控制客户端 |
| `open/close` | 新建或接续所属实例；正常停止、确认退出并回收 |
| `snapshot [-i] [--all]` | 当前角色、场景、领域摘要与引用 |
| `inspect KIND [ID]` | 按需领域读数或静态资料 |
| `watch --seconds N --interval N` | 持续只读状态，JSONL输出 |
| `events read/watch` | 当前实例原生事件；由 GUI 同类通知气泡提供 |
| `bridge status/stop` | 只读桥状态，或停止全部脚本会话并释放输入 |
| `stop` | 释放本实例遗留按键，等价于全停会话 |

动作、脚本等参数由容器内客户端解释。核对容器归属后可用 `docker exec CONTAINER beidou-pilot --json status` 只读排查。中断脚本 CLI 只结束等待，脚本取消另行显式 `script cancel --session`。

`snapshot` 与 `inspect character` 的 `character.physics` 是本端同一次原生更新的未插值物理末态（`update_id/step_ms/x/y/velocity/on_ground`），未知字段为 `null`；它与 `character.x/y` 显示位置、`character.velocity` 区间均速语义分开，CLI 只校验并透传，不做运动计算或补齐。字段语义与校准采样见 [Tick Lua API](LUA_TICK_API.md#运动观察与静止参考)。

短脚本返回或取消后容器继续运行。`close` 独立于输入锁，经Docker正常发SIGTERM，确认 `Running=false/Pid=0` 后保存退出日志并回收；活动Lua期间同样可关闭。容器内 `close` 返回 `host_lifecycle_required`。同一目录正在启停为 `lifecycle_busy`，活动脚本期间其他动作是 `input_busy`；失败先读状态和所属日志再决定重开。

## 世界门户图与路线查询

```bash
workbenches/workbench dev/NAME world-map route 100000000 100000100
```

`world-map route START GOAL` 用两个正整数地图号查询原版静态门户模型中的跨图路线。命令只读：不启动客户端、不发送游戏输入，需要该目录已有运行中的客户端提供只读观察通道。缺少子命令、地图号缺失或非正整数、多余参数按 `usage` 拒绝，不会启动客户端。

原生侧从客户端只读 `Data/` 的地图 IMG（`Map002/Map`，缺少 `Map002/` 时用 `Map/Map`）门户记录派生模型：只把指向其他地图的跨图门户当作有向边，排除带 script 的门户和外部目标 `999999999`；同地图内同名同目的地的门户合并为一条边，不推断反向边。路线按有向 BFS 搜索，最多 24 段。模型、路线搜索和版本化缓存都由两端共用的原生实现（[WorldMap.h](../shared/lua-runtime/WorldMap.h)、[WorldMapImage.h](../headless/src/WorldMapImage.h)）负责，Lua 侧不解析模型、不做搜索。

缓存路径为 `<cache_dir>/world-map/<logic_version>/<source_fingerprint>.wmap`，当前 `logic_version=2`。`logic_version` 或来源 fingerprint（地图 IMG 的相对路径、字节数与首尾内容采样哈希；不依赖 mtime，避免 Linux 与 Wine/Windows 时间表示不同导致同一资料分叉缓存）任一变化都会使用新路径；运行时只写新文件，不删除旧版本缓存。缓存不可写时本次仍用内存模型查询（`cache="memory"`）；来源数据缺失或不可读、观察通道或实例身份异常时返回统一错误信封（`ok=false`，退出码 2），不猜测缺失资料。

`data` 字段：

| 字段 | 含义 |
| --- | --- |
| `source` | 固定 `native_world_map` |
| `status` | `ok`、`no_route`、`map_unknown` 或 `route_too_long`；这些是正常返回的路线结果，不是 CLI 错误 |
| `error` | 状态原因字符串（`no_route`、`source_map_unknown`、`target_map_unknown`、`route_too_long`），`ok` 时为 `null` |
| `start`、`goal` | 本次查询的地图号 |
| `model` | `logic_version`、`source_fingerprint`、`maps`（场景数）、`edges`（合并后有向边数） |
| `cache` | `hit`（命中缓存）、`built`（本次派生并写入）或 `memory`（未写文件，仅内存模型） |
| `legs` | 有序路线段；每段含 `from`、`portal`、`to` 与门户坐标 `portal_at`（二维整数数组，每个元素为 `[x, y]` 门户点） |

`status=ok` 时 `legs` 为按顺序的腿序列，起点与终点相同时为空数组；起点或终点地图号不在模型内时返回 `map_unknown`（`error` 区分 `source_map_unknown` 与 `target_map_unknown`），有向门户不可达返回 `no_route`，超过 24 段返回 `route_too_long`；`no_route`、`map_unknown` 与 `route_too_long` 的 `legs` 为空，且都按正常 JSON 返回（退出码 0）。该查询复用只读观察请求通道（domain `world-route`，请求额外携带 start 与 goal 两个地图号），但不是普通观察领域：不出现在 `capabilities.observation_domains`，也不能用 `inspect` 或领域观察读取。腿序列如何交给 tick 脚本见 [Tick Lua API](LUA_TICK_API.md#当前静态场景与跨图)；付费交通不在路线模型内。

## 离线检查资源

```bash
workbenches/workbench dev/NAME resources-check
```

该命令固定选择headless镜像，读取公共资源配置并只读解析原版 Data/IMG，全程离线；GUI工作目录也可使用，后端设置保持原样。

Python `Catalog` 同样直接读取资源配置的 `game_data`，在自身进程内加载独立的 `libbeidou-img.so` 解码原版 IMG；不向游戏客户端、桥 DLL 或服务器请求静态数据。解析库随两种客户端镜像交付，源码离线开发可用 `make -C headless build/libbeidou-img.so` 构建，`BEIDOU_IMG_LIBRARY` 可显式选择该本地库。资源只取北斗 `Data/`；缺失条目保持未知，不回退到旧 NX 或导出 XML。内存节点兼容库仍保留上游 `nl::node` / `nl::nx` 名称，它们不是 NX 文件来源。

## 客户端事件

```bash
workbenches/workbench dev/GUI_NAME events read
workbenches/workbench dev/GUI_NAME events watch
workbenches/workbench dev/GUI_NAME events watch \
  --cursor '{"instance_id":"本次原生实例","run_id":"本次运行","seq":12}' --seconds 30
```

`events read` 返回当前保留区的 `events`、`first_seq/last_seq` 和完整 `cursor`；给定游标时只返回其后的事件。游标由 `instance_id/run_id/seq` 三字段组成，身份字段原样保留。事件带 `seq/observed_at_ms/scene_generation/character_id/type/source/expires_at_ms/data`；未知角色或期限为 `null`，`observed_at_ms` 是客户端捕获时间。

`events watch` 在取得首个新鲜基线后输出 `event="events_ready"` 及游标，随后每条 `event="client_event"` 的 `data` 保存完整原生事件，`cursor` 指向该条。无游标时从订阅时刻之后开始；给定游标时先输出就绪，再补发保留区内的后续事件。已有未处理气泡须另读当前 notifications，历史气泡按历史记录处理。默认持续监听，可用 `--seconds` 有界退出；`--interval` 默认为0.025秒，范围为0.01至1秒。中断监听只结束读者，Lua 与客户端保持运行。

绑定身份后的持续监听遇到暂时失效采样引发的 `stale_bridge_state` 时，保留游标等待新鲜采样，旧文件中的事件不投递。同一不可用期间只输出一条 `event="events_unavailable"` 流诊断；恢复后输出 `events_ready` 并从原游标继续。首次基线尚未建立时诊断中的 `cursor=null`。这些流诊断只描述事件流健康；等待仍遵守 `--seconds` 和取消。单次 `events read` 按本次采样结果返回，身份、协议及其他错误使监听退出。

原生保留最近128条事件，每个读者独立持有游标。落后于保留区返回 `events_gap`，须重新观察当前事实；身份变化返回 `events_identity_changed` 并停止，后续实例另行接入。旧桥及无头未提供通知气泡事件时返回 `unsupported_capability`；原生报告事件发布失败时返回 `events_unavailable`，旧文件只作历史保留。事件通知描述界面事实：`notification.opened` 提示发现气泡，`notification.closed` 表示该气泡不再待处理，关闭载荷的 pending/available 均为 false；`notification.observation_unavailable` 表示本端观察中断。后续业务结果按相应当前状态另行核对。

## 原生通知气泡

```bash
workbenches/workbench dev/GUI_NAME notifications
workbenches/workbench dev/GUI_NAME notifications respond @notificationCURRENT --button 2000
workbenches/workbench dev/GUI_NAME notifications respond @notificationCURRENT --button 2001
```

`notifications` 统一列出同一原生气泡类的所有种类，包含好友、组队、交易、任务、快递等；未识别种类保留整数 `native_kind`，`kind=null`，同样完整返回。来源槽的原始文字为 `source_text`；已证实的玩家、队伍、交互或任务标识分别保留，未知为 `null`。交易 `interaction_id` 与发送者 ID 是两个字段。完整气泡正文尚未提取，`text=null`、`not_covered` 包含 `rendered_body_text`，需要时用当前截图辅助，正文以实际读取结果为准。

气泡保留 `pending/available`、`expires_at_ms/remaining_ms`、当前 `window` 和真实 `buttons`。原生 duration 为0时两个期限字段为 `null`，表示没有自动到期时间；服务端有效期另行判断。按钮保留实际 `control_id` 和位置，2000标为 `primary`，2001标为 `dismiss`，其他语义未知。某些气泡只有关闭按钮；主按钮可能接受邀请、打开快递或进入后续确认界面，含义按当前气泡正文判断。

响应必须使用本次读取的 `ref` 和实际存在的 `--button`，引用绑定原生实例、运行和场景代次。过期、关闭或不可响应时返回 `stale_notification`，缺少按钮返回 `notification_button_unavailable`，按本次指定的按钮处理。GUI 使用当前控件位置，不重放固定桌面坐标。

返回的 `input_dispatched=true` 仅确认本轮桌面输入已派发；`after` 分别报告气泡是否还在、是否仍待处理及可响应，`effect` 保持 `unknown`。主按钮操作后气泡仍在属于正常结果，再次点击需重新读取后决定。输入派发后采样不可用时，结果保留该事实并返回 `observation_error`，派发按已提交处理。

业务结果另外核对：实际入队需要成员状态，接受交易邀请需要确认交易窗口，最终成交则是不同动作，需要独立明确授权；气泡消失与否作为界面事实单独记录。本接口只响应气泡按钮，物品、金币和成交由对应命令完成。组队成员接口和真实核验继续由 [#92](https://github.com/Diluka/beidou-pilot/issues/92) 完成。GUI 气泡由 GUI 端提供，无头端按结构化事件交付。

## 动作与 Lua

角色动作写在 UTF-8 tick Lua 文件或含 `main.lua` 的目录脚本包中。示例在 `dev/NAME` 的 `scripts/tick_observe.lua` 保存用户脚本：

```bash
workbenches/workbench dev/NAME script describe tick_observe.lua
workbenches/workbench dev/NAME script run tick_observe.lua --ticks 10 --seconds 20
workbenches/workbench dev/NAME script start tick_observe.lua --seconds 20
workbenches/workbench dev/NAME script status
workbenches/workbench dev/NAME script status --session SCRIPT_ID
workbenches/workbench dev/NAME script cancel --session SCRIPT_ID
```

| 命令 | 支持与结果边界 |
| --- | --- |
| `script describe FILE\|DIR` | 只读本地 tick 策略文件或目录脚本包，输出 `main(context)`、有效 `@tick` 配置、声明参数和动态用法；输出不含 `mode` 字段，不执行入口。 |
| `script run/start FILE [策略参数]` | `run` 等待会话终态；`start` 等原生受理后返回。中断等待不会取消已受理会话。 |
| `script run/start DIR [策略参数]` | tick 目录脚本包：`DIR/main.lua` 为入口，其余 `.lua` 由入口按包内相对路径 `require`；会话状态可查实际装载模块，模块缺失/编译/运行错误带来源模块与行号。 |
| `script status [--session SCRIPT_ID]` | 只读全部会话 `scripts` 与最新 `script`，可按 ID 选择；tick 会话含调度、动作与所属输入释放事实。 |
| `script cancel --session SCRIPT_ID` | 精确取消指定会话并等待所属输入释放，其他会话保持。 |
| `stop`、`bridge stop` | 停止全部会话并释放输入；`stop` 保留为释放遗留按键的轻量入口。 |

`script describe/run/start` 的相对路径从所选角色的 `/work/scripts` 解析，例如 `tick_observe.lua`；绝对路径指向容器内指定位置，例如 `/opt/beidou-pilot/shared/scripts/examples/tick-jump-attack.lua`。单文件和目录包规则相同。运行期限用 `--seconds`（默认 30，范围 `0.001..4294967.295` 秒）或显式 `--continuous`；期限与单次回调的 `@tick.budget_ms` 独立。脚本日志由原生端写入所属实例桥目录的 `script-events.jsonl`，游戏效果另行核对。

tick 引擎按每会话频率档位到期调用 `main(context)`，通过 `context.state` 保留跨调用状态，通过 `context.game` 的只读领域观察，通过 `context.game.player` 提交方向与动作意图；调用频率、预算、领域字段和动作槽语义以 [Tick Lua API](LUA_TICK_API.md#tick-环境) 为准。tick 入口可以是单文件，也可以是目录脚本包：目录内固定 `main.lua` 为入口，其余 `.lua` 由入口用原生 `require` 按包内相对路径装载，模块文件保持原位置、不复制进会话目录；GUI 与 headless 由原生各自把包根映射到本端文件系统，会话状态可查实际装载模块，模块缺失、编译或运行错误带来源模块与行号。完整示例：

```lua
-- @tick.gear 3            -- 1=10Hz，2=20Hz，3=30Hz默认，4=本端原生更新
-- @tick.budget_ms 100
-- @tick.overrun abort     -- 或 skip
-- @tick.abort_commit true
-- @option[type=int,default=5,min=1] ticks 观察次数
local function main(context)
    context.state.calls = (context.state.calls or 0) + 1
    local world = context.game.world
    if not world.ready then return end
    if context.state.calls >= context.options.ticks then return "done" end
end
```

```bash
workbenches/workbench dev/NAME script run tick_observe.lua --ticks 120 --continuous
```

脚本统一按 tick 引擎执行，无需声明引擎；`@tick.gear/budget_ms/overrun/abort_commit` 可单独出现在前导注释中；未知或重复的 `@tick.*`、非法值在发布前拒绝。`@tick.gear` 接受 `1/2/3/4`，分别为 10Hz、20Hz、30Hz 和本端原生更新不节流，默认第 3 档；不接受前导零、符号或任意 tick 倍率。首次稳定回调立即执行，之后按绝对相位跳过过期周期，不突发补跑。固定频率是目标而非严格最大延迟。默认单次预算 **100ms / abort / abort_commit=true**；`abort` 默认提交已写草稿后以 `tick_overrun` 终止该会话并放键，`abort_commit=false` 则丢弃草稿；`skip` 仅中断本次调用。预算 hook 无法抢占阻塞的原生 C 调用，适用受信脚本而非恶意源码沙箱。

### 策略参数与状态

策略选项写在入口附近的 Lua 注释中；类型支持 `int`、`number`、`string`、`boolean`。非布尔参数没有 `opt` 或 `default` 时必填，声明默认值后可省略。布尔参数未声明 `default` 时可省略且默认为 `true`；显式 `default=false` 时省略则为 `false`。`min`/`max` 用于数值范围，`choices=a|b` 限定候选值。默认值、正向 flag 和显式值按 `choices` 校验，`--no-flag` 作为无值负向开关直接传入 `false`，不因 `choices` 未列出 `false` 而拒绝。Lua 参数名中的下划线映射为 CLI 连字符：

```lua
--- 在当前地图观察目标。
-- @option[type=int,min=1] mob_id 目标怪物模板 ID
-- @option[type=int,opt,default=1001005] skill_id 可选技能 ID
-- @option[type=boolean] observe_only 仅观察；省略时默认 true
-- @option[type=boolean,default=false] attack_enabled 默认关闭攻击
local function main(context)
    game.log("map=" .. tostring(context.scene.map_id)
        .. ", mob=" .. tostring(context.options.mob_id)
        .. ", observe_only=" .. tostring(context.options.observe_only))
end
```

`script describe FILE` 显示动态参数帮助及有效默认值。策略的 `context.options` 包含 CLI 值和声明默认值；`context.scene` 带有只读身份锚点 `instance_id`、`character_id`、`map_id`、`scene_generation` 及静态地形，调用方已有的 `context.route` 按原规则保留。`context.scene.terrain.status` 是 `available`、`unavailable` 或 `unsupported`；只有 `available` 时才提供有来源的 `footholds` 与 `ropes`。换图与场景代次变化由原生 tick 引擎更新只读 `context.scene`，策略在 `context.state` 中管理自己的缓存。

`script status` 保留最新接纳的 `script`，并列出全部会话 `scripts`；每项含 `mode`、状态、原因、会话级 `control_released`，tick 另含有效 gear、实际调用 index/time/delta、场景代次、预算、超限策略及共享 `player` 动作状态。`player` 只区分当前输入槽和已开始的原生动作，不是角色 HP/buff。指定 `--session` 后 `script` 选择对应会话，`scripts` 仍保留全部会话；`command` 是最近命令，不能代替会话身份。同一客户端可追加多个 tick 会话，共享唯一角色状态机，后写覆盖；精确取消只检查目标会话终态及所属输入释放，需要全部停止时显式 `stop` 或 `bridge stop`。

动作设置返回受理，不代表技能已开始、命中或药效已发生；调用方以实际游戏事实核对结果。需要移动、战斗、用药等动作时写 tick Lua，不要把动作拆回 Python 逐帧控制。

## 正常复活

`revive` 在 GUI 与无头端都提交一次普通复活请求。HP 已知为正时返回 `already_alive` 且不发送请求；角色或 HP 读数不可用时拒绝操作。两端均调用共享 tick Lua 的 `player.revive()`：GUI 端只在唯一已识别复活窗口及其启用的确认按钮可验证时调用原版窗口确认动作；无头端由本端发送普通 `CHANGEMAP` 请求。请求派发不表示恢复成功：命令只在同一角色 ID 的 HP 为正、地图与位置有效时返回 `revived`；GUI 还要确认复活窗口消失。超时或身份变化时停止，不重发。

## AP 自动分配

`workbenches/workbench dev/NAME auto-ap` 无参数，提交一次当前全部剩余 AP 的自动分配请求。GUI 调用原版自动分配流程，无头端按其已实现的职业规则计算；不支持的版本或职业返回 `unsupported_capability`。服务端负责最终校验，不直接修改数据库。

AP 已为 0 时返回 `status=unchanged`；确认同角色 AP 已归零且属性增量合计等于原 AP 时返回 `status=allocated`。两者都返回 `before`、`after`（含 `strength`、`dexterity`、`intelligence`、`luck`、`ability_points`）、`allocated` 和 `remaining_ap`。`unknown` 表示结果未确认，先观察同一角色的属性和剩余 AP，不重复请求。完整职业覆盖不作保证。

## 无头控件交互

无头端保留只读观察，不提供桌面输入入口：`snapshot` 与 `inspect` 返回当前 `interaction.page`、控件 `role/text/enabled/ref` 和场景 NPC 引用；`click`、`ui`、`equip`、`hotkeys`、`bind`、`talk`、`dialog`、`shop`、`notifications` 等 GUI 命令在无头端统一返回 `unsupported_capability`。需要激活页面控件或 NPC 时使用原版 GUI 会话；无头端的任务接交等交互能力当前不提供，缺口见[能力边界](CLIENT_LIMITATIONS.md)。

```bash
workbenches/workbench dev/NAME snapshot
workbenches/workbench dev/NAME inspect quests
```

页面只有 `source/title/text/controls`，控件只有 `role/text/enabled/ref`。正文或控件未知时为 `null`，`enabled=null` 保持未知。服务端普通脚本页和客户端本地任务页的激活由 GUI 端提供；本地页只显示当前状态能证明的任务条目。任务观察已合并完整角色包与本端正常增量，`live_updates=true`，`live_update_kinds` 为 `not_started/started/completed`。原生观察保留原始进度串，关联语义未核实时 `linked_progress=null`。

## 原版 GUI

GUI 镜像包含与无头端相同的CLI与Lua，以及Wine/VirtualGL和匹配的桥DLL。其资源路径仍从公共 `private/workbenches/config/resources.json` 读取；原版客户端只读挂到 `/client`，`game_data` 指向的 `Data/` 只读挂到 `/data`，供 Catalog 使用共享原生解析器。工作目录的 `workbench.json` 设置 `backend="beidou"` 后，使用相同入口：

```bash
workbenches/workbench dev/GUI_NAME build
workbenches/workbench dev/GUI_NAME open
workbenches/workbench dev/GUI_NAME doctor
workbenches/workbench dev/GUI_NAME snapshot
workbenches/workbench dev/GUI_NAME close
```

当前启动器配套的 [GUI Compose](../docker/compose.yaml) 装配角色 `ref` 所选镜像。原客户端只读挂到 `/client`，镜像内的桥位于 `/opt/beidou-pilot/native/ijl15.dll`。容器在 `$CLIENT_ROOT/client` 生成可写运行副本，`Data/` 读取原只读目录，`2ijl15.dll` 图片库仍保留；外部原始文件保持只读。CLI、桌面输入和录制直接使用本容器的桥和显示环境。

GUI 容器在自身网络命名空间启用回环游戏端口 NAT，连接已核验目标，服务端公告地址保持原样。Wine prefix、运行日志和桥数据位于本次 `$CLIENT_ROOT/runtime/` 下，由工作台持久化，需允许 `1000:1000` 读写。硬件路径使用 `/dev/dri/renderD128`、`DISPLAY=:97` 的 `1920x1080x24` Xvfb 和窗口管理器、VirtualGL EGL；Wine 虚拟桌面提供原客户端所需显示模式。GUI启动诊断日志写入本次运行目录。

构建成功、环境检查和实际入图分别记录；涉及动作时另核对实际游戏结果。GUI 输入仍只允许一名明确操作者。

以下操作由 GUI 端提供，无头端按能力声明返回：

| 命令组 | 用途 |
| --- | --- |
| `talk TARGET`、`dialog` | 原版 NPC 对话与桌面消费者 |
| `click REF` | 激活当前控件引用或桌面坐标；无头端返回 `unsupported_capability` |
| `ui read` | 读取已识别窗口；窗口开关与焦点命令不再提供 |
| `equip ITEM` | 普通唯一槽位走原版背包点击换装；无头端返回 `unsupported_capability` |
| `hotkeys`、`bind` | 读取当前键位、拖放绑定物品或技能 |
| `shop read/buy/sell/close` | 普通商店读取与指定买卖；数量框和关店按实际 UI 收尾 |
| `screenshot [NAME]`、`record NAME` | 当前窗口截图或有界逐帧记录，不发游戏输入 |

引用来自本次快照，换图、对话翻页、重登或目标变化后重新读取。任务/奖励、消费和交易按一次派发处理；以当前完整正文和实际变化判断。GUI 输入只允许一名明确操作者。

## 有限批次

`batch [--file PATH]` 接受非空JSON参数数组，先解析全部CLI参数，再顺序执行。批次绑定当前实例，嵌套 batch 按错误拒绝。进度写stderr，最终仍是单个JSON；批内watch收为最终状态。

某一步抛错时立即停止，错误详情含从0开始的 `index`、此前 `completed` 和原始 `cause`，已发生效果按实际保留。子命令正常返回预算停止或取消状态时批次继续；批次用于编排无需中途决策的有限步骤，持续控制写Lua。批次不接受 `script run/start/describe`（这些入口要先读取本地文件，CLI 在批次内返回 `usage`），`script status` 与 `script cancel` 可用。
