# 命令使用

唯一宿主入口是 [private/workbenches/workbench](../private/workbenches/workbench)，它直接调用 Git、Docker 和 jq。使用 `private/workbenches/workbench DIR COMMAND` 指定一个账号角色的工作目录；两个镜像中的客户端命令仍叫 `beidou-pilot`，由宿主入口通过 `docker exec` 执行。

## 工作目录配置

工作目录必须已存在。普通工作目录只维护 `account.json` 和需要的新建设置 `workbench.json`，养成计划、交接、用户 Lua 和运行数据也放在该目录。资源路径共用主检出目录中的 `private/workbenches/resources.json`，字段示例见 [resources.example.json](../cli/config/resources.example.json)。从开发 worktree 调用时也读取这份公共配置。

常驻服务器的项目、服务与公开镜像引用固定在统一入口中。启动器核对真实服务器容器及其镜像；普通目录的服务器信息由入口固定，宿主服务器路径、账号路径和资源路径使用统一入口的配置。固定目标作为目标依据，本次玩法授权及账号占用另行核对。

`workbench.json` 可省略，默认使用 headless、main 和90秒入图等待。GUI 目录的最小 [配置示例](../cli/config/workbench.example.json) 为：

```json
{"backend":"beidou"}
```

| 设置 | 默认及用途 |
| --- | --- |
| `backend` | `headless`；可选 `headless` 或 `beidou` |
| `ref` | `main`；开发验收可明确指定已提交版本 |
| `timeout` | `90`；5至180的数值，仅限制入图等待 |
| `bridge_artifact` | 可选的匹配 GUI 桥工件目录；相对路径按工作目录解析，省略时经 `gh` 获取相应提交成功 CI 的工件 |
| `server` | 仅特殊情况确需隔离服时使用的显式对象；日常使用、调试与实际游戏验收默认省略，使用固定常驻服务器 |
| `harness` | 默认 `false`；`true` 时从所选客户端 base 派生包含 Codex、harness 和专用技能的镜像 |
| `model_proxy` | 可选的 `http://IPv4:端口` 模型 HTTP 代理，独立于客户端和脚本；模型 API 地址仍在 provider 配置中 |

调试和实际游戏验收默认复用常驻服务器与已授权的已有账号角色，只有场景必须时才新建账号或角色。确需隔离服时记录原因，其 `server` 要求 `project/service/expected_image`，`network` 可选。项目须为非 `beidou-ms` 项目，隔离服务器须不发布宿主端口、使用 bridge 网络；指定网络时为同项目 internal 网络并且服务器已连接。省略网络时，启动器为新实例建立所属 internal 连接并在关闭时回收。例如：

```json
{
  "backend": "headless",
  "ref": "COMMIT",
  "server": {
    "project": "ISOLATED_COMPOSE_PROJECT",
    "service": "app",
    "expected_image": "sha256:VERIFIED_APPLICATION_IMAGE",
    "network": "ISOLATED_INTERNAL_NETWORK"
  }
}
```

启动设置仅在新建时读取。一个目录对应一个账号角色和容器，宿主实例名固定为 `default`；原生 `instance_id/run_id` 核验继续保留。已有容器的 `status/script/close` 依赖目录下的运行登记和实际容器，新建配置修改后新实例再按新版本构建。

## 版本、挂载与输出

新实例一次解析 `main` 或 `workbench.json.ref` 的已提交 SHA，以该树及固定子模块构建或复用所选后端镜像。本次输入固定为导出时的代码树。已有实例继续运行启动时的 CLI、内置 Lua 和原生组件，实际版本查 `status` 的 `source_revision/image/run_id`。

`build` 保留 `data.image/source_revision/backend`，并在 `data.preparation` 中报告实际执行的准备阶段：

| 阶段 | 可核对的结果 |
| --- | --- |
| `context` | 源码上下文新建或复用，固定提交、源码树及子模块提交 |
| `bridge`（GUI） | CI 下载、已有工件或镜像内清单的来源；直接附带原有 manifest 中的目标指纹、桥指纹、依赖和工具链 |
| `client_image` | 客户端镜像新建或复用，实际标签和镜像 ID |
| `harness_image`（启用时） | 派生镜像新建或复用，实际标签和镜像 ID |

每个阶段包含 `outcome` 和 `duration_ms`。耗时是本次阶段的实际用时，镜像构建内部的层缓存仍由 Docker 构建日志说明。准备失败保留既有错误码，并在 `error.stage` 定位失败阶段；外部命令诊断写到 stderr，stdout 返回一个 JSON 结果及已完成阶段。

`data.current_instance` 在暂无所属容器时为 `null`，存在时报告实际容器、镜像、运行身份及 `matches_prepared_image`。`native_inputs_match` 按对应后端原生源码输入比较，文档变更导致镜像 ID 不同时也能判断原生输入是否相同；后端不同或本地缺少来源树时为 `null`。这个比较只覆盖原生输入，CLI、策略与整个镜像的差异另行核对。`build` 只准备产物，切换已有实例仍需明确的 `close/open`。

整个工作目录以一个读写挂载进入容器 `/work`。宿主保存 `runtime/default/host.json`，本次 `CLIENT_ROOT=/work/runtime/default/RUN_ID`；桥、锁、日志和自动生成的账号/服务器快照按此隔离。资源 `/client` 和 `/data` 保持各自现有只读格式和来源。用户脚本直接使用 `/work/scripts`。

普通结果为 JSON 信封，含 `ok/command/data`；客户端结果还含 `backend/instance`。失败含 `error.code/message/details`，已识别失败退出码2、中断130。`--list` 和 `notes` 输出文本，`watch/events watch` 输出 JSONL，`resources-check` 输出原生资源检查 JSON；`ai` 的 stdin/stdout 为 harness 专用 JSONL 协作通道。

## 启动、观察与关闭

```bash
private/workbenches/workbench --list
private/workbenches/workbench /external/workbench notes
private/workbenches/workbench /external/workbench status
private/workbenches/workbench /external/workbench plan
private/workbenches/workbench /external/workbench open
private/workbenches/workbench /external/workbench snapshot
private/workbenches/workbench /external/workbench close
```

只给工作目录时默认执行只读的 `status`。`notes` 只读已有 README、PLAN、HANDOFF 和脚本说明；`plan` 只核对目标。`build` 可提前准备镜像，`open` 自行构建或复用镜像，并确认本容器已入图。已有正确实例直接观察、接续即可。

两端使用权限为 `0600` 的 `account.json`：必填 `username`、`password`，已有角色的 `open` 还要求真实 `character_id`（正 int32）；`world/channel` 可选、为0基索引，默认各为0。GUI 仅支持世界0、第1至20频道，并按CID选角。密码只从账号文件读取。

### 首次登录与建角

常驻 v1.12 已实测不存在的短 ASCII 用户名登录后自动注册：登录前只读确认无账号，成功后只读确认账号已创建。15 字符 ASCII 用户名尝试后，服务日志记录 name 列过长且账号仍不存在；10 字符成功。建议用户名不超过 10 个 ASCII 字符；JAR 迁移中的 `VARCHAR(13)` 不足以证明现网完整上限。注册与建角、绑定及入图分别确认。

宿主 `login` 启动所选后端的账号会话并等待角色列表；声明同意和账号性别选择需用户明确授权，只在新启动时提供：

```bash
private/workbenches/workbench /external/workbench login --accept-terms --gender female
private/workbenches/workbench /external/workbench login
private/workbenches/workbench /external/workbench character create --name NAME --gender female --job JOB --face FACE --hair HAIR --hair-color COLOR --skin SKIN --top TOP --bottom BOTTOM --shoes SHOES --weapon WEAPON
private/workbenches/workbench /external/workbench character result REQUEST_ID --instance-id INSTANCE_ID --run-id RUN_ID
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
| `open/close` | 新建或接续所属实例；正常停止、确认退出并回收 |
| `ai [harness参数]` | 通过 `docker exec` 运行所属容器内的 `beidou-game-ai`；要求已有 harness 镜像实例 |
| `snapshot [-i] [--all]` | 当前角色、场景、领域摘要与引用 |
| `inspect KIND [ID]` | 按需领域读数或静态资料 |
| `watch --seconds N --interval N` | 持续只读状态，JSONL输出 |
| `events read/watch` | 当前实例原生事件；由 GUI 同类通知气泡提供 |
| `bridge status/stop` | 只读桥状态，或停止全部脚本会话并释放输入 |
| `stop` | 释放本实例遗留按键，等价于全停会话 |

动作、脚本等客户端参数直接跟在命令后，属于客户端参数。比如 `script run FILE --seconds 20` 的文件路径按容器内部解释。核对容器归属后可用 `docker exec CONTAINER beidou-pilot --json status` 只读排查。中断脚本 CLI 只结束等待，脚本取消另行显式 `script cancel --session`。

短脚本返回或取消后容器继续运行。`close` 独立于输入锁，经Docker正常发SIGTERM，确认 `Running=false/Pid=0` 后保存退出日志并回收；活动Lua期间同样可关闭。容器内 `close` 返回 `host_lifecycle_required`。同一目录正在启停为 `lifecycle_busy`，活动脚本期间其他动作是 `input_busy`；失败先读状态和所属日志再决定重开。

## 游戏 AI

新建设置 `harness=true` 后，`build/open` 先准备对应 headless 或 GUI base，再构建或复用同提交的 harness 衍生镜像；客户端保持原 PID1。只有配置了非空 `model_proxy` 的 harness 客户端额外连接默认 `bridge`，GUI 才增加该代理 IP/端口白名单，游戏服务器的 internal 网络不变。

```bash
private/workbenches/workbench /external/workbench ai \
  --state /work/ai/state --role /work/ai/role.md \
  --auth-file /work/ai/auth.json --task '先观察当前角色和场景' --paused
```

`--state/--role/--provider-config/--auth-file` 均为容器内路径，常驻状态放在 `/work` 下；`--cli` 仅指定容器内客户端路径。已有普通镜像返回 `harness_image_required`，harness 需要按新配置重建的实例提供。普通 agent 通过 shell 直接使用 CLI，只读模式只保留观察工具。LLM 独立启停时脚本与客户端保持运行，重新接入先观察现有任务；具体协作、状态续接与参数见 [HARNESS](HARNESS.md)。

## 离线检查资源

```bash
private/workbenches/workbench /external/workbench resources-check
```

该命令固定选择headless镜像，读取公共资源配置并只读解析原版 Data/IMG，全程离线；GUI工作目录也可使用，后端设置保持原样。

Python `Catalog` 同样直接读取资源配置的 `game_data`，在自身进程内加载独立的 `libbeidou-img.so` 解码原版 IMG；不向游戏客户端、桥 DLL 或服务器请求静态数据。解析库随两种客户端镜像交付，源码离线开发可用 `make -C headless build/libbeidou-img.so` 构建，`BEIDOU_IMG_LIBRARY` 可显式选择该本地库。资源只取北斗 `Data/`；缺失条目保持未知，不回退到旧 NX 或导出 XML。内存节点兼容库仍保留上游 `nl::node` / `nl::nx` 名称，它们不是 NX 文件来源。

## 客户端事件

```bash
private/workbenches/workbench /external/gui-workbench events read
private/workbenches/workbench /external/gui-workbench events watch
private/workbenches/workbench /external/gui-workbench events watch \
  --cursor '{"instance_id":"本次原生实例","run_id":"本次运行","seq":12}' --seconds 30
```

`events read` 返回当前保留区的 `events`、`first_seq/last_seq` 和完整 `cursor`；给定游标时只返回其后的事件。游标由 `instance_id/run_id/seq` 三字段组成，身份字段原样保留。事件带 `seq/observed_at_ms/scene_generation/character_id/type/source/expires_at_ms/data`；未知角色或期限为 `null`，`observed_at_ms` 是客户端捕获时间。

`events watch` 在取得首个新鲜基线后输出 `event="events_ready"` 及游标，随后每条 `event="client_event"` 的 `data` 保存完整原生事件，`cursor` 指向该条。无游标时从订阅时刻之后开始；给定游标时先输出就绪，再补发保留区内的后续事件。已有未处理气泡须另读当前 notifications，历史气泡按历史记录处理。默认持续监听，可用 `--seconds` 有界退出；`--interval` 默认为0.025秒，范围为0.01至1秒。中断监听只结束读者，Lua 与客户端保持运行。

绑定身份后的持续监听遇到暂时失效采样引发的 `stale_bridge_state` 时，保留游标等待新鲜采样，旧文件中的事件不投递。同一不可用期间只输出一条 `event="events_unavailable"` 流诊断；恢复后输出 `events_ready` 并从原游标继续。首次基线尚未建立时诊断中的 `cursor=null`。这些流诊断只描述事件流健康；等待仍遵守 `--seconds` 和取消。单次 `events read` 按本次采样结果返回，身份、协议及其他错误使监听退出。

原生保留最近128条事件，每个读者独立持有游标。落后于保留区返回 `events_gap`，须重新观察当前事实；身份变化返回 `events_identity_changed` 并停止，后续实例另行接入。旧桥及无头未提供通知气泡事件时返回 `unsupported_capability`；原生报告事件发布失败时返回 `events_unavailable`，旧文件只作历史保留。事件通知描述界面事实：`notification.opened` 提示发现气泡，`notification.closed` 表示该气泡不再待处理，关闭载荷的 pending/available 均为 false；`notification.observation_unavailable` 表示本端观察中断。后续业务结果按相应当前状态另行核对。

## 原生通知气泡

```bash
private/workbenches/workbench /external/gui-workbench notifications
private/workbenches/workbench /external/gui-workbench notifications respond @notificationCURRENT --button 2000
private/workbenches/workbench /external/gui-workbench notifications respond @notificationCURRENT --button 2001
```

`notifications` 统一列出同一原生气泡类的所有种类，包含好友、组队、交易、任务、快递等；未识别种类保留整数 `native_kind`，`kind=null`，同样完整返回。来源槽的原始文字为 `source_text`；已证实的玩家、队伍、交互或任务标识分别保留，未知为 `null`。交易 `interaction_id` 与发送者 ID 是两个字段。完整气泡正文尚未提取，`text=null`、`not_covered` 包含 `rendered_body_text`，需要时用当前截图辅助，正文以实际读取结果为准。

气泡保留 `pending/available`、`expires_at_ms/remaining_ms`、当前 `window` 和真实 `buttons`。原生 duration 为0时两个期限字段为 `null`，表示没有自动到期时间；服务端有效期另行判断。按钮保留实际 `control_id` 和位置，2000标为 `primary`，2001标为 `dismiss`，其他语义未知。某些气泡只有关闭按钮；主按钮可能接受邀请、打开快递或进入后续确认界面，含义按当前气泡正文判断。

响应必须使用本次读取的 `ref` 和实际存在的 `--button`，引用绑定原生实例、运行和场景代次。过期、关闭或不可响应时返回 `stale_notification`，缺少按钮返回 `notification_button_unavailable`，按本次指定的按钮处理。GUI 使用当前控件位置，不重放固定桌面坐标。

返回的 `input_dispatched=true` 仅确认本轮桌面输入已派发；`after` 分别报告气泡是否还在、是否仍待处理及可响应，`effect` 保持 `unknown`。主按钮操作后气泡仍在属于正常结果，再次点击需重新读取后决定。输入派发后采样不可用时，结果保留该事实并返回 `observation_error`，派发按已提交处理。

业务结果另外核对：实际入队需要成员状态，接受交易邀请需要确认交易窗口，最终成交则是不同动作，需要独立明确授权；气泡消失与否作为界面事实单独记录。本接口只响应气泡按钮，物品、金币和成交由对应命令完成。组队成员接口和真实核验继续由 [#92](https://github.com/Diluka/beidou-pilot/issues/92) 完成。GUI 气泡由 GUI 端提供，无头端按结构化事件交付。

## 动作与 Lua

客户端只有 tick Lua 引擎。角色动作写在 UTF-8 Lua 文件中，由 `script describe/run/start` 提交；脚本入口只有文件，没有 CLI 动作命令。

```bash
private/workbenches/workbench /external/workbench script describe /work/scripts/tick_observe.lua
private/workbenches/workbench /external/workbench script run /work/scripts/tick_observe.lua --ticks 10 --seconds 20
private/workbenches/workbench /external/workbench script start /work/scripts/tick_observe.lua --seconds 20
private/workbenches/workbench /external/workbench script status
private/workbenches/workbench /external/workbench script status --session SCRIPT_ID
private/workbenches/workbench /external/workbench script cancel --session SCRIPT_ID
```

| 命令 | 支持与结果边界 |
| --- | --- |
| `script describe FILE` | 只读本地 tick 策略文件，输出 `main(context)`、有效 `@mode`/`@tick` 配置、声明参数和动态用法；不执行入口。 |
| `script run FILE [策略参数]` | 客户端内同步等待会话终态；等待中断只结束 CLI 等待，已受理会话继续运行。 |
| `script start FILE [策略参数]` | 原生受理后返回，脚本由客户端独立执行；返回实例、运行、请求与脚本身份。 |
| `script status [--session SCRIPT_ID]` | 只读全部会话 `scripts` 与最新 `script`，可按 ID 选择；tick 会话含调度、动作与所属输入释放事实。 |
| `script cancel --session SCRIPT_ID` | 精确取消指定会话并等待所属输入释放，其他会话保持。 |
| `stop`、`bridge stop` | 停止全部会话并释放输入；`stop` 保留为释放遗留按键的轻量入口。 |

`script run/start` 只接受 UTF-8 Lua 文件，文件必须声明顶层 `main(context)` 函数，否则在发布前拒绝。运行期限用 `--seconds`（默认 30，范围 `0.001..4294967.295` 秒）或显式 `--continuous`；期限与单次回调的 `@tick.budget_ms` 独立。文件路径按容器内部解析；工作台整体挂到 `/work`，用户 Lua 直接放在 `/work/scripts`，每次调用读取当前文件内容。脚本日志由原生端写入所属实例桥目录的 `script-events.jsonl`，游戏效果另行核对。

tick 引擎按每会话频率档位到期调用 `main(context)`，通过 `context.state` 保留跨调用状态，通过 `context.game` 的只读领域观察，通过 `context.game.player` 提交方向与动作意图；调用频率、预算、领域字段和动作槽语义以 [Tick Lua API](LUA_TICK_API.md#tick-环境) 为准。完整示例：

```lua
-- @mode tick
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
private/workbenches/workbench /external/workbench script run /work/scripts/tick_observe.lua --ticks 120 --continuous
```

`@mode` 可省略并视为 tick；`@tick.gear/budget_ms/overrun/abort_commit` 可单独或与显式 `@mode tick` 一起使用。`@mode` 其他值、未知或重复配置、非法值均在发布前拒绝。`@tick.gear` 接受 `1/2/3/4`，分别为 10Hz、20Hz、30Hz 和本端原生更新不节流，默认第 3 档；不接受前导零、符号或任意 tick 倍率。首次稳定回调立即执行，之后按绝对相位跳过过期周期，不突发补跑。固定频率是目标而非严格最大延迟。默认单次预算 **100ms / abort / abort_commit=true**；`abort` 默认提交已写草稿后以 `tick_overrun` 终止该会话并放键，`abort_commit=false` 则丢弃草稿；`skip` 仅中断本次调用。预算 hook 无法抢占阻塞的原生 C 调用，适用受信脚本而非恶意源码沙箱。

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

## 无头控件交互

无头端保留只读观察，不提供桌面输入入口：`snapshot` 与 `inspect` 返回当前 `interaction.page`、控件 `role/text/enabled/ref` 和场景 NPC 引用；`click`、`ui`、`equip`、`revive`、`hotkeys`、`bind`、`talk`、`dialog`、`shop`、`notifications` 等 GUI 命令在无头端统一返回 `unsupported_capability`。需要激活页面控件或 NPC 时使用原版 GUI 会话；无头端的任务接交等交互能力当前不提供，缺口见[能力边界](CLIENT_LIMITATIONS.md)。

```bash
private/workbenches/workbench /external/workbench snapshot
private/workbenches/workbench /external/workbench inspect quests
```

页面只有 `source/title/text/controls`，控件只有 `role/text/enabled/ref`。正文或控件未知时为 `null`，`enabled=null` 保持未知。服务端普通脚本页和客户端本地任务页的激活由 GUI 端提供；本地页只显示当前状态能证明的任务条目。任务观察已合并完整角色包与本端正常增量，`live_updates=true`，`live_update_kinds` 为 `not_started/started/completed`。原生观察保留原始进度串，关联语义未核实时 `linked_progress=null`。

## 原版 GUI

GUI 镜像包含与无头端相同的CLI与Lua，以及Wine/VirtualGL和匹配的桥DLL。其资源路径仍从公共 `private/workbenches/resources.json` 读取；原版客户端只读挂到 `/client`，`game_data` 指向的 `Data/` 只读挂到 `/data`，供 Catalog 使用共享原生解析器。工作目录的 `workbench.json` 设置 `backend="beidou"` 后，使用相同入口：

```bash
private/workbenches/workbench /external/gui-workbench build
private/workbenches/workbench /external/gui-workbench open
private/workbenches/workbench /external/gui-workbench doctor
private/workbenches/workbench /external/gui-workbench snapshot
private/workbenches/workbench /external/gui-workbench close
```

[Compose](../docker/compose.yaml) 装配所选版本的 GUI 实例。原客户端只读挂到 `/client`，镜像内的桥位于 `/opt/beidou-pilot/native/ijl15.dll`。容器在 `$CLIENT_ROOT/client` 生成可写运行副本，`Data/` 读取原只读目录，`2ijl15.dll` 图片库仍保留；外部原始文件保持只读。CLI、桌面输入和录制直接使用本容器的桥和显示环境。

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
| `revive` | 死亡时只操作已识别确认框一次并核对同角色恢复；无头端返回 `unsupported_capability` |
| `screenshot [NAME]`、`record NAME` | 当前窗口截图或有界逐帧记录，不发游戏输入 |

引用来自本次快照，换图、对话翻页、重登或目标变化后重新读取。任务/奖励、消费和交易按一次派发处理；以当前完整正文和实际变化判断。GUI 输入只允许一名明确操作者。

## 有限批次

`batch [--file PATH]` 接受非空JSON参数数组，先解析全部CLI参数，再顺序执行。批次绑定当前实例，嵌套 batch 按错误拒绝。进度写stderr，最终仍是单个JSON；批内watch收为最终状态。

某一步抛错时立即停止，错误详情含从0开始的 `index`、此前 `completed` 和原始 `cause`，已发生效果按实际保留。子命令正常返回预算停止或取消状态时批次继续；批次用于编排无需中途决策的有限步骤，持续控制写Lua。批次不接受 `script run/start/describe`（这些入口要先读取本地文件，CLI 在批次内返回 `usage`），`script status` 与 `script cancel` 可用。
