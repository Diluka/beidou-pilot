---
name: beidou-pilot-client
description: "通过 beidou-pilot CLI 登录已有北斗角色、观察游戏状态、执行和取消 Lua，并判断首次登录的支持范围。实际操作客户端或排查登录时使用。"
---

# 北斗客户端 CLI

`beidou-pilot` 是 headless 与 GUI 共用的客户端入口。本技能针对已准备好的当前实例；命令直接执行，输出使用 `--json`。先确认任务授权的账号角色与操作者，同一目标同一角色只有一名控制者，GUI 保持一名明确操作者。

## 观察当前实例

```bash
beidou-pilot --help
beidou-pilot --json status
beidou-pilot --json instances
beidou-pilot --json script status
beidou-pilot --json snapshot
```

`status` 用于核对当前阶段、实际后端、角色和版本。`instances` 只报告当前实例；`--root/--backend/--instance` 用于核对既有身份，连接与其他实例保持原状。请求、结果和取消继续核对原生 `instance_id/run_id`。

每次重新接入先读取 `status`、`script status` 和 `snapshot`，确认现有角色、任务与原生身份。已有正确角色且已入图时，直接接续观察；已有活动任务时沿用它的 `script.id`，不重复 `open/start`、不抢占输入。其他操作者持有控制权时，先完成交接。

LLM 是可选的观察与决策旁路。LLM 的暂停、停止、退出或重新接入不自动取消原生任务，也不关闭客户端；任务不依赖模型会话或调用终端持续在线。需要主动取消任务时明确执行 `script cancel --session`；需要下线时明确请求客户端关闭，分别核对结果。

## 登录已有角色

`open` 完成或确认当前实例的登录。`ACCOUNT_PATH` 是已提供的账号 JSON 路径：

```bash
beidou-pilot --json open --account ACCOUNT_PATH
```

两端读取同一份账号 schema，文件权限必须为 `0600`：

| 字段 | 要求 |
| --- | --- |
| `username/password` | 非空字符串，不含控制字符；密码不放在命令参数或输出中 |
| `character_id` | 已有角色的真实正 int32 ID |
| `world/channel` | 可选的 0 基整数索引，默认各为 0；第 1 频道写 `channel=0` |

GUI 自动登录仅支持世界 0 和第 1 至 20 频道。`open` 要求已有真实 CID；首次登录和建角使用独立命令，两端都经客户端内部路径完成：GUI 由原生桥在游戏线程调用原版客户端内部动作，不再使用桌面键鼠坐标。GUI 建角仅支持空角色列表、`job=1` 和可打印 ASCII 角色名，外观候选须在当前界面实际核验。常驻 v1.12 已实测不存在的短 ASCII 用户名登录后自动注册；用户名建议不超过 10 个 ASCII 字符，验证范围见首次登录参考。没有真实 CID、停在首次声明、性别选择或空角色列表时，读[账号输入与首次登录](references/first-login.md)。

可选的 `open --server SERVER_PATH` 读取服务器 JSON，仅核对当前实例的服务器，不更换连接。必填非空字符串 `project/service/expected_image`，可选非空字符串 `network`；提供的字段必须与本实例登记一致。

成功需核对新鲜状态 `ready=true`、目标角色 CID/名称、频道、地图、位置与原生身份。账号认证成功是入图前置，入图以新鲜状态的完整核对为准。失败先读 `status` 和诊断；身份不符、`character_not_unique` 或未知首次阶段时保留现场，按实际结果处理。

## 按问题读取事实

先取 `snapshot`，再读取相关能力或领域：

```bash
beidou-pilot --json capabilities
beidou-pilot --json inspect scene
beidou-pilot --json inspect inventory
beidou-pilot --json bridge status
```

支持范围以本端 `capabilities` 和返回结果为准。未知资料保留未知，未支持能力明确报告；不从另一后端或服务器补造客户端事实。命令参数查 [CLI](../../../docs/CLI.md)，Lua 状态、动作和错误查 [Lua API](../../../docs/LUA_API.md)。

## 执行和取消 Lua

长期任务优先使用原生 `script start`，由客户端独立执行。保留返回的 `script.id`，按该会话查询和显式取消。`LUA_PATH` 是当前运行环境可读取的 UTF-8 Lua 文件路径。

```bash
beidou-pilot --json script start LUA_PATH --seconds 20
beidou-pilot --json script status
beidou-pilot --json script cancel --session SCRIPT_ID
beidou-pilot --json bridge status
```

- 有界执行使用 `--seconds N`；操作者明确选择长期持续任务时使用 `script start LUA_PATH --continuous`。原生受理后 CLI 返回，任务继续执行；LLM 暂停、停止、退出和结束事件监听均不隐式取消。
- 取消只针对匹配的当前 `script.id`。核对同一 `instance_id/run_id` 的终态与 `held_keys=[]`；旧会话 ID 只对应历史脚本。活动 Lua 占有本实例输入，其他动作遇到 `input_busy` 时先确认控制者。
- `script run` 同步等待结果。`run/start` 等待期间收到 Ctrl+C/SIGINT/SIGTERM 只结束 CLI 等待；已发布任务继续由原生执行，两端语义相同。等待超时或陈旧观察错误时，任务是否受理与停止以当前状态为准。先用 `script status` 核对当前任务与身份，不重放 `start`；主动取消使用 `script cancel --session`，再核对终态和放键。
- Lua 可直接通过 `--code` 提供，与文件输入互斥。例如：

```bash
beidou-pilot --json script run --code 'game.log("观察开始"); game.sleep(0.1)' --seconds 5
```

脚本受理、完成、放键和真实游戏效果分别核对，依据实际位置、HP/MP、库存或任务等事实判断。结果不明先观察，尤其不重放消费、奖励、加点和交易。脚本结束或取消会保留客户端。客户端关闭是另一项明确操作：`close` 返回 `host_lifecycle_required`，交由实例生命周期管理方关闭并核对退出；LLM 退出与客户端关闭分别执行。危险区域的有界任务结束后，先核对角色安全状态；需要移动至安全位置或关闭时，分别明确执行。

客户端 Python 只承担参数、脚本装载/取消和结果投影，角色控制策略使用 Lua。汇报分别说明准备、入图和实际动作结果；凭据和运行数据不写进源码、技能或项目记忆。

需要部署或从外部调用时，再读[部署与外部调用](references/docker.md)。
