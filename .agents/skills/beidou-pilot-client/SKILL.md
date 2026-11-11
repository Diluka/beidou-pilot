---
name: beidou-pilot-client
description: "通过统一 workbench 入口和工作目录使用北斗 Docker 客户端：接续已有角色、构建或启动实例、观察状态、执行和取消 Lua，并处理账号准备与首次登录。新会话接手游戏或排查登录停住时使用；需求讨论使用 beidou-pilot-requirements。"
---

# 北斗客户端的 Docker 用法

通过 Docker 工作台接续已授权的角色和养成进度。先找到工作目录、现有容器与操作者，再按实际状态选择观察、登录或首次流程。

## 唯一入口与运行边界

- 宿主统一使用 `private/workbenches/workbench DIR COMMAND`。Docker 构建、启停、版本路由和取消转发直接在这个脚本里完成；不使用根宿主 `beidou-pilot` 或每目录 `pilot`。
- 客户端分为 headless、GUI 两个镜像，安装同一份 CLI、辅助引擎和内置 Lua。宿主入口通过 `docker exec` 调用所属容器内的 `beidou-pilot`，容器内直接使用本容器进程、桥和显示环境。
- 一个工作目录对应一个角色与容器，实例名固定为 `default`，原生 `instance_id/run_id` 继续核对。新实例默认从 `main` 的已提交版本构建或复用镜像；已有实例保持启动版本，实际版本和后端看 `status` 回报。
- 目录内维护 `account.json`、养成计划、交接记录、用户 Lua 和运行数据。可选 `workbench.json` 保存新建参数；公共资源路径只在主检出目录中的 `private/workbenches/resources.json` 维护一份，普通目录不再保存 `resources.json/server.json`。
- 常驻服务器由统一入口固定。开发隔离目标必须在目录内的 `workbench.json.server` 显式声明，沿用非工作区服务、无宿主端口和 internal 网络核验；不要用默认常驻目标做开发或注册试探。
- 整个工作目录读写挂到 `/work`，本次快照、桥和日志在 `/work/runtime/default/RUN_ID/`，用户 Lua 使用 `/work/scripts/`。原版 `/client` 和现有 NX `/data` 的来源、格式和只读挂载保持现状；原始 IMG 直读尚未实现。

日常动作通过统一入口操作，它会把 Ctrl+C/SIGTERM 定向转发给本次容器内 CLI 并等待取消。创建和关闭容器也通过该入口；工作目录不保存客户端源码副本。`private/` 下只有这个公共脚本纳入 Git，账号、共享资源配置、角色目录和运行数据保持忽略。

## 找回工作目录与已有进度

- 技能源文件维护在北斗仓库 `.agents/skills/beidou-pilot-client/`。从用户技能目录的链接调用时，先解析真实路径找回仓库；不要在其他项目里猜客户端命令。
- 首次操作先读仓库 `AGENTS.md` 和[游戏 AI 操作指引](../../../docs/PLAY_GUIDE.md)；本会话已读内容不重复加载。精确参数查 `private/workbenches/workbench --help`，按需读[CLI](../../../docs/CLI.md)，不先通读源码、历史 Issue 或服务端实现。
- 从用户指令、本机索引和已有交接记录确认工作目录、角色、养成计划和操作者。只读本次所需资料，不回显凭据或扫描所有账号文件；私密值和某台机器的路径不写进技能。
- 沿用本次任务已有的目标、账号和玩法授权，不逐步重问已经明确的选择。目录或文件存在、服务可访问都不能单独证明授权。

在仓库根先发现已有目录，再读取选中目录的记录：

```bash
private/workbenches/workbench --list
private/workbenches/workbench /external/workbench notes
private/workbenches/workbench /external/workbench status
```

只给目录时默认 `status`，不隐式登录。没有目录索引时，还可只读发现已登记容器：

```bash
docker ps -a --filter label=beidou.workbench \
  --format '{{.Names}}\t{{.Label "beidou.workbench"}}\t{{.Label "beidou.client.instance"}}\t{{.Label "beidou.backend"}}\t{{.Status}}'
```

这些结果只是位置线索；无结果不能证明没有旧实例或其他操作者。`instances` 只报告所属容器。同一目标同一角色只交给一名控制者，GUI 也只有一名明确操作者；发现活动 Lua 或 harness，先按已有认领完成交接。

核对容器归属后，可直接做只读排查：

```bash
docker exec CONTAINER beidou-pilot --json status
```

## 按当前事实选择路径

| 当前事实 | 下一步 |
| --- | --- |
| 已有运行容器、角色正确 | 读 `status`、`script status`、`snapshot`，接续原版本；无需重新 `open` 或构建 |
| 有专用账号和真实角色 CID，容器未运行 | 检查目录内 `account.json` 及必要启动设置，再走下方登录路径 |
| 找不到账号配置，但已有工作台或账号池 | 先按本机索引找回授权资料，不直接判定“没有账号” |
| 确实无账号，或账号没有角色 | 读[账号准备与首次登录](references/first-login.md)，区分注册、声明与建角，不反复尝试已有角色登录 |

## 已有角色的最短登录路径

以下在仓库根执行，只需替换已确认的工作目录：

```bash
private/workbenches/workbench /external/workbench plan
private/workbenches/workbench /external/workbench open
private/workbenches/workbench /external/workbench snapshot
```

需要提前准备镜像时使用同一入口的 `build`；`open` 会自动构建或复用。启动设置都在工作目录里，不再通过宿主配置参数覆盖。GUI 的最小 `workbench.json` 为：

```json
{"backend":"beidou"}
```

未指定后端时默认 headless。`ref`、`timeout`、`bridge_artifact` 和开发隔离 `server` 仅在确有需要时按[CLI](../../../docs/CLI.md)配置，不把全部默认值复制进每个目录。新建设置不替换运行中容器的快照。

- `account.json` 严格保持 `0600`，必填 `username/password/character_id`，CID 为已有角色的正 int32。`world/channel` 默认 0，第 1 频道写 `channel=0`。GUI 仅支持世界 0 和第 1 至 20 频道。密码不放进命令参数或输出。
- `plan` 只读核对选定服务器，不构建或启动；入口不负责启动游戏服务端。普通服务器固定，目录中显式的开发隔离配置仍须经过目标、镜像与网络核验。
- `open` 不自动建角。成功需确认新鲜状态 `ready=true`、匹配的 CID/名称、频道、地图、位置，以及本次原生 `instance_id/run_id`；容器运行或账号认证都不足以证明入图。

失败先读 `status` 和所属目录的 `runtime/default/` 日志。`profile_invalid/private_file_permissions` 核对账号格式和权限；`character_not_unique` 核对实际名单；`open_timeout/open_stage_unknown` 看当前 GUI 阶段和截图。`input_busy` 先看脚本与控制者，身份不符时保留现场。延长工作台入图等待不能补出账号、角色或首次声明处理能力。

## 观察、执行与停止

先 `snapshot`，再按需使用 `capabilities`、`inspect scene/inventory/quests/skills`。动作参数查[CLI](../../../docs/CLI.md)，Lua 查[LUA_API.md](../../../docs/LUA_API.md)；维护公共策略另读 `shared/scripts/AGENTS.md`。

```bash
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --seconds 20
private/workbenches/workbench /external/workbench script status
private/workbenches/workbench /external/workbench script cancel --session SCRIPT_ID
private/workbenches/workbench /external/workbench bridge status
private/workbenches/workbench /external/workbench close
```

- 用户文件路径在容器内解释；工作目录的 `scripts/` 就是 `/work/scripts/`。可以在已有实例提交新 Lua，无需为此重建或重登；角色策略不使用 Python 逐帧控制。
- `script run` 等到结束，原调用方可用 Ctrl+C/SIGTERM 取消；`script start` 受理后返回，结束模型回合不会取消它，需使用当前 `script.id` 显式取消。核对同一原生身份的终态和 `held_keys=[]`。
- 动作受理、脚本完成、放键与真实游戏效果分别核对；读实际位置、HP/MP、库存、任务等。结果不明先观察，尤其不重放消费、奖励、加点和交易。
- 短脚本结束或取消保留客户端。需要下线时用宿主入口 `close`，再读 `status` 核对退出；容器内 `close` 会报告 `host_lifecycle_required`。危险区域结束后先回到已核实安全位置或关闭所属实例，再长时间分析。

交接写回同一工作目录：目标与角色、控制权、实际进度、下一步、运行版本和必要证据位置。凭据、养成记录和运行数据不进入源码、技能或 Serena 记忆。汇报分别说明准备、入图和实际动作结果。
