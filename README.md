# beidou-pilot

面向脚本和 AI 的游戏客户端工具：脚本承担主要驱动工作，AI 在客户端外部负责决策。工具负责管理实例、读取结构化状态、执行原生动作和 Lua。无头端用于多实例，北斗 GUI 适配器用于按需验证与排障。客户端运行体不集成模型、性格、长期目标或玩家记忆；同仓 `harness/` 独立消费这些客户端能力，持有游戏 AI 的模型会话、角色设定与经历。

## 组件布局

```text
cli/             命令入口、实例管理、观察、测试
docker/          客户端及独立 Codex 镜像、GUI Compose 与启动脚本
harness/         游戏 AI 宿主薄控制器、独立模型会话与专用协作入口
headless/        无头客户端宿主和适配器
beidou-ijl15/    原版客户端 DLL 工程和适配器
shared/
  lua-runtime/   两端共用的 C++ Lua 调度与 game API
  scripts/       公共 Lua 策略和示例
third_party/     上游依赖
```

两个客户端分别链接同一份共享运行体，各实例拥有独立 Lua 状态；平台能力通过各自适配器实现，公共脚本按能力声明运行。

## 准备

需要 Docker，以及运行 CLI 的 Python 标准库环境。先初始化固定依赖，再构建无头镜像：

```bash
git submodule update --init --recursive
docker build -f docker/headless/Dockerfile -t local/beidou-pilot:local .
./cli/beidou-pilot --help
```

无头编译在 Docker builder 中完成，运行镜像只带客户端、必要动态库和许可证。原版 GUI 使用独立 Wine/VirtualGL 镜像，按需从项目根构建：

```bash
docker build -t local/beidou-v17-client:intel docker/gui
```

两个镜像的定义与 GUI 的 [Compose](docker/compose.yaml)、启动脚本统一放在 `docker/`；北斗原客户端、NX、账号和运行状态由外部提供。

把 [resources.example.json](cli/config/resources.example.json) 复制为 `cli/config/resources.json`，配置所用后端的外部路径：无头端使用 `headless_resources`，GUI 使用 `gui_client` 和 `gui_dll`。GUI 将原客户端只读挂到 `/client`，在容器内准备运行副本并替换 DLL，保留源目录不变。已有匹配 NX 可直接复用；资源转换、可选 WZ XML 及 GUI 前置条件见[架构与支持范围](docs/ARCHITECTURE.md)。

## 操作实例

准备已核验的 target 和权限为 `0600` 的已有账号 profile。GUI 和无头端都通过 `open --profile PATH` 读取同一格式的文件：`username`、`password`、`character_id`，以及可省略的 `world` 和 `channel`（从 0 开始，默认 0）。同一目标和角色一次只使用一个客户端。无头端可按实例名操作：

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json open \
  --target /external/target.json --profile /private/account.private.json
./cli/beidou-pilot --backend headless --instance worker-a --json snapshot
./cli/beidou-pilot --backend headless --instance worker-a --json capabilities
./cli/beidou-pilot --backend headless --instance worker-a --json close
```

需要原版 GUI 时，先完成上述实例的交接，再用同一 target 和 profile 打开默认单实例：

```bash
./cli/beidou-pilot --backend beidou --json open \
  --target /external/target.json --profile /private/account.private.json
./cli/beidou-pilot --backend beidou --json close
```

GUI 只支持 `world=0`。常驻工作区目标需要已有授权并显式传 `--workspace-server`。完整登录条件见 [CLI](docs/CLI.md#启动观察与关闭)。

`open` 后容器后台常驻。Lua 返回、期限结束或取消只结束当前动作，`close` 才关闭并回收实例；真实断线或错误会退出并保留原因。

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
