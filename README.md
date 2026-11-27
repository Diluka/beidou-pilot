# beidou-pilot

面向脚本和 AI 操作者的北斗游戏客户端工具：通过 CLI 观察角色与场景，用 tick Lua 提交持续动作，在原版 GUI 客户端中核对实际游戏结果。

## 项目定位

- **是**：一套可核验的客户端自动化工具。CLI 负责实例、观察、脚本装载/取消和结果投影；tick Lua 负责角色动作；Docker 负责客户端、资源与运行环境隔离。
- **不是**：游戏服务端、外挂或开箱即用的游戏机器人。仓库不包含服务端实现、数据库、存档或账号；角色策略和玩法流程由使用者编写。
- **应用层**：伴游机器人（跟随、组队、组队任务、BOSS、可选大模型）是建立在本工具之上的应用层，当前处于设计与分阶段实施中，不是已交付能力。设计见 [伴游机器人设计与路线](docs/COMPANION_BOT.md)。
- **后端**：客户端只提供原版 GUI 后端（Wine + Xvfb 无头部署）。此前的原生 headless 客户端已退役；机器人包迁移到 GUI 后端属于后续任务。

## 当前能力

| 能力 | 状态 |
| --- | --- |
| 原版 GUI 客户端、登录、建角与实例生命周期 | 已交付 |
| CLI 观察：角色、场景、背包、任务、同图玩家、通知 | 已交付 |
| tick Lua：动作槽、预算、会话、取消与放键 | 已交付 |
| 静态地形/导航数据、世界门户路线只读查询 | 已交付 |
| 脚本目录包、模块装载、怪物与物理观察 | 已交付 |
| 聊天、队伍、运行时跨图路线、交易、手动 AP | 缺口，见 [能力边界](docs/CLIENT_LIMITATIONS.md) |
| 内置寻路/狩猎/组队任务/伴游机器人 | 不在客户端内置；由用户脚本或应用层实现 |

能力以当前 `capabilities`、领域响应和真实结果为准；文档没有写到的能力不等于已支持。

## 组件布局

```text
workbenches/                    宿主统一入口、部署说明和公开配置示例
cli/                            容器内 beidou-pilot、观察和测试
docker/                         GUI 客户端镜像和运行入口、独立开发服部署
beidou-ijl15/                   原版客户端 DLL 工程和适配器
shared/
  lua-runtime/                  tick Lua 调度、领域观察与动作槽
  img/                          两端共用的原版 IMG 只读解析库
  scripts/                      随镜像固定的 tick 示例和校准探针
third_party/                    上游依赖
docs/                           产品文档、接口契约、研究记录和路线
```

宿主统一使用 `workbenches/workbench`，容器内命令仍叫 `beidou-pilot`。真实配置、账号、角色记录和运行数据留在主检出 `private/workbenches/`，不纳入版本控制。

## 准备

宿主需要 Bash、Git、Docker（含 Compose）和 jq；默认取得 CI 桥工件时还需要已配置的 GitHub CLI `gh`。日常客户端运行不要求宿主 Python。

```bash
git submodule update --init --recursive
workbenches/workbench --help
```

先按[工作台指南](workbenches/README.md)准备主检出 `private/workbenches/config/`：`resources.json` 指向只读原版资源，`live.server.json` 和 `dev.server.json` 各指定本区服务器。开发服配置、数据和网络独立于常驻服，各 Git worktree 使用同一套私密目录。

| 用途 | 角色标识 | 接续依据 |
| --- | --- | --- |
| 常驻服自然游玩与养成 | `live/NAME` | 已授权角色的 `PLAN.md` 与实际游戏进度 |
| 开发服调试、复现与验收 | `dev/NAME` | `STATE.md` 记录角色条件、来源与核对时间 |

角色目录整体挂载到容器 `/work`；`account.json` 权限为 `0600`。`workbench.json` 可省略；保留时 `backend` 只接受 `beidou`。

## 操作工作台

以下在仓库根执行；用本次已授权角色的工作台目录名替换 `NAME`。

```bash
workbenches/workbench list dev
workbenches/workbench server dev status
workbenches/workbench dev/NAME plan
workbenches/workbench dev/NAME status
workbenches/workbench dev/NAME open
workbenches/workbench dev/NAME snapshot
workbenches/workbench dev/NAME capabilities
workbenches/workbench dev/NAME script run control.lua --seconds 20
workbenches/workbench dev/NAME close
```

`script run` 同步等结果，`script start` 等原生受理；中断等待不会取消已受理会话。需要停止时先 `script status`，再按 `script.id` 显式 `script cancel --session` 并核对终态/放键；客户端关闭另用 `close`。完整参数见 [CLI](docs/CLI.md)，操作流程见 [使用指引](docs/PLAY_GUIDE.md)。

## 文档

- [文档索引](docs/README.md)：产品文档、契约、应用路线和研究记录的分层入口。
- [伴游机器人设计与路线](docs/COMPANION_BOT.md)：常驻运行时、组队任务/BOSS、LLM 参谋与分阶段验收。
- [架构与支持范围](docs/ARCHITECTURE.md)：组件职责、容器/版本、外部资源与 GUI 能力。
- [CLI](docs/CLI.md)、[控制协议](docs/CONTROL.md)、[Tick Lua API](docs/LUA_TICK_API.md)：命令、脚本生命周期和公开接口。
- [能力边界](docs/CLIENT_LIMITATIONS.md)：当前缺口与下一步能力建设。
- [使用指引](docs/PLAY_GUIDE.md)：AI 操作者的最小上手、核对和交接流程。
- [业务地图](docs/business-map/README.md)：按领域查看用户结果、责任边界和源码入口。
- [V17 运动规则](docs/V17_MOTION_RULES.md)、[扩展运动规则](docs/V17_EXTENDED_MOTION_RULES.md)：原版运动研究记录，不是产品契约。
- [依赖管理](docs/DEPENDENCIES.md)、[CI 与合并验收](docs/CI.md)、[开发约定](AGENTS.md)：维护与交付流程。

## 开发与验收

从仓库根构建共享 IMG 解析库并运行离线测试：

```bash
make -C shared/img build/libbeidou-img.so
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli -v
```

离线合同、镜像构建和真实游戏结果分别判断。涉及客户端行为时，在开发服准备匹配样本并用真实 GUI 客户端核对；纯文档或不改变运行行为的改动说明“游戏试用不适用”及理由。开发约定见 [AGENTS.md](AGENTS.md)，CI 见 [docs/CI.md](docs/CI.md)。

项目采用 [AGPL-3.0-only](LICENSE)，第三方保留各自授权，详见 [NOTICE](NOTICE)。外部游戏客户端与素材不属于本项目软件许可范围。

项目开发记忆入口为 [.serena/memories/core.md](.serena/memories/core.md)。使用仓库真实绝对路径激活 Serena 项目 `beidou-pilot`；当前只启用项目记忆，不启动语言服务。
