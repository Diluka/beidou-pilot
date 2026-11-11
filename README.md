# beidou-pilot

面向脚本和 AI 的游戏客户端工具：脚本承担主要驱动工作，AI 可选接入辅助决策。无头端用于自动化，北斗 GUI 用于按需操作和验证；两端的 Docker 镜像安装同一份 CLI 与 Lua。同仓 `harness/` 可随所选客户端打包，在同一容器内通过 CLI 旁路接入；客户端和脚本在无 LLM 时持续运行，模型会话、角色设定与经历由 harness 持有。

## 组件布局

```text
private/workbenches/workbench   唯一宿主入口，直接管理 Docker/Git
cli/                            两个镜像共用的容器内 beidou-pilot、观察和测试
docker/                         headless 与 GUI 镜像、唯一 GUI Compose 和容器入口
harness/                        容器内模型会话、角色上下文与专用协作入口
headless/                       无头原生宿主和适配器
beidou-ijl15/                   原版客户端 DLL 工程和适配器
shared/
  lua-runtime/                  两端共用的 C++ Lua 调度与 game API
  scripts/                      随镜像固定的公共 Lua 策略和示例
third_party/                    上游依赖
```

`private/workbenches/workbench` 是版本化的公共脚本。该目录中的账号、共享 `resources.json`、工作目录和运行数据继续被 Git 忽略；不再提供仓库根宿主脚本或各工作目录的转发脚本。容器内命令仍叫 `beidou-pilot`。

## 准备

宿主需要 Bash、Git、Docker（含 Compose）和 jq；GUI 默认取得 CI 桥工件时还需要已配置的 GitHub CLI `gh`。日常客户端运行不要求宿主 Python。

```bash
git submodule update --init --recursive
private/workbenches/workbench --help
```

将公共资源路径配置保存在主检出目录的 `private/workbenches/resources.json`，字段示例见 [resources.example.json](cli/config/resources.example.json)。各工作目录及开发 worktree 共用这一份配置；原版 `/client` 与 NX `/data` 的格式、来源和只读挂载保持不变，当前未实现原始 IMG 直读。

常驻服务器的项目、服务和公开镜像引用由统一脚本固定，普通工作目录不维护 `server.json`。启动器继续核对实际服务器镜像。调试和实际游戏验收默认使用常驻服，优先复用已授权的已有账号、角色及就绪实例，减少主机内存占用；仅在验证场景必须时新建账号或角色。隔离服仅用于常驻服无法安全完成验证等特殊情况，需说明原因，并在 `workbench.json` 中显式选择非 `beidou-ms` 服务器；格式和边界见 [CLI](docs/CLI.md#工作目录配置)。

每个工作目录长期保存一个账号角色的资料：

```text
/external/workbench/
  account.json       0600，已有账号与角色
  workbench.json     可选的新建设置；省略时使用 headless 和 main
  PLAN.md            角色养成方案
  HANDOFF.md         已确认进度与下一步
  scripts/           用户 Lua
  runtime/           启动器生成的配置快照、桥、日志和运行记录
```

两端共用 `account.json`：必填 `username/password/character_id`，可省略的 `world/channel` 从 0 开始、默认 0。GUI 工作目录的最小 [workbench.json 示例](cli/config/workbench.example.json) 只需：

```json
{"backend":"beidou"}
```

工作目录整体读写挂到容器 `/work`，用户 Lua 位于 `/work/scripts`。每个目录使用自己的 `default` 实例和独立运行数据；同一目标同一角色仍只交给一名控制者。

## 操作工作台

以下在仓库根执行，将目录替换为已确认的账号工作目录。操作前沿用已有授权并核对账号在线、认领和操作者。

```bash
private/workbenches/workbench /external/workbench notes
private/workbenches/workbench /external/workbench status
private/workbenches/workbench /external/workbench plan
private/workbenches/workbench /external/workbench open
private/workbenches/workbench /external/workbench snapshot
private/workbenches/workbench /external/workbench capabilities
private/workbenches/workbench /external/workbench close
```

只给目录时默认为只读 `status`；`--list` 列出主检出 `private/workbenches/` 下已有的工作目录，`notes` 读取指定目录的计划和交接。需要先准备镜像时使用同一入口的 `build`。离线 NX 检查使用 `resources-check`，不登录游戏。

新实例默认取 `main` 当时的已提交版本构建或复用镜像；后端、开发 `ref`、等待期限和可选桥工件在工作目录内配置，不通过宿主命令行覆盖。已有实例的命令继续使用其已登记容器，修改新建设置或更新 `main` 都不会更换运行中的 CLI 与内置策略。实际版本查 `status` 的 `source_revision/image/run_id`。

日常命令经宿主入口转到所属容器内的 `beidou-pilot`。核对容器归属后也可只读排查：`docker exec CONTAINER beidou-pilot --json status`。脚本 CLI 中断只结束等待，已发布的原生任务继续；等待超时或观察失败也不能当作任务已停止。先读当前脚本状态，明确取消用 `script cancel --session`，核对终态和放键；`close` 另行关闭并回收所属容器。Lua 返回或取消后实例继续运行，真实断线或错误会保留退出原因。完整参数见 [CLI](docs/CLI.md)。

需要游戏 AI 时，在 `workbench.json` 设置 `harness=true`，然后使用同一入口的 `open`、`ai`；模型 HTTP 代理 `model_proxy="http://IPv4:端口"` 按需配置。构建先准备对应客户端 base，再派生包含 Node/Codex、Python harness 和专用 CLI 技能的镜像；继承用于打包复用，客户端继续作为 PID1，LLM 独立启停。角色、认证及常驻状态均通过容器内路径提供，普通模式直接使用 CLI，只读模式关闭 shell。退出 LLM 会保留脚本，重新接入先观察已有任务；取消脚本和关闭客户端分别执行明确命令。配置、协作和跨运行续接见 [harness 用法](docs/HARNESS.md)。

## 文档与开发

- [北斗游戏攻略技能](.agents/skills/beidou-game-guide/SKILL.md)：收录彩虹岛与骑士团新手任务、青苹果乐园支线、冒险家三转任务、冒险家二转三转及骑士团一至三转终态加点；各篇注明来源与实测范围。
- [业务地图](docs/business-map/README.md)：按领域查看用户结果、责任边界、主要流程与源码入口。
- [游戏 AI 操作指引](docs/PLAY_GUIDE.md)：确认授权目标与角色占用，完成上手观察、动作核对和停止交接。
- [客户端操作技能](.agents/skills/beidou-pilot-client/SKILL.md)：供新会话接续工作台、登录已有角色，并区分账号注册与首次建角；可显式调用 `$beidou-pilot-client`。
- [游戏 AI harness](docs/HARNESS.md)：隔离 Codex、角色上下文、游戏工具与开发 AI 协作。
- [命令使用](docs/CLI.md)：实例、观察、动作、GUI 入口和错误结果。
- [Lua API 参考](docs/LUA_API.md)：写脚本使用的状态字段、函数参数、返回值与错误语义。
- [Lua 脚本目录说明](shared/scripts/README.md)：内置旅行、战斗、恢复策略及示例的用途、调用入口和弃用标记。
- [Lua 与控制协议](docs/CONTROL.md)：脚本、控制权、取消和效果边界。
- [架构与支持范围](docs/ARCHITECTURE.md)：代码职责、外部资源、两端能力和限制。
- [客户端能力边界与缺口索引](docs/CLIENT_LIMITATIONS.md)：实际使用成本、已入池用户结果和已有能力的适用范围。
- [依赖管理](docs/DEPENDENCIES.md)：子模块、派生源码与许可来源。
- [CI 与合并验收](docs/CI.md)：PR 自动检查、本地复现入口及与真实游戏试用的分工。
- [需求池](https://github.com/Diluka/beidou-pilot/issues?q=is%3Aissue%20is%3Aopen%20label%3A%E9%9C%80%E6%B1%82%E6%B1%A0)：按独立用户故事收集需求，入池标准与讨论规则见 [开发约定](AGENTS.md#需求收集与需求池)。
- [开发约定](AGENTS.md)：需求收集、任务拆分、CI 与真实客户端验收、PR 合并、维护规则及 Serena 项目记忆。

从仓库根运行离线测试：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli -v
```

项目采用 [AGPL-3.0-only](LICENSE)，第三方保留各自授权，详见 [NOTICE](NOTICE)。外部游戏客户端与素材不属于本项目的软件许可范围。

项目开发记忆入口为 [.serena/memories/core.md](.serena/memories/core.md)。使用仓库真实绝对路径激活 Serena 项目 `beidou-pilot`；当前只启用记忆，不启动语言服务，维护规则见 [AGENTS.md](AGENTS.md)。
