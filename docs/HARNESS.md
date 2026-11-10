# Codex 游戏 AI

`harness/` 是客户端能力的独立消费者。Codex app-server 在专用容器中保留一个角色的模型会话；宿主薄控制器只调用固定 root/backend/instance 的已有 CLI，并负责开发 AI 的短协作消息。模型不进入逐帧控制，持续移动、战斗与等待仍由 Lua 执行。

准备客户端、选择授权目标与角色、核对占用及交接前，先按[游戏 AI 操作指引](PLAY_GUIDE.md)完成检查；harness 的运行配置不代替游戏操作授权。

## 准备与启动

需要 Linux、Docker、Python 标准库和已准备好的授权客户端实例。harness 不创建账号、不启动或关闭客户端。先构建固定版本 Codex 镜像：

```bash
docker build -t local/beidou-game-ai:0.167.0 docker/harness
```

准备一份只包含角色设定、当前养成方案及操作边界的 UTF-8 文本。认证只使用本机 Codex 授权的专用副本，或运行时显式提供的 API-key 变量；不挂载整份开发 HOME、Codex 配置、技能或 MCP。认证、provider 配置及状态均保存在私密目录，不进入 Git、镜像、日志或提示词。构建过程不登录、不调用模型。发行物与许可见 [容器说明](../docker/harness/README.md)。

```bash
./harness/game-ai --root /external/client-cli --backend beidou \
  --state /private/game-ai/state --role /private/game-ai/role.md \
  --auth-file /private/game-ai/auth.json \
  --task '在已确认安全的区域观察，执行约定的有界移动并核对停止结果'
```

命名无头实例另加 `--backend headless --instance NAME`。`--cli` 可指定所用版本的统一入口；默认加载同一源码树的 `cli/beidou-pilot`。`--read-only` 只装载观察与脚本状态能力，拒绝 Lua 执行，也不取消其他操作者的输入；适合先核对真实模型、状态、延迟和 token。`--paused` 在初始化后等待 `resume`，不会立即开始模型 turn。`--state` 的 Codex 子目录须允许容器 UID1000 读写，不能指向开发 Codex 目录。stdin 保持打开用于协作；EOF、SIGINT 或 SIGTERM 会停止本次玩法控制并等待释放。

默认模型为 `gpt-6-luna`，只允许显式改选 `gpt-6.1-terra`。启动先从当前运行身份的 `model/list` 读取模型和支持的 effort，优先 `none`，否则选广告清单中的最低已知档位；模型不可用就报错，不切换成其他模型。启动记录给出实际选择。首轮不强制固定上下文窗口，记录有效配置与实际 token，后续依据结果调整；客户端配置不能被宣称为模型服务原生容量变化。

需要专用提供方时用 `--provider-config /private/game-ai/provider.toml`，其中仅保留本次模型访问所需字段；不要使用开发 config.toml。需要环境认证时按变量名显式加 `--credential-env NAME`，变量值不出现在参数或日志中。当前 Codex 只支持 Responses 协议，可配置 provider 不证明任意小模型兼容。

## 工具与精简边界

模型可用三项动态游戏能力与 Codex 原生同步/异步询问。固定发行物可能用 `exec/wait` 编排壳调用 `game` 命名空间，壳内只能分派下列游戏工具；默认开发命名空间的 patch、MCP 资源与时钟已从描述和嵌套路由排除：

| 工具 | 合同 |
| --- | --- |
| `game_observe` | 先读实际 status；未运行时直接返回，运行时读新鲜桥身份及 snapshot；未知仍未知 |
| `game_run_lua` | 提交0至30秒的有界源码，立即返回 `starting`；原生受理和游戏效果另行核对 |
| `game_script_status` | Lua、任务、控制权、持键及本 harness 最近执行结果 |
| `request_user_input` | 真正需要协助或越界决策时向开发 AI 询问，原问题及回答经专用通道传递 |

Lua 结束后控制器自动把结果送回同一模型会话，游戏 AI 重新观察并按任务继续；开发 AI 无需逐轮发起动作。原 CLI 仍拥有实例身份、执行期限、取消和放键语义。harness 不提供任意 shell、文件修改、Docker 操作或改变所控实例的工具。

镜像使用独立 HOME 和空 `/game`，关闭 bundled skills、插件、MCP、shell、apps、多代理、记忆、目标、hooks、搜索和图像工具，不继承仓库 AGENTS。基础指令由短游戏指引替换；角色约束显式传入新 thread，不复制或 fork 开发会话。内置询问工具被明确保留，并非已从 Codex 移除。启动检查技能/MCP/指令来源，CI 再用无认证假端点捕获真实请求中的提示与完整工具清单；零技能或空 MCP 本身不能证明最终精简成功。

## 开发 AI 的协作通道

stdin 为 JSONL，stdout 返回带事件名和时间的 JSONL；每个命令可携带自己的 `id`。例如：

```jsonl
{"id":"s1","command":"status"}
{"id":"m1","command":"message","text":"补充观察这次停止后的坐标和持键，并说明不确定项。"}
{"id":"t1","command":"task","text":"改为在当前安全区域验证停止效果，不继续前往旧目标。"}
{"id":"p1","command":"pause"}
{"id":"r1","command":"resume"}
{"id":"x1","command":"stop"}
```

游戏 AI 询问时输出 `question`，含 `request_id` 和问题数组。开发 AI 使用原问题 ID 回答：

```jsonl
{"id":"a1","command":"answer","request_id":10,"answers":{"route":{"answers":["按已确认的安全路线继续"]}}}
```

`task` 同步更新当前目标与检查点；`message` 仅补充事实或询问。已启动的有界 Lua 不因改目标自动重放或替换，需立即停止时先 `pause`。运行中的消息经 `turn/steer` 进入当前 turn；空闲时在同一 thread 开启下一轮。暂停时消息保留到恢复。有控制权的会话暂停或停止先禁止新动作，等待已受理的模型输入取得 turn 身份后中断生成，并向本 harness 持有的原脚本 CLI 发信号，等待同 instance_id/run_id 的新鲜状态确认 Lua/命令已停止及 `held_keys=[]`，之后才报告成功。中断模型 turn 不等于取消 Lua，第二个 `stop` 命令不能替代原 CLI 的取消。

恢复会重新观察并规划，不恢复已取消的 Lua 协程。需要开发 AI 直接接管时，先收到确认暂停及放键，再交接控制权；同角色仅有一个操作者。停止 harness 后客户端容器保留，按其独立生命周期显式关闭。

## 记录与验证

`--state` 保留独立 Codex 状态、`checkpoint.json` 和私密 `events.jsonl`，记录任务、回复、询问、工具结果、版本、用量及执行耗时。重启同一状态目录可续接该游戏 thread，并先取最新游戏状态；不会读取旧位置或旧引用作为当前事实。客户端选择改变时拒绝续接。

启动还记录可控基础/角色/动态工具描述的 UTF-8 字节数，组件 token 分摊未由接口提供时保持未知。指标区分 turn 请求次数、动态工具次数、token 用量更新、模型轮次墙钟时间与 Lua 执行时间。token 来自 Codex 实际事件；不把 turn 数或用量更新数冒充底层 API 请求数，不凭未知价格估算费用。底层请求精确计数与价格尚不可得时如实记未知。原始观察和经历不上传公开 Issue。

离线检查：

```bash
mkdir -p tmp/harness-tests
TMPDIR="$PWD/tmp/harness-tests" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=harness \
  BEIDOU_GAME_AI_IMAGE=local/beidou-game-ai:0.167.0 \
  python3 -m unittest discover -s harness/test -v
```

`Game AI harness contract` CI 构建隔离镜像，执行纯假 CLI/app-server 合同及真实 Codex 到本地假 Responses 端点的完整工具/指令、exec 游戏分派与询问往返检查，无认证、无外部模型和游戏操作。既有 `Python offline tests` 与 `Headless image build` 继续独立运行。

正式验收仍需主代理记录实际模型、effort、上下文与 token、决策延迟，在授权角色和隔离目标上核对有界移动、停止放键、双向询问和定向复验。离线模拟、Lua 返回或仅登录成功不能代替实际游戏结果；此证据缺失时 PR 保持待验收。

## 向已有 SSH Codex 会话投递客户端事件

`harness/game-events` 是独立的事件消费者，连接桌面应用经 SSH 使用的既有 Codex daemon 和明确指定的 thread。它不启动 `game-ai`、模型容器或游戏客户端，不创建新聊天，也不修改已有角色设定或工具。客户端事件契约由统一 CLI 的 `events read/watch` 提供，模型接入代码留在 `harness/`。

此入口单独需要 `harness/requirements-events.txt` 中固定的 `websockets` 依赖；原有 `harness/game-ai` 仍可仅用 Python 标准库。依赖安装到独立虚拟环境，例如使用本机已有的 uv：

```bash
uv venv /private/game-events/venv
uv pip install --python /private/game-events/venv/bin/python -r harness/requirements-events.txt
```

在 SSH 远端主机以拥有目标会话的同一用户运行，显式绑定客户端、Codex thread 和 daemon socket。socket 可使用该用户的 `~/.codex/app-server-control/app-server-control.sock`；必须确实指向管理目标会话的 daemon，不启动或重启其他服务。

```bash
/private/game-events/venv/bin/python harness/game-events \
  --root /external/client-cli --backend beidou --instance default \
  --thread THREAD_UUID \
  --socket "$HOME/.codex/app-server-control/app-server-control.sock" \
  --state /private/game-events/receiver --check
```

`--check` 只初始化连接并读取指定会话，不订阅客户端事件、不发送模型输入。移除 `--check` 后，消费者装载同一 thread 的通知连接，并启动只读 `events watch` 子进程。默认只投递 `invitation.opened`；重复 `--event-type TYPE` 可显式选择其他原生事件。`invitation.closed` 等未选中的事件只推进游标，避免在模型刚处理完邀请时再次打断它。

首次没有游标时，以当前最新事件序号建立基线；先看到 `events_ready`，再开始发送邀请。它不会把启动前的历史邀请当作仍然有效，已有弹窗应通过当前邀请观察另行检查。状态目录私密保存绑定和 `instance_id/run_id/seq` 游标；恢复时由 CLI 补读留存增量，重复序号不会重复通知。已知过期事件跳过；时限未知保持未知。事件缺口、身份变化或原生观察不可用不能作为邀请已处理的证据。

默认 `--delivery steer` 在活跃回合使用 `turn/steer`，空闲时直接 `turn/start`。显式选择 `--delivery interrupt` 时，先中断当前模型回合，等待匹配的 `turn/completed`，再启动事件处理回合；不通过 `queue` 等旧回合自然结束。该选项会打断目标聊天正在处理的工作，只用于明确授权的专用控制会话。

消费者只调度模型，不调用已有 `game-ai` 的 `pause/stop`、不发送游戏取消、不直接写桥命令。已提交游戏任务是否继续，遵循其原执行入口的生命周期；同步 `script run` 的 SIGINT/SIGTERM 仍会取消所属 Lua。需要让游戏任务独立于模型回合继续时，使用客户端正式支持的非阻塞执行入口，并从当前脚本状态核对结果。停止本监听器只关闭它自己的只读 watcher 与 daemon 连接。

stdout 的 `event_delivered` 区分事件观察到接口受理的时间、投递调度耗时、目标 thread/turn 和实际使用的 RPC；`effect="unknown"` 表示尚未核对游戏效果。接口受理不证明模型已经理解通知，也不保证在邀请有效期内完成决策。收到通知后仍需读取当前邀请引用，按既有明确意图接受或拒绝，并以实际好友或队伍状态确认结果。连接中断、RPC 超时等不明投递结果会报错并保留未确认的游标，不自动重放模型操作。

离线合同使用真实 Unix WebSocket 假服务和 CLI 子进程，不访问模型或游戏：

```bash
mkdir -p tmp/game-events-tests
TMPDIR="$PWD/tmp/game-events-tests" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=harness \
  /private/game-events/venv/bin/python -m unittest discover -s harness/test -p test_events.py -v
```

实际验收分别记录运行中插话、空闲唤醒、显式中断后重新处理，以及真实邀请是否仍有效、接受/拒绝和成员结果。两账号分属两个控制会话；停止接收方模型时发送方与开发协调方继续运行。监听器的离线合同和 `--check` 均不能替代这项试用。
