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

两端使用同一份权限为 `0600` 的 `account.json`：必填 `username`、`password`、已有角色 `character_id`（正 int32），可选 `world/channel` 为0基索引，默认各为0。GUI 仅支持世界0、第1至20频道，并按CID选角。密码只从账号文件读取，建角由独立的首次登录流程完成。

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
| `bridge status/script status` | 只读桥、动作和脚本状态 |

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

```bash
private/workbenches/workbench /external/workbench walk right --seconds 0.2
private/workbenches/workbench /external/workbench script run --code 'game.log("你好，Lua"); game.sleep(0.1)' --seconds 20
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --seconds 20
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --continuous
private/workbenches/workbench /external/workbench script start --code 'while true do game.sleep(1) end' --continuous
private/workbenches/workbench /external/workbench script describe /work/scripts/hunt.lua
private/workbenches/workbench /external/workbench script run /work/scripts/hunt.lua --mob-id 1001001 --skill-id 1001005 --seconds 60
private/workbenches/workbench /external/workbench script cancel --session SCRIPT_ID
```

| 命令 | 支持与结果边界 |
| --- | --- |
| `walk DIR --seconds N`、`face DIR`、`jump` | 有界方向移动、朝向、跳跃尝试 |
| `attack`、`pickup`、`use_item ID` | 原生尝试；`use_item` 的消耗和恢复由后续观察确认 |
| `revive` | 无头发一次正常复活请求并确认同角色恢复；GUI 使用已识别死亡确认框；存活时跳过 |
| `click REF` | 无头激活当前原生控件或NPC目标引用；GUI保留既有引用与桌面点击流程 |
| `equip ITEM --slot SOURCE --to-slot TARGET [--seconds 3]` | 无头普通装备；明确背包正槽和身上负槽，核对物品 ID 及实际替换结果 |
| `unequip --slot SOURCE --to-slot TARGET [--seconds 3]` | 无头卸下普通装备；明确身上负槽和空背包正槽 |
| `stats STAT COUNT`、`skills SKILL [COUNT]` | 明确属性/技能与点数；两端 Lua 原生逐点双确认，GUI 复用本端必要窗口；未知或部分结果保留现状，按最新状态继续 |
| `move X`、`move X --to-y Y`、`climb X --to-y Y`、`portal NAME` | Lua执行同层对齐、单地图跨平台寻路、单根绳梯或单个门户；`move --to-y` 用静态平台图（走、跳台上升、落层、绳梯）行进，不支持跨地图自动选路 |
| `hunt [MOB\|all]` | 单场景自主找怪、可达跨平台和连续战斗；支持 `--skill ID`、`--range N`、限时或 `--continuous` |
| `script run/start --library travel\|island-supply` | 显式装载旅行函数；Lua消费者在一次会话内调用已知路线并核对目的地 |
| `use ITEM --count N`、`--until-hp N`、`--until-mp N` | 核对库存消耗与恢复；计数范围和组合以帮助/实际分类为准 |
| `script describe FILE` | 只读本地策略文件，输出 `main(context)` 入口、声明参数和动态 CLI 用法 |
| `script run/start FILE [策略参数]` | 带 `main(context)` 的文件按注释动态解析参数并接收场景上下文；无入口的文件仍作为原始 chunk 运行 |
| `script run FILE`、`script run --code CODE` | 原生会话同步等待结果；`--code` 始终按原始源码执行，中断等待时脚本继续运行，持续模式显式声明 |
| `script start FILE`、`script start --code CODE` | 原生受理后返回，脚本由客户端独立执行；返回实例、运行、请求与脚本身份 |
| `script cancel --session SCRIPT_ID` | 只取消当前匹配脚本，并等待原生停止和放键；旧脚本 ID 作为历史记录 |
| `task add/replace/stop` | 向指定活动Lua会话管理独立任务，不取得整会话动作锁 |
| `task result REQUEST_ID` | 只读查询已保留的任务管理结果，包括超时后补查的结果 |
| `stop`、`bridge stop` | 无其他活动动作控制者时清理遗留控制 |
| `key KEYS --seconds N` | 原版按键扩展；无头端按自身能力声明返回 |
| `skill ID` | 原生技能请求；无头首批1001004/1001005，其他类型明确不支持 |

[跨平台移动](../../shared/scripts/travel/walk_to.lua)只处理当前地图：按静态地形平台图计算最短平台路径，逐段执行走、跳台、落层与绳梯，落地后重新采样再规划。目标坐标必须落在平台范围内，`--plan-only` 只输出规划路径不输入；对话窗口打开、身份或地图变化、HP低于安全比例时明确失败并且不猜测结果。

`--code` 的值是完整 Lua 源码，按 shell 的引号规则作为一个参数传入；源码以 `--` 注释开头时使用 `--code='-- 注释…'` 的等号形式。直接源码保持原样执行，不解析策略注释。文件路径按容器内部解析；工作台整体已挂到 `/work`，用户 Lua 直接放在 `/work/scripts`，每次调用读取当前 UTF-8 文件内容。带顶层 `main(context)` 的文件是策略入口，`script run/start FILE` 会按注释校验参数并由原生 Runtime 调用入口；其他 Lua 文件保持原始 chunk 路径。两种方式都可在已运行实例中提交，沿用相同 `game` API、错误、时限和取消规则。`script status` 只接收 `--session`。源码模式的结果中 `script_file` 为 `null`；日志由原生端写入所属实例桥目录的 `script-events.jsonl`，游戏效果另行核对。

策略选项写在入口附近的 Lua 注释中；类型支持 `int`、`number`、`string`、`boolean`。非布尔参数没有 `opt` 或 `default` 时必填，声明默认值后可省略。布尔参数未声明 `default` 时可省略且默认为 `true`；显式 `default=false` 时省略则为 `false`。`min`/`max` 用于数值范围，`choices=a|b` 限定候选值。默认值、正向 flag 和显式值按 `choices` 校验，`--no-flag` 作为无值负向开关直接传入 `false`，不因 `choices` 未列出 `false` 而拒绝。Lua 参数名中的下划线映射为 CLI 连字符：

```lua
--- 在当前地图观察目标。
-- @option[type=int,min=1] mob_id 目标怪物模板 ID
-- @option[type=int,opt,default=1001005] skill_id 可选技能 ID
-- @option[type=boolean] observe_only 仅观察；省略时默认 true
-- @option[type=boolean,default=false] attack_enabled 默认关闭攻击
local function main(context)
    local map_id = context.scene.map_id
    game.log("map=" .. tostring(map_id)
        .. ", mob=" .. tostring(context.options.mob_id)
        .. ", observe_only=" .. tostring(context.options.observe_only)
        .. ", attack_enabled=" .. tostring(context.options.attack_enabled))
end
```

`script describe FILE` 显示动态参数帮助及有效默认值。布尔选项始终可省略：未显式声明 `default` 时默认 `true`，显式 `default=false` 时省略后为 `false`；裸 `--flag` 与 `--no-flag` 分别传入 `true`、`false`，也可显式写成 `--flag true|false`。默认值、正向 flag 和显式值按 `choices` 校验；负向 `--no-flag` 作为无值布尔开关直接传入 `false`，不因 `choices` 未列出 `false` 而拒绝。策略的 `context.options` 包含 CLI 值和声明默认值；`context.scene` 带有只读身份锚点 `instance_id`、`character_id`、`map_id`、`scene_generation` 及静态地形。`context.scene.terrain.status` 是 `available`、`unavailable` 或 `unsupported`；只有 `available` 时才提供有来源的 `footholds` 与 `ropes`。调用入口前会重新核对实例、角色、地图和场景代次；上下文过期时策略主体不运行。标准策略再次采样初始状态时也会与 `context.scene` 核对，避免预检后场景变化仍执行旧规划。动态角色状态继续通过 Lua API 查询。

策略自有的时间预算声明为 `budget_seconds`（CLI `--budget-seconds`），与控制整个原生脚本生命周期的 `--seconds` / `--continuous` 分开。仓库内旅行、战斗和恢复策略都使用标准 `main(context)` 与 `@option`；旅行策略装载时自动组合其共用的 `_common.lua`。函数库及普通 chunk 仍保留各自原始用途。

`script run` 同步等待会话结果，`script start` 等待原生受理。两者在等待期间收到 Ctrl+C/SIGINT/SIGTERM 都只结束本次等待，不取消已发布的原生任务；等待超时或观察失败只结束 CLI 等待，任务是否停止以当前状态为准。先用 `script status` 核对当前原生身份、`script.id` 与任务，结果未确认时先观察再决定。取消须明确 `script cancel --session SCRIPT_ID`，并核对终态与放键；客户端关闭另用 `close`。原生执行期限、角色变化、断线和脚本自身错误等停止规则保留。活动 Lua 仍占有本实例控制权，其他脚本和普通窗口输入返回 `input_busy`；`--continuous` 显式给出，持续控制在原生 Runtime 内执行。

在已有脚本会话中调整一项任务，先用 `script status` 取得 `script.id` 和该任务的 `revision`，再明确传给任务管理入口：

```bash
private/workbenches/workbench /external/workbench task add observer \
  --session SCRIPT_ID --priority 0 --code 'while true do game.log("观察中"); game.sleep(1) end'
private/workbenches/workbench /external/workbench task replace chase /work/scripts/chase.lua \
  --session SCRIPT_ID --revision 2 --priority 10
private/workbenches/workbench /external/workbench task stop chase \
  --session SCRIPT_ID --revision 3
private/workbenches/workbench /external/workbench task result REQUEST_ID
```

新增和替换必须提供 `--priority` 与文件或 `--code`，停止只提供任务名、`--session` 和预期 `--revision`。任务名是1至64字节的非NUL文本，可包含中文和空格；`main` 由整会话入口管理。新增使用会话内未占用的名称；替换为同名的新版本，分配新的 `revision`，旧版本历史仍可查看。停止已结束的当前版本返回 `changed=false`；旧版本请求返回版本不匹配，新版本保持运行。

任务源码直接作为独立chunk运行，共享本次会话的全局变量和 `game` API，局部变量按各自 chunk 隔离。动作任务先 `game.acquire()`，取得控制后重新采样与规划；原会话中已有的动作逻辑也需遵守这一多任务约定。替换先编译，编译失败保留旧任务及其输入；编译成功后停止旧版本，确认其输入释放后安装新版本。任一任务运行后的Lua错误继续停止整个会话；替换作用于后续执行，已发生的副作用按实际记录。

管理结果的 `completed` 表示任务已安装或指定版本已停止并完成其释放确认，实际游戏效果需另行观察；`control_released` 只针对被替换或停止的旧任务，其他任务仍可持有输入。`--timeout` 默认3秒，只限制本次管理等待。

请求发布前，例如等待 `task.lock` 时，Ctrl+C/SIGTERM返回通用 `interrupted` 和退出码130，此时没有已发布的 `request_id`；等待管理锁超时返回 `task_management_busy`。请求发布后，等待结果超时返回 `task_result_unconfirmed`，Ctrl+C/SIGTERM返回 `task_request_interrupted` 和退出码130，这两种结果都保留已发布的 `request_id`。管理等待失败时整会话继续运行，请求按一次发布处理；已发布的请求可用 `task result` 查询最终结果，再决定后续操作。查询结果属于响应中记录的历史实例和会话，当前角色效果另行观察。

移动和战斗参数只对当前场景有效。地形与恢复属性通过配置的只读原版 `Data/**/*.img` 和共享原生解析器读取；资料缺失或未支持时明确拒绝。`hunt` 根据当前位置在本场景连续寻找可达目标，允许正常换平台和空中攻击，地图或场景代次变化则停止。狩猎受成长节点限制。

```bash
private/workbenches/workbench /external/workbench hunt all --seconds 60
private/workbenches/workbench /external/workbench hunt 100100 --continuous --hp-item 2000000
private/workbenches/workbench /external/workbench hunt all --skill 1001004 --range 60 --seconds 30
```

`hunt` 默认普攻、全部怪物、60秒，`--bounds MIN MAX` 可限定横向区域，`--until-level` 指定停级，`--min-hp-ratio` 默认0.35。`--hp-item` 仅使用明确指定、库存已知的恢复品。技能必须已学且当前后端支持；无头首批仅支持战士 `1001004/1001005`，其他类型明确拒绝。狩猎不包含拾取或结束后撤退。攻击距离是策略接近参数，命中以实际战斗结果为准。无可确认的进展、不可通过的地形、生命下限或取消都有明确停止；原始日志保留所属实例，最终经验跨级时按等级与经验字段分别记录。

`hunt` 接受 `--first-job magician|warrior|bowman|thief|pirate`，只为本次新手练级明确首转路线：魔法师默认停8级，战士、弓箭手、飞侠、海盗默认停10级。`--until-level` 可以更早停止；高于明确转职节点时仍停在该节点，例如 `--first-job magician --until-level 10` 实际停8级。达到或超过已知节点后返回 `advancement_due`，本次装载到此结束。已转职角色依据当前职业沿用30/70/120级节点，`--first-job` 只作用于新手角色。

```bash
private/workbenches/workbench /external/workbench hunt all --first-job magician --seconds 60
```

新手路线未知时，两端 `status`/`snapshot` 的 `advancement.level`、`due` 为 `null`，`candidates` 列出各路线节点，前次命令的选择不写入状态。没有路线也没有 `--until-level` 时，`hunt` 先停在8级检查点；到达后再次默认调用返回 `advancement_route_required`，要求明确路线或本次目标。检查点只表示本次调用的停级。未知路线下显式给出的 `--until-level` 按调用方目标执行，包括10级；调用方按养成计划选择边界。

狩猎结果的 `requested_level` 是实际装载的停级，`advancement` 保留当前节点或未知候选，`stop_level_source` 区分 `advancement`、`first_job_checkpoint`、`until_level`。无适用节点且未明确停级时，`hunt` 不附加等级上限（`none`）。停级在Lua观察到等级达到或超过边界时生效；转职条件与加点由独立命令处理。

已知路线可在一个有界 Lua 内复用，接口与适用起点见 [Lua 旅行函数库](LUA_API.md#可选旅行函数库)。例如从50000东上层行进至相邻安全城镇：

```bash
private/workbenches/workbench /external/workbench script run --library island-supply --code 'local result = island_supply.to_town({seconds=30}); assert(result.arrived)' --seconds 35
```

`island_supply.to_field()` 从城镇西入口区域返回50000东下层。它只负责路线行进，购物、交任务、分配点数和战斗由各自命令完成。起点不符、有段未到达、意外转场或安全条件不足时停止，`route_failed` 保留 `arrived=false`、阶段和原因；原生动作错误同时保留最近的 `route_stage` 日志。成功返回表必须经过终点地图、区域和停止后的复采确认。CLI只组合源码，原生会话继续持有生命周期；`start`、等待中断及精确取消仍遵循同一规则。

在已知绳梯附近接续 `hunt` 时，策略可在总预算内恢复到狩猎边界内的已知端点，通过实际横移和平台位置复采确认脱绳后再找怪。日志 `hunt_rope_recovery` / `hunt_rope_recovered` 区分恢复尝试和已确认恢复；无安全端点、候选不唯一、遇阻或预算不足会明确停止。此行为不依赖 GUI 未知的 `settled`，可恢复范围以当前地形事实为准。

已知近距 `pt7` 脚本门户由原生 Up 输入走正常脚本门户请求，静态目标未知时保留未知，到达以在线地图和位置确认。通用路线规划与静态查询资料由各自的命令提供。

无头 `use` 接受数字ID的200类药品和201类食品。两端普通200类药品均走Lua原生用药，快捷键绑定无关；按次数使用只依赖库存，带HP/MP目标时需要资料已知恢复类型。

无头201类食品不带HP/MP目标时为明确单次消费，仅接受 `--count 1`（默认值），满HP/MP仍会提交一次。该路径只依赖库存；结果 `effect="consumption"`、`effect_confirmed=true` 表示库存已恰减一。前后HP/MP分别保留，观察到增长时 `recovery_confirmed=true`，未观察到增长时为 `null`，恢复效果以实际数值为准。`healing_metadata_known` 与 `metadata_unavailable` 说明静态恢复资料的已知范围。带HP/MP目标时沿用有界恢复流程，仍需资料已知恢复类型。

`use_item ID` 及 `game.use_item(ID)` 只报告单次原生派发，食品消耗和恢复须由后续观察确认。GUI其他已支持恢复品保留背包工作流；203类传送卷仅支持GUI单次使用，不接受HP/MP目标。

无头 `equip` 要求数字物品 ID、装备背包源正槽和身上目标负槽；Lua 先读取库存，核对该源槽仍是明确指定的物品。目标已有普通装备时，正常替换将其放回源槽。`unequip` 要求明确源负槽和空背包目标正槽。两者通过共享 Lua 发起一次正常装备请求，在无头原生更新中等待源、目的槽位对象变化。`--seconds` 默认3秒，范围为0.001至30秒；超时、取消、接管或换图保持未确认事实，请求按一次派发处理。随后先读取最新背包和身上槽位，再决定下一步。

CLI 仅在脚本 `status="completed"` 且最终 `action_result.effect="confirmed"` 时返回 `confirmed=true`。脚本正常完成但槽位效果未知时，报 `equipment_change_unconfirmed`，错误详情保留本次结果；`cancelled` 等终态按实际终态返回。Python 只负责参数、Lua 装载/取消和终态投影，换装反馈由原生库存更新提供。

原版 `equip ITEM` 保留原有 GUI 工作流，新增原生槽位参数供无头使用；`unequip` 由无头端的槽位参数提供。换装覆盖普通装备，强化、现金外观和其他装备操作按各自命令处理。

`skill` 保留 `native_result`、`dispatched/skill_reason` 和未知效果，顶层 `reason` 继续表达脚本终态。原生数值含义随后端不同：无头枚举0表示准入，GUI保留原返回值，命中以实际战斗结果为准。需要停止活动脚本时，先读取当前 `script.id`，显式 `script cancel --session` 并等待终态和放键；其他动作命令在控制权释放后执行。脚本能力及效果判断见 [CONTROL](CONTROL.md)。

无头 `snapshot` 与 `bridge status` 提供 `dead/revive_requestable`：死亡来自已就绪角色的原生 HP=0；读数不可用时保持未知。`revive_requestable` 表示客户端请求前置已满足，服务端许可由实际请求结果确认。无头 `revive` 通过共享 Lua 默认等待至多6秒，只有同角色 HP>0 且地图、位置有效才返回 `revived`；存活返回 `already_alive`，请求按一次执行。未确认返回 `revive_not_confirmed`，取消/断线保留实际结果；死亡观察只报告状态。参数化等待及脚本用法见 [Lua API](LUA_API.md#无头正常复活)。

## 无头控件交互

先用 `snapshot` 观察 `interaction.page` 的正文和控件，再对选定控件执行一次 `click REF`；场景NPC的原生 `ref` 也使用同一激活入口。`REF` 必须替换为当前观察到的引用：

```bash
private/workbenches/workbench /external/workbench snapshot
private/workbenches/workbench /external/workbench click CONTROL_REF
```

页面只有 `source/title/text/controls`，控件只有 `role/text/enabled/ref`。正文或控件未知时为 `null`，`enabled=null` 保持未知。引用由原生单点生产和验证；CLI 原样传递引用，失效引用按当前页面重新读取。`--double` 与坐标点击仅GUI可用。

激活只报告控件处理或页面变化，任务完成、奖励和消费到账随后用当前交互页、`inspect quests`、背包及角色核对。服务端普通脚本页和客户端本地任务页使用同一入口。本地页只显示当前状态能证明的任务条目，先读取真实资料详情，再激活确认控件；资格未知时确认控件保持不可用。缺少原版 Quest IMG 只影响本地任务界面；任务接交由通用控件交互完成。

任务观察已合并完整角色包与本端正常增量，`live_updates=true`，`live_update_kinds` 为 `not_started/started/completed`。原生观察保留原始进度串，关联语义未核实，`linked_progress=null`；持续观察由本端正常增量提供。

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
| `talk TARGET`、`dialog` | 原版已有NPC桌面消费者；无头使用通用控件交互 |
| `ui read/open/close/focus` | 已识别窗口和输入焦点；`ui close all`同时处理普通商店 |
| `equip ITEM` | 普通唯一槽位走 Lua 并核对原生对象；多目标/特殊槽位保留既有 GUI 自动选择，不接受无头槽位参数 |
| `hotkeys`、`bind`、`press` | 读取、拖放绑定和按已有物品/技能快捷键 |
| `shop read/buy/sell/close` | 普通商店读取与指定买卖；数量框和关店按实际UI收尾 |
| `screenshot [NAME]`、`record NAME` | 当前窗口截图或有界逐帧记录，不发游戏输入 |

引用来自本次快照，换图、对话翻页、重登或目标变化后重新读取。任务/奖励、消费、加点和交易按一次派发处理；以当前完整正文和实际变化判断。GUI输入只允许一名明确操作者。

## 有限批次

`batch [--file PATH]` 接受非空JSON参数数组，先解析全部CLI参数，再顺序执行。批次绑定当前实例，嵌套 batch 按错误拒绝。进度写stderr，最终仍是单个JSON；批内watch收为最终状态。

某一步抛错时立即停止，错误详情含从0开始的 `index`、此前 `completed` 和原始 `cause`，已发生效果按实际保留。子命令正常返回预算停止或取消状态时批次继续；批次用于编排无需中途决策的有限步骤，持续控制写Lua。
