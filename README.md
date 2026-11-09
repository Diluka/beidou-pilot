# beidou-pilot

供人工、脚本和 harness 驱动的游戏客户端工具：管理实例、读取结构化状态、执行原生动作和 Lua。无头端用于多实例，北斗 GUI 适配器用于按需验证与排障。客户端不集成模型、性格、长期目标或玩家记忆。

## 组件布局

```text
cli/             命令入口、实例管理、观察、测试
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
docker build -t local/beidou-pilot:local .
./cli/beidou-pilot --help
```

编译在 Docker builder 中完成。运行镜像只带客户端、必要动态库和许可证；北斗原客户端、NX、账号和运行状态都由外部提供。

把 [resources.example.json](cli/config/resources.example.json) 复制为 `cli/config/resources.json`，配置外部 `headless_resources`。已有匹配 NX 可直接复用；从原始客户端转换、可选 WZ XML 及 GUI 前置条件见[架构与支持范围](docs/ARCHITECTURE.md)。

## 操作实例

准备已核验的 target 和权限为 `0600` 的已有账号 profile，按实例名操作：

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json open \
  --target /external/target.json --profile /private/account.private.json
./cli/beidou-pilot --backend headless --instance worker-a --json snapshot
./cli/beidou-pilot --backend headless --instance worker-a --json capabilities
./cli/beidou-pilot --backend headless --instance worker-a --json close
```

`open` 后容器后台常驻。Lua 返回、期限结束或取消只结束当前动作，`close` 才关闭并回收实例；真实断线或错误会退出并保留原因。

## 文档与开发

- [命令使用](docs/CLI.md)：实例、观察、动作、GUI 入口和错误结果。
- [Lua API 参考](docs/LUA_API.md)：写脚本使用的状态字段、函数参数、返回值与错误语义。
- [Lua 与控制协议](docs/CONTROL.md)：脚本、控制权、取消和效果边界。
- [架构与支持范围](docs/ARCHITECTURE.md)：代码职责、外部资源、两端能力和限制。
- [依赖管理](docs/DEPENDENCIES.md)：子模块、派生源码与许可来源。
- [开发约定](AGENTS.md)：维护规则与 Serena 项目记忆。

从仓库根运行离线测试：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli -v
```

项目采用 [AGPL-3.0-only](LICENSE)，第三方保留各自授权，详见 [NOTICE](NOTICE)。外部游戏客户端与素材不属于本项目的软件许可范围。

项目开发记忆入口为 [.serena/memories/core.md](.serena/memories/core.md)。使用仓库真实绝对路径激活 Serena 项目 `beidou-pilot`；当前只启用记忆，不启动语言服务，维护规则见 [AGENTS.md](AGENTS.md)。
