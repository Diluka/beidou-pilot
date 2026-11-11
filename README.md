# beidou-pilot

面向脚本和 AI 的游戏客户端工具：脚本承担主要驱动工作，AI 在客户端外部负责决策。工具负责管理实例、读取结构化状态、执行原生动作和 Lua。无头端用于多实例，北斗 GUI 适配器用于按需验证与排障。客户端运行体不集成模型、性格、长期目标或玩家记忆；同仓 `harness/` 独立消费这些客户端能力，持有游戏 AI 的模型会话、角色设定与经历。

## 组件布局

```text
beidou-pilot     宿主 Docker/Git 薄入口，选择工作台、构建和启停实例
cli/             两个镜像共用的容器内 CLI、观察和测试
docker/          headless 与 GUI 镜像、GUI Compose 和容器启动入口
harness/         独立模型会话与专用协作入口
headless/        无头客户端宿主和适配器
beidou-ijl15/    原版客户端 DLL 工程和适配器
shared/
  lua-runtime/   两端共用的 C++ Lua 调度与 game API
  scripts/       随镜像固定的公共 Lua 策略和示例
third_party/     上游依赖
```

两个客户端镜像安装同一份 CLI 和 Lua，各自提供原生无头或 Wine/VirtualGL 运行环境。每个工作台实例有独立容器、Lua 状态、桥和日志。Python 客户端与内置策略在容器中执行，宿主入口只调用 Git、Docker 和 jq。

## 准备

宿主需要 Bash、Git、Docker（含 Compose）和 jq，客户端运行不要求宿主 Python。初始化固定构建依赖：

```bash
git submodule update --init --recursive
./beidou-pilot --help
```

工作台目录长期保存账号、养成方案和交接记录，最少准备：

```text
/external/workbench/
  account.private.json   0600，已有账号与角色
  resources.json         外部 NX/原客户端/GUI 桥工件路径
  target.json            已核验的隔离目标；常驻授权路径可按需准备
  runtime/               启动器管理的独立实例运行数据
```

两端使用相同 profile：`username`、`password`、`character_id`，以及可省略的 `world`、`channel`（从 0 开始，默认 0）。按 [resources.example.json](cli/config/resources.example.json) 配置资源路径；原客户端、NX、账号与运行数据都不进入镜像。GUI 构建另需与所选提交原生输入匹配的 `ijl15.dll` 和 `manifest.json`，可用 `--bridge-artifact DIR` 指定，默认从 `resources.json` 的 `gui_dll` 推导工件目录。

## 操作实例

从工作台打开无头角色：

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --backend headless --json plan
./beidou-pilot --workbench /external/workbench --instance worker-a --backend headless --json open
./beidou-pilot --workbench /external/workbench --instance worker-a --json snapshot
./beidou-pilot --workbench /external/workbench --instance worker-a --json capabilities
./beidou-pilot --workbench /external/workbench --instance worker-a --json close
```

新实例默认从 `main` 当时的已提交版本导出构建输入并构建或复用镜像。之后 `main` 更新不改变已有实例；`status` 可查看 `source_revision/image/run_id`。开发验收可在命令前显式加 `--ref COMMIT`。`plan` 只读核对目标，不构建或启动。

GUI 使用同一入口和 profile，在其工作台选择 `beidou` 后端：

```bash
./beidou-pilot --workbench /external/gui-workbench --backend beidou --json open
./beidou-pilot --workbench /external/gui-workbench --json snapshot
./beidou-pilot --workbench /external/gui-workbench --json close
```

GUI 在一个工作台中只用 `default` 实例，且仅支持 `world=0`。同一目标同一角色一次只交给一个控制者。常驻 `beidou-ms` 目标须已有授权，并在 `plan/open` 时传 `--workspace-server`；没有 target 文件时，启动器为该实例准备所属 internal 连接。

日常命令通过所属容器内的 `beidou-pilot` 执行，例如 `docker exec CONTAINER beidou-pilot --json status`；GUI CLI 入口会使用客户端的 `1000:1000` 身份。动作和取消优先使用宿主薄入口，它负责向本次容器内 CLI 定向转发信号。宿主 `close` 通过 Docker 正常停止、核对退出并回收所属容器；容器内 `close` 会提示使用该生命周期入口。Lua 返回或取消只结束当前动作，实例继续运行；真实断线或原生错误会退出并保留原因。完整参数见 [CLI](docs/CLI.md)。

## 文档与开发

- [业务地图](docs/business-map/README.md)：按领域查看用户结果、责任边界、主要流程与源码入口。
- [游戏 AI 操作指引](docs/PLAY_GUIDE.md)：确认授权目标与角色占用，完成上手观察、动作核对和停止交接。
- [游戏 AI harness](docs/HARNESS.md)：隔离 Codex、角色上下文、游戏工具与开发 AI 协作。
- [命令使用](docs/CLI.md)：实例、观察、动作、GUI 入口和错误结果。
- [Lua API 参考](docs/LUA_API.md)：写脚本使用的状态字段、函数参数、返回值与错误语义。
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
