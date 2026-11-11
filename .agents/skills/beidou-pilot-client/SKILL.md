---
name: beidou-pilot-client
description: "使用 beidou-pilot 仓库提供的 Docker 客户端：登录已有角色、观察游戏状态、执行和取消 Lua，并判断首次登录的支持范围。实际操作客户端或排查登录时使用；需求讨论使用 beidou-pilot-requirements。"
---

# 北斗客户端的 Docker 用法

headless 与 GUI 两个镜像安装同一份 `beidou-pilot` CLI、辅助引擎和内置 Lua，分别提供无头原生环境与 Wine/GUI 环境。客户端命令在所属容器内执行，宿主不加载 Python 客户端或策略。

## 仓库入口与实例身份

- 首次操作先读仓库 `AGENTS.md`；本会话已读内容不重复加载。构建、容器创建与关闭按 [README](../../../README.md) 和 [CLI](../../../docs/CLI.md) 的仓库入口执行。
- 新实例默认从 `main` 的已提交版本构建或复用镜像。已有容器保持启动时的代码，实际后端、源码与镜像版本读取 `status`；更新源码不要求重建正在使用的实例。
- 从本次任务确认目标容器、账号角色及操作者，沿用已有授权。同一目标同一角色只有一名控制者，GUI 保持一名明确操作者。
- `instances` 只报告本容器。命令的 `--root/--backend/--instance` 用于核对本容器身份，不能用来切换连接或接管其他实例。请求、结果和取消继续核对原生 `instance_id/run_id`。
- 原版资源 `/client` 与 NX `/data` 保持各自现有来源、格式和只读挂载；原始 IMG 直读尚未实现。配置、桥和运行资源的装配以仓库文档为准。

确认所属容器后，先做只读观察：

```bash
docker exec CONTAINER beidou-pilot --help
docker exec CONTAINER beidou-pilot --json status
docker exec CONTAINER beidou-pilot --json instances
docker exec CONTAINER beidou-pilot --json script status
docker exec CONTAINER beidou-pilot --json snapshot
```

已有正确角色且已入图时，直接接续观察与脚本，不重复登录。发现活动脚本或其他控制者时，先完成控制权交接。

## 已有角色登录与公共配置

容器由仓库入口准备后，容器内 `open` 完成或确认登录。`ACCOUNT_PATH` 是容器内已提供的账号 JSON 路径：

```bash
docker exec CONTAINER beidou-pilot --json open --account ACCOUNT_PATH
```

两端读取同一份账号 schema，文件权限必须为 `0600`：

| 字段 | 要求 |
| --- | --- |
| `username/password` | 非空字符串，不含控制字符；密码不放在命令参数或输出中 |
| `character_id` | 已有角色的真实正 int32 ID |
| `world/channel` | 可选的0基整数索引，默认各为0；第1频道写 `channel=0` |

GUI 自动登录仅支持世界0和第1至20频道。`open` 不自动注册或建角；没有真实 CID、停在首次声明、性别选择或空角色列表时，读[账号准备与首次登录](references/first-login.md)。

可选的 `open --server SERVER_PATH` 读取容器内服务器 JSON，仅核对当前实例的服务器，不更换连接。其公共 schema 必填非空字符串 `project/service/expected_image`，可选非空字符串 `network`；提供的字段必须与本实例登记一致。容器创建、服务器镜像及网络核验仍由仓库生命周期入口负责。

成功需核对新鲜状态 `ready=true`、目标角色 CID/名称、频道、地图、位置与原生身份。账号认证或容器运行本身不足以证明入图。失败先读 `status` 和其诊断；身份不符、`character_not_unique` 或未知首次阶段时保留现场，按实际结果处理。

## 观察与能力判断

先取 `snapshot`，再按问题读取能力和领域事实：

```bash
docker exec CONTAINER beidou-pilot --json capabilities
docker exec CONTAINER beidou-pilot --json inspect scene
docker exec CONTAINER beidou-pilot --json inspect inventory
docker exec CONTAINER beidou-pilot --json bridge status
```

两端共享 CLI，支持范围分别以本端 `capabilities` 和返回结果为准。未知资料保留未知，未支持能力明确报告；不从另一后端或服务器补造客户端事实。命令参数查 [CLI](../../../docs/CLI.md)，Lua 状态、动作和错误查 [Lua API](../../../docs/LUA_API.md)；维护仓库公共策略前读 `shared/scripts/AGENTS.md`。

## 执行 Lua 与停止

持续控制优先使用原生 `script start`，保留返回的 `script.id`，再按该会话查询和显式取消。`LUA_PATH` 按容器内路径解释，用户 Lua 可作为运行输入提交，无需为此重建镜像。

```bash
docker exec CONTAINER beidou-pilot --json script start LUA_PATH --continuous
docker exec CONTAINER beidou-pilot --json script status
docker exec CONTAINER beidou-pilot --json script cancel --session SCRIPT_ID
docker exec CONTAINER beidou-pilot --json bridge status
```

- `--continuous` 须由操作者明确选择；有界执行使用 `--seconds N`。`script start` 在原生受理后返回，结束终端调用、模型回合或事件监听不会取消脚本。
- 取消只针对匹配的当前 `script.id`。核对同一 `instance_id/run_id` 的终态与 `held_keys=[]`；旧会话 ID 不能取消新脚本。活动 Lua 占有本实例输入，其他动作遇到 `input_busy` 时先确认控制者。
- `script run` 同步等待完成。需要通过 Ctrl+C/SIGTERM 定向取消同步调用时，使用仓库宿主入口的信号转发，具体用法见 [CLI](../../../docs/CLI.md)。直接结束 `docker exec` 调用不能代替原生取消确认。
- 脚本受理、完成、放键和真实游戏效果分别核对，依据实际位置、HP/MP、库存或任务等事实判断。结果不明先观察，尤其不重放消费、奖励、加点和交易。
- 脚本结束或取消会保留客户端。需要下线时通过仓库宿主入口关闭所属容器，并核对退出；容器内 `close` 返回 `host_lifecycle_required`。危险区域结束有界动作后，先进入已核实的安全位置或关闭所属实例，再长时间分析。

客户端 Python 只承担参数、脚本装载/取消和结果投影，角色控制策略使用 Lua。汇报分别说明准备、入图和实际动作结果；凭据和运行数据不写进源码、技能或项目记忆。
