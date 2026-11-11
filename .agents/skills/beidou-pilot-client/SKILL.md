---
name: beidou-pilot-client
description: "使用 beidou-pilot 北斗游戏客户端时使用：寻找和接续工作台、启动与登录已有角色、处理无账号或首次建角、观察状态、执行 Lua、取消及关闭。新会话接手游戏或排查登录停住时优先使用；需求收集使用 beidou-pilot-requirements。"
---

# 北斗客户端操作

让新会话尽快接上正确的游戏实例。先复用已授权的工作台与角色，按实际状态选择登录路径；缺少账号、角色和客户端能力是不同问题。

## 找回入口与已有进度

- 技能源文件维护在北斗仓库 `.agents/skills/beidou-pilot-client/`。从用户技能目录的链接调用时，先解析技能真实路径找回仓库；不要在当前其他项目中猜客户端命令。
- 首次操作先读仓库 `AGENTS.md` 和 [游戏 AI 操作指引](../../../docs/PLAY_GUIDE.md)；本会话已读过的内容不重复加载。精确参数查根入口 `beidou-pilot --help`，按需读 [CLI](../../../docs/CLI.md)，不先通读源码、历史 Issue 或服务端实现。
- 从用户指令、仓库未跟踪的 `LOCAL.md` 等本机索引及已有交接记录找到工作台、profile、目标、养成计划和操作者。只读取本次所需内容，不回显凭据，不扫描所有账号文件。不要把私密值或某台机器的运行路径复制进技能。
- 沿用本次任务已有的目标、账号及玩法授权；不逐步重问已经明确的选择。文件存在或服务可访问不能单独证明授权。

未找到实例索引时，可只读发现新入口登记的容器：

```bash
docker ps -a --filter label=beidou.workbench \
  --format '{{.Names}}\t{{.Label "beidou.workbench"}}\t{{.Label "beidou.client.instance"}}\t{{.Label "beidou.backend"}}\t{{.Status}}'
```

结果只提供位置线索；无结果也不能证明没有旧实例或其他操作者。`instances` 只报告所属容器，不能列出全机工作台。同一目标同一角色只能有一个控制者，GUI 仅一名明确操作者；发现活动脚本或 harness 先按已有认领完成交接。

## 先选正确分支

| 当前事实 | 下一步 |
| --- | --- |
| 已有运行实例、角色正确 | 读 `status`、`script status`、`snapshot`，接续原版本；无需重新 `open` 或重建 |
| 有专用账号和已有角色，实例未运行 | 检查 profile 与 target，执行下方已有角色登录路径 |
| 找不到 profile、但已有工作台或账号池 | 先按本机索引找回已授权资料；不直接判成“没有账号” |
| 确实无账号，或有账号但没有角色 | 读 [账号准备与首次登录](references/first-login.md)，区分注册、首次声明和建角；不反复尝试已有角色登录 |

## 已有角色的最短登录路径

以下在仓库根执行，将工作台和实例名替换为已确认值；GUI 使用 `--backend beidou`，实例名必须为 `default`。

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --json status
./beidou-pilot --workbench /external/workbench --instance worker-a --backend headless --json plan
./beidou-pilot --workbench /external/workbench --instance worker-a --backend headless --json open
./beidou-pilot --workbench /external/workbench --instance worker-a --json snapshot
```

- 工作台必须已存在，默认提供 `account.private.json`、`resources.json` 和需要时的 `target.json`。可在 `plan/open` 后用 `--profile PATH --resources PATH --target PATH` 指定已有文件；不复制一套重复配置。
- profile 权限严格为 `0600`，必填 `username/password/character_id`；`character_id` 是已有角色的正 int32 CID。`world/channel` 默认 0，第 1 频道写 `channel=0`。GUI 仅支持 `world=0`、第 1 至 20 频道。密码不放命令参数或输出，旧 `--character/--character-index/--channel` 登录参数已退役。
- `plan` 只读核对目标，不构建或启动。隔离目标核对项目、服务、精确镜像与 internal 网络；常驻工作区目标仅在已有授权时给 `plan/open` 加 `--workspace-server`。启动器不负责启动游戏服务端。
- 新实例默认用 `main` 已提交版本构建或复用镜像。已有实例继续使用启动时的 CLI、内置 Lua 和桥；查 `status` 的 `source_revision/image/run_id`，不能用当前宿主 HEAD 代替实际版本。开发验收明确用 `--ref COMMIT`。
- `open` 不自动建角。成功需确认新鲜状态 `ready=true`、匹配的角色 CID/名称、频道、地图、位置及本次原生 `instance_id/run_id`；容器运行或认证成功均不足以证明入图。

失败先读 `status` 与所属工作台 `runtime/INSTANCE/` 日志。`profile_invalid/private_file_permissions` 核对私密文件格式和权限；`character_not_unique` 核对实际角色名单；`open_timeout/open_stage_unknown` 看 GUI 当前阶段与截图。`input_busy` 先看活动脚本和控制者；身份不符保留现场。`--timeout` 只限制入图等待，延长它不能补出账号、角色或处理首次声明。

## 观察、执行和停止

日常操作只经根 `beidou-pilot` 薄入口进入所属容器；不要回到宿主 Python、旧 `headless/agent` 或临时直接按键链。先 `snapshot`，再按需 `capabilities`、`inspect scene/inventory/quests/skills`。具体动作查 CLI，Lua 查 [LUA_API.md](../../../docs/LUA_API.md)；维护公共策略另读 `shared/scripts/AGENTS.md`。

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --json script run --code 'game.log("你好，Lua"); game.sleep(0.1)' --seconds 20
./beidou-pilot --workbench /external/workbench --instance worker-a --json script status
./beidou-pilot --workbench /external/workbench --instance worker-a --json script cancel --session SCRIPT_ID
./beidou-pilot --workbench /external/workbench --instance worker-a --json bridge status
```

- `script run` 等待结束；`script start` 受理后返回，结束模型回合不会取消脚本。取消使用当前 `script.id`，或向原 `script run` 命令发 Ctrl+C/SIGTERM；核对同一原生身份的终态和 `held_keys=[]`。
- 用户文件路径按容器内部解释，工作台 `scripts/` 对应 `/scripts`；可在已有实例提交新 Lua，无需为此重建或重登。角色策略用 Lua，不加 Python 逐帧控制。
- 动作受理、脚本完成和放键分别核对，游戏效果读实际位置、HP/MP、库存、任务等。结果不明先观察，尤其不重放消费、奖励、加点和交易。
- 短脚本结束或取消保留客户端。需要下线时用宿主 `close`，再读 `status` 核对退出；容器内 `close` 会报 `host_lifecycle_required`。危险区域结束后先按已核实路径回到安全位置或关闭所属实例，再长时间分析。

交接写回所属工作台：本次目标与角色、控制权、实际进度、下一步、运行版本和必要证据位置。凭据、养成记录和运行数据不进入源码、技能或 Serena 记忆。汇报分别说明准备、入图和实际动作结果。
