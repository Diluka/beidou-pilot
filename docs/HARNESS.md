# Codex 游戏 AI

`harness/` 是可选的 LLM 旁路控制端，负责模型会话、角色设定、目标与游戏经历。它随所选 headless 或 GUI 客户端镜像打包，在同一容器中启动本地 Codex app-server；普通模式的 agent 通过 shell 直接调用 `beidou-pilot`。客户端、Lua 与 LLM 并行运行、独立启停，没有 LLM 时客户端和已启动脚本继续工作。CLI、原生适配器与 Lua Runtime 保持各自职责边界。

准备授权角色、核对占用和交接按[操作指引](PLAY_GUIDE.md)执行。harness 专注模型会话与协作；账号准备和容器生命周期由[统一入口](CLI.md#启动观察与关闭)管理。

## 准备与启动

在角色工作目录的 `workbench.json` 开启 harness，将可选 LLM 工具随客户端打包。模型 HTTP 代理与 harness 独立配置，按需填写：

```json
{
  "harness": true
}
```

`harness` 省略时取默认值 `false`；GUI 目录另设 `backend="beidou"`。统一入口先从选定提交构建或复用对应客户端 base，再用同一提交的 `docker/harness/Dockerfile` 派生 harness 镜像。继承只用于打包复用：Node/Codex、Python harness 和专用客户端技能随镜像固定，客户端原有 ENTRYPOINT、CMD 与 PID1 保留，客户端可独立启动。根上下文的离线构建方式见 [CI](CI.md#本地复现) 和[镜像说明](../docker/harness/README.md)。

可选的 `model_proxy` 以 `http://IPv4:端口` 指定 HTTP/HTTPS 出口代理，模型 API 地址由 provider 配置提供。只有 harness 客户端配置了非空代理，才额外连接 Docker 默认 `bridge`；GUI 防火墙只额外放行该代理 IP/端口。游戏服务器继续只使用原有 internal 目标网络，原版客户端 `/client` 与只读 `Data/` `/data` 挂载保持独立。

先启动客户端，再在所属容器内运行 harness：

```bash
private/workbenches/workbench /external/workbench open
private/workbenches/workbench /external/workbench ai \
  --state /work/ai/state --role /work/ai/role.md \
  --auth-file /work/ai/auth.json \
  --task '先观察当前角色和场景，再执行已有授权中的有界动作并核对停止结果'
```

宿主 `ai` 只通过 `docker exec` 启动已有客户端容器内的 `beidou-game-ai`。已有普通镜像会明确返回 `harness_image_required`；需要 harness 时，按新配置关闭并重建实例，运行中的 CLI 与内置策略保持启动时的版本。进入容器后也可直接执行 `beidou-game-ai`，客户端观察和动作直接使用本容器的 `beidou-pilot`。

`--state`、`--role`、`--provider-config`、`--auth-file` 均为容器内路径。将常驻状态放在 `/work` 下，确保所属容器运行身份可读写。角色文件为 UTF-8 文本，仅保留所需角色设定、养成方案与操作边界；认证使用专用文件或容器显式提供的 API 认证环境。认证和 provider 配置单独存放，私密状态与经历保留在私密状态目录。

`--cli` 默认选择镜像已安装的客户端 CLI，可为开发验证指定另一容器内 CLI 路径。`--paused` 在初始化后等待 `resume`，`--read-only` 仅观察输入状态。stdin/stdout 是专用 JSONL 协作通道；结束本次 LLM 会话时脚本与客户端保持运行。

默认模型为 `gpt-6-luna`，只允许显式改选 `gpt-6.1-terra`。启动从当前身份的 `model/list` 核对模型和 effort，优先 `none`，否则选择其支持清单中的最低已知档位；不可用时明确报错。启动记录实际配置和 token，客户端设置与模型服务原生容量分别记录。可用 `--provider-config` 提供本次访问所需配置；当前固定 Codex 使用 Responses 协议，换用其他模型需核对提供方兼容性。

## CLI、技能与只读边界

普通会话使用 `tool_surface="cli-v1"`，启用 Codex shell，通过 CLI 获取观察、执行 Lua 和核对结果；动作入口统一经由 CLI。CLI 与 Lua 的身份、期限、取消、放键及支持范围仍以客户端合同为准。持续脚本优先 `script start`，保存返回的 `script.id`，需要停止时显式 `script cancel --session`。

镜像在 `/game/.agents/skills/beidou-pilot-client/` 安装唯一专用技能，并按相对结构携带所需公共文档；app-server 的 cwd 为 `/game`。技能正文直接讲 CLI，Docker 用法放在参考中。普通模式每个新 turn 显式加载该技能；启动检查技能清单，合同测试核对正文实际进入提示。镜像内环境保持精简，角色约束通过新 thread 的独立输入提供。

`--read-only` 关闭 shell，只保留两个动态观察工具及原生询问能力：

| 工具 | 只读合同 |
| --- | --- |
| `game_observe` | 读取当前 status、原生身份、已有 script/command、持键/动作及新鲜 snapshot；未运行与未知事实照实返回 |
| `game_script_status` | 读取 Lua、任务、控制权及持键，只返回当前状态 |

只读模式只观察，其他操作者的执行保持原状。模型进程锁和状态目录锁保护模型会话，角色与脚本控制权以当前原生状态为准。普通模式重新接入时先读取当前脚本、任务和输入归属；已有执行继续有效，恢复 LLM 后继续观察即可。

两种模式都保留 Codex 原生 `request_user_input`，真正缺少选择或越界决策时经专用通道询问；运行环境只启用模型协作需要的配置。

## 开发 AI 的协作通道

stdin 接收 JSONL，stdout 输出带事件与时间的 JSONL；每个命令可携带 `id`：

```jsonl
{"id":"s1","command":"status"}
{"id":"m1","command":"message","text":"补充观察停止后的坐标和持键，并说明不确定项。"}
{"id":"t1","command":"task","text":"改为在当前安全区域验证停止效果。"}
{"id":"p1","command":"pause"}
{"id":"r1","command":"resume"}
{"id":"x1","command":"stop"}
```

游戏 AI 输出 `question` 时，开发 AI 用原 `request_id` 和问题 ID 回答：

```jsonl
{"id":"a1","command":"answer","request_id":10,"answers":{"route":{"answers":["按已确认的安全路线继续"]}}}
```

`task` 更新模型目标和检查点，`message` 补充事实或询问；运行中的消息经 `turn/steer` 进入当前 turn，空闲时在同一 thread 开启下一轮，暂停时等待恢复。改目标时已启动 Lua 继续运行；需要停止脚本时，先核对当前 `script.id`，再明确执行 `script cancel --session SCRIPT_ID` 并确认结果。

`pause/stop` 只中断并确认当前 LLM turn，后台 shell、Lua 与客户端保持运行。客户端与已提交的独立脚本继续运行；要改变游戏执行，仍需对当前任务发出明确的客户端命令。

`resume` 复用仍活的 app-server 和原 thread，先观察当前角色、脚本会话、任务和控制权。重新接入已有执行时同样先观察，核对当前 `script.id` 后按现状续接。脚本是否停止或角色是否放键以当前 CLI 读取的原生状态为准，`status.lua_running=null` 只表示 harness 未观察到运行中的脚本。

| 操作意图 | 明确命令与确认 |
| --- | --- |
| 暂停或结束 LLM | 使用本协作通道的 `pause/stop`，保留客户端和脚本运行 |
| 取消当前 Lua | 读取当前 `script.id`，显式执行 `script cancel --session SCRIPT_ID`，核对同一原生身份的终态与 `held_keys=[]` |
| 关闭客户端 | 使用宿主统一入口的 `close`，核对所属容器退出 |

## 状态续接与验证

`--state` 保存独立 Codex 状态、`checkpoint.json` 与私密 `events.jsonl`。绑定使用稳定的工作目录标识、账号角色/世界、目标项目/服务、CLI 路径和只读模式，不绑定临时容器 ID 或 run ID；同一角色在新客户端运行中可续接原 thread，续接时重新读取当前实例身份、位置和引用。绑定改变时拒绝恢复，历史观察作为历史记录保留。

旧 `lua-v1`、`hunt-v1` 或缺失工具面标记的状态明确拒绝续接。保留旧状态作为历史，使用新的独立 `--state` 启动 `cli-v1` 会话；旧工具只读保留。线程恢复与新客户端原生身份的核验分别完成。

记录实际模型、effort、turn 墙钟时间和 token 事件；组件 token 分摊、底层请求次数或价格不可得时保持未知。角色经历与原始观察留在私密状态，公开 Issue 只引用无私密结论。

离线构建及完整测试命令集中在 [CI](CI.md#本地复现)。`Game AI harness contract` 从无头客户端派生镜像，验证镜像内 CLI/技能、真实 Codex 到无认证假 Responses 端点的 shell、技能、只读工具、询问和线程恢复合同，全程使用离线假端点。

独立启停边界的验收覆盖 headless 与 GUI：在无 LLM 时启动原生脚本；LLM 退出及重新接入后，同一 `script.id` 和已有任务继续；重新接入只观察，已有执行继续原样运行。显式脚本取消放键与客户端关闭分别核对，模型侧使用既有无认证离线合同。对应镜像、提交和实际脚本证据分别记录；模型质量、token、决策延迟和询问功能按相关需求另行验证。

## 向已有 SSH Codex 会话投递客户端事件

`harness/game-events` 是独立的事件消费者，连接桌面应用经 SSH 使用的既有 Codex daemon 和明确指定的 thread。它复用已有 harness、app-server 与游戏客户端，只投递客户端事件；角色设定与工具保持原样。客户端事件契约由统一 CLI 的 `events read/watch` 提供，模型接入代码留在 `harness/`。

此入口通过 `private/workbenches/workbench DIR COMMAND` 读取已运行容器内的事件 CLI，客户端版本由其运行登记固定。`--cli` 默认取同仓的这个统一入口，客户端版本由运行登记固定。此入口单独需要 `harness/requirements-events.txt` 中固定的 `websockets` 依赖；容器内的 `beidou-game-ai` 沿用 Python 标准库。依赖安装到独立虚拟环境，例如使用本机已有的 uv：

```bash
uv venv /private/game-events/venv
uv pip install --python /private/game-events/venv/bin/python -r harness/requirements-events.txt
```

在 SSH 远端主机以拥有目标会话的同一用户运行，显式绑定客户端、Codex thread 和 daemon socket。socket 可使用该用户的 `~/.codex/app-server-control/app-server-control.sock`，确认指向管理目标会话的 daemon 后再运行；其他服务保持原状。

```bash
/private/game-events/venv/bin/python harness/game-events \
  --workbench /external/gui-workbench \
  --thread THREAD_UUID \
  --socket "$HOME/.codex/app-server-control/app-server-control.sock" \
  --state /private/game-events/receiver --check
```

`--check` 只初始化连接并读取指定会话，用于确认连通性与会话身份。移除 `--check` 后，消费者装载同一 thread 的通知连接，并启动只读 `events watch` 子进程。默认投递统一的 `notification.opened`，覆盖好友、组队、交易及其他所有业务 `kind`；`kind=null` 的未知类型同样送达，并保留真实 `native_kind`、原生字段和按钮，是否响应由模型依据当前事实和已有授权决定。重复 `--event-type TYPE` 可显式选择其他原生事件。`notification.closed` 和观察不可用等未选中的事件只推进游标，事件流按顺序继续；流级 `events_unavailable` 只记录诊断，不推进游标或唤醒模型。

首次没有游标时，以当前最新事件序号建立基线；先看到 `events_ready`，再触发气泡。启动前的历史气泡按历史处理，已有弹窗通过 `notifications read` 另行检查。状态目录私密保存统一入口、工作目录、目标 thread/socket 的绑定及 `instance_id/run_id/seq` 游标；事件报告还要核对实际后端和当前工作目录的默认实例。恢复时由同一容器 CLI 补读留存增量，重复序号只投递一次。旧版本含 `instance` 或 `root/backend` 的绑定保持原状态目录，按历史状态处理。已知过期事件跳过；时限未知保持未知。事件缺口、身份变化或原生观察不可用时，气泡状态以重新读取为准。

默认 `--delivery steer` 在活跃回合使用 `turn/steer`，空闲时直接 `turn/start`。显式选择 `--delivery interrupt` 时，先中断当前模型回合，等待匹配的 `turn/completed`，再启动事件处理回合。该选项会打断目标聊天正在处理的工作，只用于明确授权的专用控制会话。

消费者只调度模型，游戏侧操作分别由各自的显式命令完成。`script run/start` 的 CLI 中断只结束等待，已发布的原生任务继续运行；等待超时或观察失败后先核对当前脚本与任务，再决定后续。需要停止脚本时明确 `script cancel --session` 并确认终态和放键，关闭客户端另用 `close`。停止本监听器只关闭它自己的只读 watcher 与 daemon 连接。

stdout 的 `event_delivered` 区分事件观察到接口受理的时间、投递调度耗时、目标 thread/turn 和实际使用的 RPC；`effect="unknown"` 表示尚未核对游戏效果。接口受理表示通知已送达模型，模型理解与决策时点以后续回合为准。收到通知后先用 `notifications read` 读取当前引用和真实按钮；确有明确操作意图时使用 `notifications respond REF --button CONTROL_ID`，按钮范围以当前读取结果为准。信息类气泡可以只记录；未知 `kind` 保持未知。渲染正文尚未真实读取时 `text=null`，观察明确报告 `not_covered=["rendered_body_text"]`，正文以实际读取结果为准。

通用响应只证明本次按钮派发及当前气泡状态。交易气泡的 `primary` 只打开交易会话，资产成交需从相应当前状态另行核对；好友、队伍或其他业务结果同样按各自状态核对。连接中断、RPC 超时等不明投递结果会报错并保留未确认的游标，模型操作按一次投递处理。

离线合同使用真实 Unix WebSocket 假服务和 CLI 子进程，不访问模型或游戏：

```bash
mkdir -p tmp/game-events-tests
TMPDIR="$PWD/tmp/game-events-tests" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=harness \
  /private/game-events/venv/bin/python -m unittest discover -s harness/test -p test_events.py -v
```

实际验收分别记录运行中插话、空闲唤醒、显式中断后重新处理，以及当前气泡有效性、真实按钮响应和适用的业务结果。好友与组队可用两个账号在两个控制会话中交叉确认；交易测试需单独核对授权范围后再执行资产交换。停止接收方模型时发送方与开发协调方继续运行。监听器的离线合同和 `--check` 覆盖合同层，真实试用另行记录。
