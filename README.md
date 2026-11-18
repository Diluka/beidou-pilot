# beidou-pilot

面向脚本和 AI 操作者的游戏客户端工具。通过 CLI 观察角色和场景，使用 tick Lua 持续执行游戏动作。无头端用于自动化，北斗 GUI 用于原版界面操作和验证；两端的 Docker 镜像安装同一份 CLI 与 Lua。

## 组件布局

```text
workbenches/                    宿主统一入口、部署说明和公开配置示例
cli/                            两个镜像共用的容器内 beidou-pilot、观察和测试
docker/                         两端客户端镜像和运行入口、独立开发服部署
headless/                       无头原生宿主和适配器
beidou-ijl15/                   原版客户端 DLL 工程和适配器
shared/
  lua-runtime/                  两端共用的 tick Lua 调度、领域观察与动作槽
  scripts/                      随镜像固定的 tick 示例
third_party/                    上游依赖
```

宿主统一使用 [workbench](workbenches/workbench)，容器内命令仍叫 `beidou-pilot`。真实配置、账号、角色记录和运行数据均留在主检出目录的 `private/workbenches/`，不纳入版本控制。

## 准备

宿主需要 Bash、Git、Docker（含 Compose）和 jq；GUI 默认取得 CI 桥工件时还需要已配置的 GitHub CLI `gh`。日常客户端运行不要求宿主 Python。

```bash
git submodule update --init --recursive
workbenches/workbench --help
```

先按[工作台指南](workbenches/README.md)准备主检出目录的 `private/workbenches/config/`：`resources.json` 指向只读原版资源，`live.server.json` 和 `dev.server.json` 各指定本区服务器。开发服配置、数据和网络独立于常驻服，各 Git worktree 使用同一套私密目录。

| 用途 | 角色标识 | 接续依据 |
| --- | --- | --- |
| 常驻服自然游玩与养成 | `live/NAME` | 已授权角色的 `PLAN.md` 与实际游戏进度 |
| 半常驻开发服的调试、复现与验收 | `dev/NAME` | `STATE.md` 记录角色条件、核对来源和时间，不维护养成进度 |

标识映射到 `private/workbenches/live/NAME/` 或 `private/workbenches/dev/NAME/`。每个角色目录有自己的账号文件（`0600`）、可选 `workbench.json`、`scripts/` 和运行记录。角色目录整体挂载到容器 `/work`；两区不共用账号、存档或运行目录。GUI 角色在 `workbench.json` 设置 `{"backend":"beidou"}`。

## 操作工作台

以下在仓库根执行；用本次已授权角色的工作台目录名替换 `NAME`。先列出已有角色并核对环境、角色占用和操作者，再打开客户端。

```bash
workbenches/workbench list dev
workbenches/workbench server dev status
workbenches/workbench dev/NAME notes
workbenches/workbench dev/NAME status
workbenches/workbench dev/NAME plan
workbenches/workbench dev/NAME open
workbenches/workbench dev/NAME snapshot
workbenches/workbench dev/NAME capabilities
workbenches/workbench dev/NAME close
```

`list` 列出两个分区，可加 `live` 或 `dev` 筛选。开发服由 `server dev up` 显式启动，`server dev stop` 停服并保留数据。角色 `close` 只关闭其客户端；离线资源检查 `resources-check` 无需登录。

新实例按 `workbench.json.ref`（默认 `main`）的已提交版本构建或复用镜像；GUI Compose 由当前宿主入口提供。已有实例保留启动时的 CLI、内置 Lua 和原生组件，实际版本查 `status` 的 `source_revision/image/run_id`。

日常命令经宿主入口转到所属容器内的 `beidou-pilot`。核对容器归属后也可只读排查：`docker exec CONTAINER beidou-pilot --json status`。脚本 CLI 中断只结束等待，已发布的原生任务继续；等待超时或观察失败时，任务是否停止以当前脚本状态为准。先读当前脚本状态，明确取消用 `script cancel --session`，核对终态和放键；`close` 另行关闭并回收所属容器。Lua 返回或取消后实例继续运行，真实断线或错误会保留退出原因。完整参数见 [CLI](docs/CLI.md)。

## 文档与开发

- [北斗游戏攻略技能](.agents/skills/beidou-game-guide/SKILL.md)：收录彩虹岛与骑士团新手任务、青苹果乐园支线、冒险家三转任务、冒险家二转三转及骑士团一至三转终态加点；各篇注明来源与实测范围。
- [业务地图](docs/business-map/README.md)：按领域查看用户结果、责任边界、主要流程与源码入口。
- [AI 操作者的客户端使用指引](docs/PLAY_GUIDE.md)：确认授权目标与角色占用，完成上手观察、动作核对和停止交接。
- [客户端操作技能](.agents/skills/beidou-pilot-client/SKILL.md)：供新会话接续工作台、登录已有角色，并区分账号注册与首次建角；可显式调用 `$beidou-pilot-client`。
- [命令使用](docs/CLI.md)：实例、观察、动作、GUI 入口和错误结果。
- [Lua API 导航](docs/LUA_API.md)：指向 [tick API](docs/LUA_TICK_API.md)，说明入口、档位、只读领域、动作槽、参数、返回值与执行语义。
- [Lua 示例目录说明](shared/scripts/README.md)：随镜像固定的 tick 示例及其运行方式。
- [Lua 与控制协议](docs/CONTROL.md)：脚本、控制权、取消和效果边界。
- [架构与支持范围](docs/ARCHITECTURE.md)：代码职责、外部资源、两端能力和限制。
- [V17 普通运动规则](docs/V17_MOTION_RULES.md)：原版 GUI 普通地面/跳跃/空中运动的参数、倍率缺省、分支公式、真机基线与未闭环项；供 headless 普通运动对齐与 C++ 运动预测复用。
- [V17 其余运动规则与差异](docs/V17_EXTENDED_MOTION_RULES.md)：攀爬、受击、移动技能、场地特例、实体及运动包的原版规则、headless差异和后续调整记录。
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
