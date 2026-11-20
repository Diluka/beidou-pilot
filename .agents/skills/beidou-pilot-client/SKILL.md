---
name: beidou-pilot-client
description: "通过 beidou-pilot CLI 登录已有北斗角色、观察游戏状态、执行和取消 Lua，并判断首次登录的支持范围。实际操作客户端或排查登录时使用。"
---

# 北斗客户端 CLI

`beidou-pilot` 是 headless 与 GUI 共用的容器内入口。宿主用 `workbenches/workbench list [live|dev]` 查找角色：常驻养成用已授权的 `live/NAME`；开发、复现和验收按[开发约定](../../../AGENTS.md)复用空闲的 `dev/NAME`，没有合适角色时可自行建号建角。在所属实例内直接运行以下命令。同一目标同一角色只有一名控制者，GUI 保持一名明确操作者。

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

支持范围以本端 `capabilities` 和返回结果为准。未知资料保留未知，未支持能力明确报告；不从另一后端或服务器补造客户端事实。命令参数查 [CLI](../../../docs/CLI.md)，Lua 入口、只读领域、动作槽与错误查 [Tick Lua API](../../../docs/LUA_TICK_API.md)。

跨图路线只使用客户端原生只读查询 `beidou-pilot --json world-map route START_MAP GOAL_MAP`：需要当前实例已在运行，不启动或控制客户端；客户端与技能都不提供其他路线计算入口，结果按正常数据状态返回，不当作观察错误。

## 技能加点

技能前置不足由客户端拦截；已实测的隔离开发服务端不校验该条件，维护者已接受此已知限制。其他服务端的校验行为不由此推断，不绕过客户端门禁。

确认角色、技能及明确的加点授权后，可用 `beidou-pilot --json skill-up SKILL_ID --points N`；`--points` 默认 1。无头端逐点核对技能等级和 SP 后继续，失败时查看 `details.confirmed`。当前未提交实现为已列举的骑士团、战神职业增加各自初学者组 `10001000`–`10001002`、`20001000`–`20001002` 的独立 SP 池，要求对应三项技能资源完整才放行；未知职业和 Evan 等未核验的多册技能仍拒绝，这些新增职业尚无真实样本验收。请求已发布但结果未知时先重新观察，不重放。当前草稿支持在同一运行实例用 `beidou-pilot --json skill-up-reconcile SKILL_ID --request-id REQUEST_ID` 只读核对原生记录，返回 `confirmed` 或 `unresolved`，不发加点请求；未决记录会保守阻断当前 run 的后续加点。重启不证明旧请求失败，不得自动重发。无头核对已在 `40b16bf` 的开发服真实场景实测，证据见 PR 评论 `7031143430`；该证据不覆盖所有职业或超时场景。

当前 GUI 草稿通过无窗口原生事件逐点加点，覆盖实现中精确列举的普通冒险家职业 `100`–`522` 的祖先组技能，非初学者技能由原生组校验；初学者技能仅覆盖该职业表中的 `1000`、`1001`、`1002`，原生端核查 group0 成员和可见性；扩展职业范围仍待真实游戏验收。特殊职业及 GM 技能拒绝；原生阶段累计门禁不满足或不可核验时拒绝，其他未核实的技能或职业组合也予以拒绝。每点确认同一角色的技能等级及相应点数变化后才继续；结果未知时停止，不重试。在同一运行实例可用 `beidou-pilot --json skill-up-reconcile SKILL_ID --request-id REQUEST_ID` 显式核对原请求，此操作不发送加点事件；仍未知时保留现场，不重放。GUI 无窗口路径已在开发服实测战士多点与法师单点等场景；全职业及超时场景尚未完成验收，不以先前窗口操作的证据代替。具体命令见 [CLI 技能加点](../../../docs/CLI.md#技能加点)。

## AP 自动分配

`workbenches/workbench dev/NAME auto-ap` 无参数，一次提交全部剩余 AP 的自动分配；支持范围以实际结果为准。返回 `unknown` 时先观察同一角色的属性和剩余 AP，不重复发起；不要修改数据库代替客户端操作。详见 [CLI](../../../docs/CLI.md)。

## 执行和取消 Lua

角色动作与持续脚本写在所属角色的 `scripts/`。`LUA_PATH` 可以是 UTF-8 单文件或含 `main.lua` 的目录包；`script describe/run/start` 的相对路径从 `/work/scripts` 解析，容器绝对路径也可显式使用。长期任务用 `script start`，保留返回的 `script.id` 以便查询或取消。

```bash
beidou-pilot --json script start LUA_PATH --seconds 20
beidou-pilot --json script status
beidou-pilot --json script cancel --session SCRIPT_ID
beidou-pilot --json bridge status
```

- 有界执行使用 `--seconds N`；操作者明确选择长期持续脚本时使用 `script start LUA_PATH --continuous`。原生受理后 CLI 返回，脚本继续执行。
- 取消只针对匹配的当前 `script.id`。核对同一 `instance_id/run_id` 的终态与会话级 `control_released`；全局 `held_keys` 可能仍包含其他会话的合法持键。旧会话 ID 只对应历史脚本。活动 Lua 期间普通 GUI 输入遇到 `input_busy` 时先确认控制者。
- `script run` 同步等待结果。`run/start` 等待期间收到 Ctrl+C/SIGINT/SIGTERM 只结束 CLI 等待；已发布任务继续由原生执行，两端语义相同。等待超时或陈旧观察错误时，任务是否受理与停止以当前状态为准。先用 `script status` 核对当前任务与身份，不重放 `start`；主动取消使用 `script cancel --session`，再核对终态和放键。
- 脚本入口须声明 `main(context)`；需要调整调度或预算时在前导注释用 `@tick.*`。例如将下例保存为该角色的 `scripts/observe-tick.lua`：

```lua
local function main(context)
    if context.tick.index == 1 then context.game.log("观察开始") end
    if context.tick.index >= 5 then return "done" end
end
```

```bash
beidou-pilot --json script run observe-tick.lua --seconds 5
```

脚本受理、完成、放键和真实游戏效果分别核对，依据实际位置、HP/MP、库存或任务等事实判断。结果不明先观察，尤其不重放消费、奖励、加点和交易。脚本结束或取消会保留客户端。客户端关闭是另一项明确操作：`close` 返回 `host_lifecycle_required`，交由实例生命周期管理方关闭并核对退出。危险区域的有界任务结束后，先核对角色安全状态；需要移动至安全位置或关闭时，分别明确执行。

客户端 Python 只承担参数、脚本装载/取消和结果投影，角色控制策略使用 Lua。汇报分别说明准备、入图和实际动作结果；凭据和运行数据不写进源码、技能或项目记忆。

需要部署或从外部调用时，再读[部署与外部调用](references/docker.md)。
