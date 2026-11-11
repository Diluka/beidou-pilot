# 命令使用

唯一宿主入口是 [private/workbenches/workbench](../private/workbenches/workbench)，它直接调用 Git、Docker 和 jq。使用 `private/workbenches/workbench DIR COMMAND` 指定一个账号角色的工作目录；两个镜像中的客户端命令仍叫 `beidou-pilot`，由宿主入口通过 `docker exec` 执行。

## 工作目录配置

工作目录必须已存在。普通工作目录只维护 `account.json` 和需要的新建设置 `workbench.json`，养成计划、交接、用户 Lua 和运行数据也放在该目录。资源路径共用主检出目录中的 `private/workbenches/resources.json`，字段示例见 [resources.example.json](../cli/config/resources.example.json)。从开发 worktree 调用时也读取这份公共配置。

常驻服务器的项目、服务与公开镜像引用固定在统一入口中。启动器核对真实服务器容器及其镜像；普通目录没有人工维护的 `server.json`，也不接受宿主服务器路径、账号路径或资源路径覆盖参数。固定目标不能替代本次玩法授权及账号占用核对。

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
| `model_proxy` | 可选的 `http://IPv4:端口` 模型 HTTP 代理；省略不影响客户端和脚本，模型 API 地址仍在 provider 配置中 |

调试和实际游戏验收默认复用常驻服务器与已授权的已有账号角色，只有场景必须时才新建账号或角色。确需隔离服时记录原因，其 `server` 要求 `project/service/expected_image`，`network` 可选。项目必须不是 `beidou-ms`，隔离服务器不能发布宿主端口或使用host网络；指定网络时必须是同项目 internal 网络并且服务器已连接。省略网络时，启动器为新实例建立所属 internal 连接并在关闭时回收。例如：

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

启动设置仅在新建时读取。一个目录对应一个账号角色和容器，宿主实例名固定为 `default`；原生 `instance_id/run_id` 核验继续保留。已有容器的 `status/script/close` 依赖目录下的运行登记和实际容器，不因新建配置被修改而换版本。

## 版本、挂载与输出

新实例一次解析 `main` 或 `workbench.json.ref` 的已提交 SHA，以该树及固定子模块构建或复用所选后端镜像。构建期间更新代码不改变本次输入。已有实例继续运行启动时的 CLI、内置 Lua 和原生组件，实际版本查 `status` 的 `source_revision/image/run_id`。

`build` 保留 `data.image/source_revision/backend`，并在 `data.preparation` 中报告实际执行的准备阶段：

| 阶段 | 可核对的结果 |
| --- | --- |
| `context` | 源码上下文新建或复用，固定提交、源码树及子模块提交 |
| `bridge`（GUI） | CI 下载、已有工件或镜像内清单的来源；直接附带原有 manifest 中的目标指纹、桥指纹、依赖和工具链 |
| `client_image` | 客户端镜像新建或复用，实际标签和镜像 ID |
| `harness_image`（启用时） | 派生镜像新建或复用，实际标签和镜像 ID |

每个阶段包含 `outcome` 和 `duration_ms`。耗时是本次阶段的实际用时，镜像构建内部的层缓存仍由 Docker 构建日志说明。准备失败保留既有错误码，并在 `error.stage` 定位失败阶段；外部命令诊断写到 stderr，stdout 返回一个 JSON 结果及已完成阶段。

`data.current_instance` 在没有所属容器时为 `null`，存在时报告实际容器、镜像、运行身份及 `matches_prepared_image`。`native_inputs_match` 按对应后端原生源码输入比较，文档变更导致镜像 ID 不同时也能判断原生输入是否相同；后端不同或本地缺少来源树时为 `null`。这个比较不表示 CLI、策略或整个镜像相同。`build` 只准备产物，切换已有实例仍需明确的 `close/open`。

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

只给工作目录时默认只读 `status`。`notes` 只读已有 README、PLAN、HANDOFF 和脚本说明；`plan` 只读核对目标，不构建或启动。`build` 可提前准备镜像，`open` 自行构建或复用镜像，并确认本容器已入图。已有正确实例直接观察、接续，不需重建或重复登录。

两端使用同一份权限为 `0600` 的 `account.json`：必填 `username`、`password`、已有角色 `character_id`（正 int32），可选 `world/channel` 为0基索引，默认各为0。GUI 仅支持世界0、第1至20频道，并按CID选角。密码不进入参数或日志，`open` 不自动建角。

启动器把账号与已解析的服务器配置自动保存到 `runtime/default/RUN_ID/account.json`、`server.json`。容器入口读取该快照、生成内部资源映射与 `state/container.json`，再运行原生进程。随后宿主向容器内 `open` 传入这两个快照路径，完成或确认登录；容器 CLI 的 `--server` 仅核对已有实例的服务器，不切换连接。日常只维护工作目录根的账号和新建设置，运行快照由启动器管理。

已核验目标公告频道 IPv4 为 `127.0.0.0/8` 时，无头端使用该目标内部IP并保留公告端口；其他地址沿用公告。该映射不修改服务端或原资源。

| 命令 | 行为 |
| --- | --- |
| `build` | 构建或复用所选版本镜像 |
| `plan` | 只读核对授权目标，不构建或启动 |
| `resources-check` | 用headless镜像离线检查公共NX，无需账号或服务器，不启动或切换现存实例 |
| `status` | 报告未运行实例；运行时由容器CLI读取实时阶段与版本 |
| `doctor` | 在已有容器内检查资源和读取能力 |
| `instances` | 返回当前容器实例身份与版本 |
| `capabilities` | 读取原生能力和静态观察支持范围 |
| `open/close` | 新建或接续所属实例；正常停止、确认退出并回收 |
| `ai [harness参数]` | 通过 `docker exec` 运行所属容器内的 `beidou-game-ai`；要求已有 harness 镜像实例 |
| `snapshot [-i] [--all]` | 当前角色、场景、领域摘要与引用 |
| `inspect KIND [ID]` | 按需领域读数或静态资料 |
| `watch --seconds N --interval N` | 持续只读状态，JSONL输出 |
| `events read/watch` | 当前实例原生事件；GUI同类通知气泡提供，无头明确不支持 |
| `bridge status/script status` | 只读桥、动作和脚本状态 |

动作、脚本等客户端参数直接跟在命令后，不是宿主启动配置。比如 `script run FILE --seconds 20` 的文件路径按容器内部解释。核对容器归属后可用 `docker exec CONTAINER beidou-pilot --json status` 只读排查。中断脚本 CLI 只结束等待，脚本取消另行显式 `script cancel --session`。

短脚本返回或取消后容器继续运行。`close` 独立于输入锁，经Docker正常发SIGTERM，确认 `Running=false/Pid=0` 后保存退出日志并回收；活动Lua不阻挡关闭。容器内 `close` 返回 `host_lifecycle_required`。同一目录正在启停为 `lifecycle_busy`，活动脚本期间其他动作是 `input_busy`；失败先读状态和所属日志再决定重开。

## 游戏 AI

新建设置 `harness=true` 后，`build/open` 先准备对应 headless 或 GUI base，再构建或复用同提交的 harness 衍生镜像；客户端保持原 PID1。只有配置了非空 `model_proxy` 的 harness 客户端额外连接默认 `bridge`，GUI 才增加该代理 IP/端口白名单，游戏服务器的 internal 网络不变。

```bash
private/workbenches/workbench /external/workbench ai \
  --state /work/ai/state --role /work/ai/role.md \
  --auth-file /work/ai/auth.json --task '先观察当前角色和场景' --paused
```

`--state/--role/--provider-config/--auth-file` 均为容器内路径，常驻状态放在 `/work` 下；`--cli` 仅指定容器内客户端路径。已有普通镜像返回 `harness_image_required`，修改新建配置不会给运行中的镜像安装 harness。普通 agent 通过 shell 直接使用 CLI，只读模式关闭 shell。LLM 独立启停不联动取消脚本或关闭客户端，重新接入先观察现有任务；具体协作、状态续接与参数见 [HARNESS](HARNESS.md)。

## 离线检查资源

```bash
private/workbenches/workbench /external/workbench resources-check
```

该命令固定选择headless镜像，读取公共资源配置并只读检查NX，不读取账号、不连接游戏服务器，也不创建或切换已有客户端。GUI工作目录也可使用，无需修改其后端设置。

## 客户端事件

```bash
private/workbenches/workbench /external/gui-workbench events read
private/workbenches/workbench /external/gui-workbench events watch
private/workbenches/workbench /external/gui-workbench events watch \
  --cursor '{"instance_id":"本次原生实例","run_id":"本次运行","seq":12}' --seconds 30
```

`events read` 返回当前保留区的 `events`、`first_seq/last_seq` 和完整 `cursor`；给定游标时只返回其后的事件。游标由 `instance_id/run_id/seq` 三字段组成，必须原样保留身份，不能只保存数字序号。事件带 `seq/observed_at_ms/scene_generation/character_id/type/source/expires_at_ms/data`；未知角色或期限为 `null`，`observed_at_ms` 是客户端捕获时间。

`events watch` 在取得首个新鲜基线后输出 `event="events_ready"` 及游标，随后每条 `event="client_event"` 的 `data` 保存完整原生事件，`cursor` 指向该条。无游标时从订阅时刻之后开始；给定游标时先输出就绪，再补发保留区内的后续事件。已有未处理气泡须另读当前 notifications，不能把历史气泡当成仍有效。默认持续监听，可用 `--seconds` 有界退出；`--interval` 默认为0.025秒，范围为0.01至1秒。中断监听只结束读者，不取消 Lua 或关闭客户端。

绑定身份后的持续监听遇到暂时失效采样引发的 `stale_bridge_state` 时，保留游标等待新鲜采样，不投递旧文件中的事件。同一不可用期间只输出一条 `event="events_unavailable"` 流诊断；恢复后输出 `events_ready` 并从原游标继续。首次基线尚未建立时诊断中的 `cursor=null`。这些流诊断不代表新气泡；等待仍遵守 `--seconds` 和取消。单次 `events read` 保留明确失败，身份、协议及其他错误仍使监听退出。

原生保留最近128条事件，每个读者独立持有游标。落后于保留区返回 `events_gap`，须重新观察当前事实；身份变化返回 `events_identity_changed` 并停止，不跟随后继实例。旧桥及无头尚未提供通知气泡事件时返回 `unsupported_capability`；原生报告事件发布失败时返回 `events_unavailable`，不把旧文件当成正常事件流。事件通知不代表游戏操作完成：`notification.opened` 提示发现气泡，`notification.closed` 表示该气泡不再待处理，关闭载荷的 pending/available 均为 false；`notification.observation_unavailable` 表示本端未能继续观察。事件本身不代表任何后续业务完成。

## 原生通知气泡

```bash
private/workbenches/workbench /external/gui-workbench notifications
private/workbenches/workbench /external/gui-workbench notifications respond @notificationCURRENT --button 2000
private/workbenches/workbench /external/gui-workbench notifications respond @notificationCURRENT --button 2001
```

`notifications` 统一列出同一原生气泡类的所有种类，包含好友、组队、交易、任务、快递等；未识别种类保留整数 `native_kind`，`kind=null`，不会静默忽略。来源槽的原始文字为 `source_text`；已证实的玩家、队伍、交互或任务标识分别保留，未知为 `null`。交易 `interaction_id` 不是发送者 ID。完整气泡正文尚未提取，`text=null`、`not_covered` 包含 `rendered_body_text`，需要时用当前截图辅助，不能拼模板冒充屏幕原文。

气泡保留 `pending/available`、`expires_at_ms/remaining_ms`、当前 `window` 和真实 `buttons`。原生 duration 为0时两个期限字段为 `null`，不被误判为过期；这不证明服务端业务永远有效。按钮保留实际 `control_id` 和位置，2000标为 `primary`，2001标为 `dismiss`，其他语义未知。某些气泡只有关闭按钮；主按钮可能接受邀请、打开快递或进入后续确认界面，不能一律解释为“接受”。

响应必须使用本次读取的 `ref` 和实际存在的 `--button`，引用绑定原生实例、运行和场景代次。过期、关闭或不可响应时返回 `stale_notification`，缺少按钮返回 `notification_button_unavailable`，不会改点另一个按钮。GUI 使用当前控件位置，不重放固定桌面坐标。

返回的 `input_dispatched=true` 仅确认本轮桌面输入已派发；`after` 分别报告气泡是否还在、是否仍待处理及可响应，`effect` 保持 `unknown`。主按钮操作后气泡仍在也不报成失败，不自动再次点击。输入派发后采样不可用时，结果保留该事实并返回 `observation_error`，不能当作未发送而重放。

业务结果另外核对：实际入队需要成员状态，接受交易邀请需要确认交易窗口，最终成交则是不同动作，需要独立明确授权；气泡消失不能替代这些结果。本接口不提交物品、金币或确认成交。组队成员接口和真实核验继续由 [#92](https://github.com/Diluka/beidou-pilot/issues/92) 完成，不作为公共气泡响应的内置分支。无头端明确不支持 GUI 气泡。

## 动作与 Lua

```bash
private/workbenches/workbench /external/workbench walk right --seconds 0.2
private/workbenches/workbench /external/workbench script run --code 'game.log("你好，Lua"); game.sleep(0.1)' --seconds 20
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --seconds 20
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --continuous
private/workbenches/workbench /external/workbench script start --code 'while true do game.sleep(1) end' --continuous
private/workbenches/workbench /external/workbench script cancel --session SCRIPT_ID
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
| `script run/start --library travel\|island-supply` | 显式装载旅行函数；Lua消费者在一次会话内调用已知路线并核对目的地 |
| `use ITEM --count N`、`--until-hp N`、`--until-mp N` | 核对库存消耗与恢复；计数范围和组合以帮助/实际分类为准 |
| `script run FILE`、`script run --code CODE` | 文件或直接源码二选一，同步等待原生会话结果；中断等待不取消脚本，持续模式须明确声明 |
| `script start FILE`、`script start --code CODE` | 原生受理后返回，脚本由客户端独立执行；返回实例、运行、请求与脚本身份 |
| `script cancel --session SCRIPT_ID` | 只取消当前匹配脚本，并等待原生停止和放键；旧脚本 ID 不发送取消 |
| `task add/replace/stop` | 向指定活动Lua会话管理独立任务，不取得整会话动作锁 |
| `task result REQUEST_ID` | 只读查询已保留的任务管理结果，包括超时后的结果 |
| `stop`、`bridge stop` | 无其他活动动作控制者时清理遗留控制 |
| `key KEYS --seconds N` | 原版按键扩展；无头明确拒绝 |
| `skill ID` | 原生技能请求；无头首批1001004/1001005，其他类型明确不支持 |

`--code` 的值是完整 Lua 源码，按 shell 的引号规则作为一个参数传入；源码以 `--` 注释开头时使用 `--code='-- 注释…'` 的等号形式。CLI 不拼接、展开或改写源码。文件路径按容器内部解析；工作台整体已挂到 `/work`，用户 Lua 直接放在 `/work/scripts`，文件方式每次读取当前 UTF-8 内容。两种方式都可在已运行实例中提交，无需重新构建或重启客户端，沿用相同 `game` API、错误、时限和取消规则。`script status` 不接收文件或 `--code`。源码模式的结果中 `script_file` 为 `null`；日志由原生端写入所属实例桥目录的 `script-events.jsonl`，不作为游戏效果确认。

`script run` 同步等待会话结果，`script start` 等待原生受理。两者在等待期间收到 Ctrl+C/SIGINT/SIGTERM 都只结束本次等待，不取消已发布的原生任务；等待超时或观察失败同样不能证明任务停止。先用 `script status` 核对当前原生身份、`script.id` 与任务，不因结果未知而重放启动。取消须明确 `script cancel --session SCRIPT_ID`，并核对终态与放键；客户端关闭另用 `close`。原生执行期限、角色变化、断线和脚本自身错误等停止规则保留。活动 Lua 仍占有本实例控制权，其他脚本和普通窗口输入返回 `input_busy`；`--continuous` 须显式给出，不增加后台 Python 控制进程。

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

新增和替换必须提供 `--priority` 与文件或 `--code`，停止只提供任务名、`--session` 和预期 `--revision`。任务名是1至64字节的非NUL文本，可包含中文和空格；`main` 由整会话入口管理。新增不能复用会话历史中的名称；替换为同名的新版本，分配新的 `revision`，旧版本历史仍可查看。停止已结束的当前版本返回 `changed=false`；旧版本请求被拒绝，不会停止新版本。

任务源码直接作为独立chunk运行，共享本次会话的全局变量和 `game` API，不能访问旧任务的局部变量。动作任务先 `game.acquire()`，取得控制后重新采样与规划；原会话中已有的动作逻辑也需遵守这一多任务约定。替换先编译，编译失败保留旧任务及其输入；编译成功后停止旧版本，确认其输入释放后安装新版本。任一任务运行后的Lua错误继续停止整个会话，不能把替换理解为执行副作用可回滚。

管理结果的 `completed` 表示任务已安装或指定版本已停止并完成其释放确认，实际游戏效果需另行观察；`control_released` 只针对被替换或停止的旧任务，其他任务仍可持有输入。`--timeout` 默认3秒，只限制本次管理等待。

请求发布前，例如等待 `task.lock` 时，Ctrl+C/SIGTERM返回通用 `interrupted` 和退出码130，此时没有已发布的 `request_id`；等待管理锁超时返回 `task_management_busy`。请求发布后，等待结果超时返回 `task_result_unconfirmed`，Ctrl+C/SIGTERM返回 `task_request_interrupted` 和退出码130，这两种结果都保留已发布的 `request_id`。管理等待失败不停止整会话，也不自动重放请求；已发布的请求可用 `task result` 查询最终结果，再决定后续操作。查询结果属于响应中记录的历史实例和会话，不代表当前角色效果。

移动和战斗参数只对当前场景有效。地形与恢复属性优先使用已配置 XML，缺少对应 XML 时使用同源 NX；资料缺失或未支持时明确拒绝。基础 `fight` 保留同层预算与撤退行为；`hunt` 根据当前位置在本场景连续寻找可达目标，允许正常换平台和空中攻击，地图或场景代次变化则停止。两者均保留成长节点限制。

```bash
private/workbenches/workbench /external/workbench hunt all --seconds 60
private/workbenches/workbench /external/workbench hunt 100100 --continuous --hp-item 2000000
private/workbenches/workbench /external/workbench hunt all --skill 1001004 --range 60 --seconds 30
```

`hunt` 默认普攻、全部怪物、60秒，`--bounds MIN MAX` 可限定横向区域，`--until-level` 指定停级，`--min-hp-ratio` 默认0.35。`--hp-item` 仅使用明确指定、库存已知的恢复品，不购买或替换药品。技能必须已学且当前后端支持；无头首批仅支持战士 `1001004/1001005`，其他类型明确拒绝。攻击距离是策略接近参数，不保证命中。无可确认的进展、无法通过的地形、生命下限或取消都有明确停止；原始日志保留所属实例，最终经验跨级时不直接相减。

已知路线可在一个有界 Lua 内复用，接口与适用起点见 [Lua 旅行函数库](LUA_API.md#可选旅行函数库)。例如从50000东上层行进至相邻安全城镇：

```bash
private/workbenches/workbench /external/workbench script run --library island-supply --code 'local result = island_supply.to_town({seconds=30}); assert(result.arrived)' --seconds 35
```

`island_supply.to_field()` 从城镇西入口区域返回50000东下层。它不会购物、交任务、分配点数或继续战斗。起点不符、有段未到达、意外转场或安全条件不足时停止，`route_failed` 保留 `arrived=false`、阶段和原因；原生动作错误同时保留最近的 `route_stage` 日志。成功返回表必须经过终点地图、区域和停止后的复采确认。CLI只组合源码，原生会话继续持有生命周期；`start`、等待中断及精确取消仍遵循同一规则。

在已知绳梯附近接续 `hunt` 时，策略可在总预算内恢复到狩猎边界内的已知端点，通过实际横移和平台位置复采确认脱绳后再找怪。日志 `hunt_rope_recovery` / `hunt_rope_recovered` 区分恢复尝试和已确认恢复；无安全端点、候选不唯一、遇阻或预算不足会明确停止。此行为不依赖 GUI 未知的 `settled`，也不保证所有地形都可恢复。

已知近距 `pt7` 脚本门户由原生 Up 输入走正常脚本门户请求，静态目标未知时保留未知，到达以在线地图和位置确认。它不补齐通用路线规划或缺失的静态查询资料。

无头 `use` 接受数字ID的200类药品和201类食品。两端普通200类药品均走Lua原生用药，不要求快捷键绑定；按次数使用可不依赖XML，带HP/MP目标时需要资料已知恢复类型。

无头201类食品不带HP/MP目标时为明确单次消费，仅接受 `--count 1`（默认值），满HP/MP仍会提交一次。它不依赖可选XML；结果 `effect="consumption"`、`effect_confirmed=true` 只表示库存已恰减一。前后HP/MP分别保留，观察到增长时 `recovery_confirmed=true`，否则为 `null`，不能把满血消费说成恢复成功。`healing_metadata_known` 与 `metadata_unavailable` 说明静态恢复资料的已知范围。带HP/MP目标时沿用有界恢复流程，仍需资料已知恢复类型。

`use_item ID` 及 `game.use_item(ID)` 只报告单次原生派发，食品消耗和恢复须由后续观察确认。GUI其他已支持恢复品保留背包工作流；203类传送卷仅支持GUI单次使用，不接受HP/MP目标。

无头 `equip` 要求数字物品 ID、装备背包源正槽和身上目标负槽；Lua 先读取库存，核对该源槽仍是明确指定的物品。目标已有普通装备时，正常替换将其放回源槽。`unequip` 要求明确源负槽和空背包目标正槽。两者通过共享 Lua 发起一次正常装备请求，在无头原生更新中等待源、目的槽位对象变化。`--seconds` 默认3秒，范围为0.001至30秒；超时、取消、接管或换图保持未确认事实，不自动重试，也不撤销已派发请求。随后先读取最新背包和身上槽位，再决定下一步。

CLI 仅在脚本 `status="completed"` 且最终 `action_result.effect="confirmed"` 时返回 `confirmed=true`。脚本正常完成但槽位效果未知时，报 `equipment_change_unconfirmed`，错误详情保留本次结果；`cancelled` 等终态不会被标为确认成功。Python 只负责参数、Lua 装载/取消和终态投影，不轮询执行换装反馈。

原版 `equip ITEM` 保留原有 GUI 工作流，新增原生槽位参数供无头使用；原版不支持 `unequip`。换装只覆盖普通装备，不扩展强化、现金外观或其他装备操作。

`skill` 保留 `native_result`、`dispatched/skill_reason` 和未知效果，顶层 `reason` 继续表达脚本终态。原生数值含义随后端不同：无头枚举0表示准入，GUI保留原返回值，不能仅凭零或非零判断命中。需要停止活动脚本时，先读取当前 `script.id`，显式 `script cancel --session` 并等待终态和放键；不要用第二个动作命令抢占。脚本能力及效果判断见 [CONTROL](CONTROL.md)。

无头 `snapshot` 与 `bridge status` 提供 `dead/revive_requestable`：死亡来自已就绪角色的原生 HP=0；读数不可用时保持未知。`revive_requestable` 只表示客户端请求前置已满足，不能预判事件脚本许可。无头 `revive` 通过共享 Lua 默认等待至多6秒，只有同角色 HP>0 且地图、位置有效才返回 `revived`；存活返回 `already_alive`，均无重复请求。未确认返回 `revive_not_confirmed`，取消/断线保留实际结果；检测到死亡本身不触发复活或重连。参数化等待及脚本用法见 [Lua API](LUA_API.md#无头正常复活)。

## 无头控件交互

先用 `snapshot` 观察 `interaction.page` 的正文和控件，再对选定控件执行一次 `click REF`；场景NPC的原生 `ref` 也使用同一激活入口。`REF` 必须替换为当前观察到的引用：

```bash
private/workbenches/workbench /external/workbench snapshot
private/workbenches/workbench /external/workbench click CONTROL_REF
```

页面只有 `source/title/text/controls`，控件只有 `role/text/enabled/ref`。正文或控件未知时为 `null`，`enabled=null` 不改成 `false`。引用由原生单点生产和验证；CLI不解析引用、不按控件角色拼协议参数，也不自动重新选择或重放失效引用。`--double` 与坐标点击仍仅GUI可用。

激活只报告控件处理或页面变化，不能当作任务完成、奖励或消费到账；随后用当前交互页、`inspect quests`、背包及角色核对。服务端普通脚本页和客户端本地任务页使用同一入口。本地页只显示当前状态能证明的任务条目，先读取真实资料详情，再激活确认控件；无法确认的资格不产生可用确认。缺少 `Quest.nx` 只影响本地任务界面；不根据任务ID制造菜单，不增加直接接交的内容命令。

任务观察已合并完整角色包与本端正常增量，`live_updates=true`，`live_update_kinds` 为 `not_started/started/completed`。原生观察保留原始进度串，关联语义未核实，`linked_progress=null`；不靠重登刷新代替持续观察。

## 原版 GUI

GUI 镜像包含与无头端相同的CLI与Lua，以及Wine/VirtualGL和匹配的桥DLL。其资源路径仍从公共 `private/workbenches/resources.json` 读取，原版 `/client` 与NX `/data` 不迁移或改格式。工作目录的 `workbench.json` 设置 `backend="beidou"` 后，使用相同入口：

```bash
private/workbenches/workbench /external/gui-workbench build
private/workbenches/workbench /external/gui-workbench open
private/workbenches/workbench /external/gui-workbench doctor
private/workbenches/workbench /external/gui-workbench snapshot
private/workbenches/workbench /external/gui-workbench close
```

[Compose](../docker/compose.yaml) 装配所选版本的 GUI 实例。原客户端只读挂到 `/client`，镜像内的桥位于 `/opt/beidou-pilot/native/ijl15.dll`。容器在 `$CLIENT_ROOT/client` 生成可写运行副本，`Data/` 读取原只读目录，`2ijl15.dll` 图片库仍保留；外部原始文件不被修改。CLI、桌面输入和录制直接使用本容器的桥和显示环境，无 Docker socket。

GUI 容器在自身网络命名空间启用回环游戏端口 NAT，连接已核验目标，不修改服务端公告地址。Wine prefix、运行日志和桥数据位于本次 `$CLIENT_ROOT/runtime/` 下，由工作台持久化，需允许 `1000:1000` 读写。硬件路径使用 `/dev/dri/renderD128`、`DISPLAY=:97` 的 `1920x1080x24` Xvfb 和窗口管理器、VirtualGL EGL；Wine 虚拟桌面提供原客户端所需显示模式。GUI启动诊断日志写入本次运行目录。

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
