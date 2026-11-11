# Codex 游戏 AI

`harness/` 是客户端能力的独立消费者。Codex app-server 在专用容器中保留一个角色的模型会话；宿主薄控制器通过固定工作台和实例的 Docker 入口，调用客户端容器内的 CLI，并负责开发 AI 的短协作消息。模型不进入逐帧控制，持续移动、战斗与等待仍由 Lua 执行。

准备客户端、选择授权目标与角色、核对占用及交接前，先按[游戏 AI 操作指引](PLAY_GUIDE.md)完成检查；harness 的运行配置不代替游戏操作授权。

## 准备与启动

需要 Linux、Docker、Python 标准库和已准备好的授权客户端实例。harness 不创建账号、不启动或关闭客户端。先构建固定版本 Codex 镜像：

```bash
docker build -t local/beidou-game-ai:0.167.0 docker/harness
```

准备一份只包含角色设定、当前养成方案及操作边界的 UTF-8 文本。认证只使用本机 Codex 授权的专用副本，或运行时显式提供的 API-key 变量；不挂载整份开发 HOME、Codex 配置、技能或 MCP。认证、provider 配置及状态均保存在私密目录，不进入 Git、镜像、日志或提示词。构建过程不登录、不调用模型。发行物与许可见 [容器说明](../docker/harness/README.md)。

```bash
./harness/game-ai --workbench /private/workbench --instance default \
  --state /private/game-ai/state --role /private/game-ai/role.md \
  --auth-file /private/game-ai/auth.json \
  --task '在已确认安全的区域观察，执行约定的有界移动并核对停止结果'
```

`--workbench` 选择已由操作者启动的工作台，`--instance` 选择其中的实例。客户端后端与版本由该实例的登记决定；后续命令通过 `docker exec` 使用容器内的同一份 CLI 和内置 Lua，main 更新不改变已有实例。`--cli` 可指定宿主 Docker 薄入口，默认使用同仓根目录的 `beidou-pilot`；不再通过 `--root`、`--backend` 或宿主 Python 源码选择客户端。客户端源码和 Docker socket 都不挂进模型容器。

`--read-only` 只装载观察与脚本状态能力，拒绝 Lua 和狩猎执行，也不取消其他操作者的输入；适合先核对真实模型、状态、延迟和 token。`--paused` 在初始化后等待 `resume`，不会立即开始模型 turn。`--state` 的 Codex 子目录须允许容器 UID1000 读写，不能指向开发 Codex 目录。stdin 保持打开用于协作；EOF、SIGINT 或 SIGTERM 会停止本次玩法控制并等待释放。

默认模型为 `gpt-6-luna`，只允许显式改选 `gpt-6.1-terra`。启动先从当前运行身份的 `model/list` 读取模型和支持的 effort，优先 `none`，否则选广告清单中的最低已知档位；模型不可用就报错，不切换成其他模型。启动记录给出实际选择。首轮不强制固定上下文窗口，记录有效配置与实际 token，后续依据结果调整；客户端配置不能被宣称为模型服务原生容量变化。

需要专用提供方时用 `--provider-config /private/game-ai/provider.toml`，其中仅保留本次模型访问所需字段；不要使用开发 config.toml。需要环境认证时按变量名显式加 `--credential-env NAME`，变量值不出现在参数或日志中。当前 Codex 只支持 Responses 协议，可配置 provider 不证明任意小模型兼容。

## 工具与精简边界

新游戏会话可用四项动态游戏能力与 Codex 原生同步/异步询问。固定发行物可能用 `exec/wait` 编排壳调用 `game` 命名空间，壳内只能分派下列游戏工具；默认开发命名空间的 patch、MCP 资源与时钟已从描述和嵌套路由排除：

| 工具 | 合同 |
| --- | --- |
| `game_observe` | 先读实际 status；未运行时直接返回，运行时读新鲜桥身份及 snapshot；未知仍未知 |
| `game_run_lua` | 提交0至30秒的有界源码，立即返回 `starting`；原生受理和游戏效果另行核对 |
| `game_hunt` | 当前单一场景内自主找怪、换层与连续攻击；参数为 `target`（默认 `all`，也可模板ID字符串或怪物名）、可选 `skill_id`、`range`（默认60）、`seconds`（默认60，0.05至600）或 `continuous=true`；立即返回 `starting`，结束后自动收到结果 |
| `game_script_status` | Lua、任务、控制权、持键及本 harness 最近执行结果 |
| `request_user_input` | 真正需要协助或越界决策时向开发 AI 询问，原问题及回答经专用通道传递 |

Lua 结束后控制器自动把结果送回同一模型会话，游戏 AI 重新观察并按任务继续；开发 AI 无需逐轮发起动作。`game_hunt` 复用固定实例的 `hunt` CLI，脚本和地形在客户端装载；模型只提交狩猎参数，不需要取得或复制整份源码。持续狩猎与短 Lua 使用同一活动执行和取消链，期间不能插入另一个动作；不再要求每30秒回到模型重新提交狩猎。指定技能仍需本后端支持且角色已学，换地图或场景代次变化会停止本次狩猎。原 CLI 仍拥有实例身份、执行期限、取消和放键语义。harness 不提供任意 shell、文件修改、Docker 操作或改变所控实例的工具。

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

`task` 同步更新当前目标与检查点；`message` 仅补充事实或询问。已启动的有界 Lua 不因改目标自动重放或替换，需立即停止时先 `pause`。运行中的消息经 `turn/steer` 进入当前 turn；空闲时在同一 thread 开启下一轮。暂停时消息保留到恢复。有控制权的会话暂停或停止先禁止新动作，等待已受理的模型输入取得 turn 身份后中断生成，再取消本 harness 持有的原脚本 CLI。宿主薄入口将取消信号转发到该次容器内执行，等待原 CLI 收尾及同 instance_id/run_id 的新鲜状态确认 Lua/命令已停止、`held_keys=[]`，之后才报告成功。仅终止宿主 `docker exec` 进程不能证明容器内 CLI 已取消；中断模型 turn 也不等于取消 Lua，第二个 `stop` 命令不能替代原 CLI 的取消。

恢复会重新观察并规划，不恢复已取消的 Lua 协程。需要开发 AI 直接接管时，先收到确认暂停及放键，再交接控制权；同角色仅有一个操作者。停止 harness 后客户端容器保留，按其独立生命周期显式关闭。

## 记录与验证

`--state` 保留独立 Codex 状态、`checkpoint.json` 和私密 `events.jsonl`，记录任务、回复、询问、工具结果、版本、用量及执行耗时。重启同一状态目录可续接该游戏 thread，并先取最新游戏状态；不会读取旧位置或旧引用作为当前事实。客户端绑定由宿主入口 `cli`、`workbench`、`instance` 和 `read_only` 组成，选择改变时拒绝续接。旧版本保存的 `cli/root/backend` 绑定不自动迁移或原地恢复；保留原状态目录，按新工作台选择创建独立 `--state`。

[OpenAI App Server 文档](https://developers.openai.com/codex/app-server) 说明动态工具随 thread 持久保存。本项目固定的 Codex `0.167.0` 只在 `thread/start` 提供 `dynamicTools`，该版本的 `thread/resume` schema 没有更新工具参数；真实无认证协议检查也确认，续接时传入此字段会被忽略。新 checkpoint 保存 `tool_surface="hunt-v1"`，续接原 thread 时恢复其已注册的四项工具。旧 checkpoint 沿用 `lua-v1` 三项工具和对应指引，并产生可观察的 `legacy_tool_surface` 事件；原 thread 与历史保持原样。需要 `game_hunt` 时，使用新的独立 `--state` 目录明确启动新游戏会话，保留原状态目录。源码更新不会自动替换已有会话的工具或修改私密常驻部署。

启动还记录可控基础/角色/动态工具描述的 UTF-8 字节数，组件 token 分摊未由接口提供时保持未知。指标区分 turn 请求次数、动态工具次数、token 用量更新、模型轮次墙钟时间与 Lua 执行时间。token 来自 Codex 实际事件；不把 turn 数或用量更新数冒充底层 API 请求数，不凭未知价格估算费用。底层请求精确计数与价格尚不可得时如实记未知。原始观察和经历不上传公开 Issue。

离线检查：

```bash
mkdir -p tmp/harness-tests
TMPDIR="$PWD/tmp/harness-tests" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=harness \
  BEIDOU_GAME_AI_IMAGE=local/beidou-game-ai:0.167.0 \
  python3 -m unittest discover -s harness/test -v
```

`Game AI harness contract` CI 构建隔离镜像，执行纯假 CLI/app-server 合同及真实 Codex 到本地假 Responses 端点的完整工具/指令、exec 游戏分派与询问往返检查；还验证新 thread 注册后续接，`game_hunt` 仍可按类型参数派发。检查无认证、无外部模型和游戏操作。既有 `Python offline tests` 与 `Headless image build` 继续独立运行。

正式验收仍需主代理记录实际模型、effort、上下文与 token、决策延迟，在授权角色和隔离目标上核对有界移动、停止放键、双向询问和定向复验。离线模拟、Lua 返回或仅登录成功不能代替实际游戏结果；此证据缺失时 PR 保持待验收。
