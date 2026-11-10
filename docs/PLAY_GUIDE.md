# 游戏 AI 操作指引

本篇供新会话从已有授权开始操作客户端。命令从仓库根执行；`/external/target.json`、`/private/account.private.json` 和 `worker-a` 均须替换为本次已确认的配置与实例名。精确参数查当前 `--help`，完整命令、Lua 与支持范围分别以 [CLI](CLI.md)、[Lua API](LUA_API.md) 和[架构说明](ARCHITECTURE.md)为准。

## 先确认目标、角色和操作者

从用户指令及已有授权记录确认服务器用途、专用账号和角色、允许执行的玩法，以及本次操作者。可在本机 `LOCAL.md` 等环境索引中查找已登记的配置路径；配置文件存在、服务器正在运行或账号能够登录，都不能替代授权。凭据只从已授权的私密文件读取，不放进命令参数、公开日志或 Issue。

常驻工作区服务和开发隔离服务是不同目标。先核对 target 的 `project/service/network/expected_image`，再只读解析其实际容器身份：

```bash
python3 cli/clientctl.py plan --target /external/target.json
./cli/beidou-pilot --backend headless --json instances
./cli/beidou-pilot --backend beidou --json status
```

`plan` 不启动服务或客户端；确认返回的项目、服务、容器、镜像、网络和运行状态属于本次授权目标。目标须使用同项目 internal 网络；隔离目标不得发布宿主端口。常驻 `beidou-ms/beidou-server-all` 仅在已获对应授权时给 `plan` 和 `open` 都加 `--workspace-server`，仍须满足网络与镜像核验。核验失败时先查具体原因与当前配置，不能把另一服务器当作替代目标。

`instances` 只覆盖当前运行根已登记的无头实例。结合该根的 GUI `status`、本机操作者登记和必要的 Docker 容器身份核对账号占用；其他运行根及外部操作者的占用需要另外确认。实例登记中的 CID、频道和 `run_id` 有助于定位，停止的历史登记不代表正在占用。同一目标同一角色只交给一名控制者，GUI 只保留一名明确操作者；发现占用时先完成控制权交接。

## 用已有角色完成最小上手

准备方式见 [README](../README.md#准备)和[外部资源配置](ARCHITECTURE.md#外部资源与配置)。先检查所用后端，再打开已授权角色：

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json doctor
./cli/beidou-pilot --backend headless --instance worker-a --json open \
  --target /external/target.json --profile /private/account.private.json
./cli/beidou-pilot --backend headless --instance worker-a --json status
./cli/beidou-pilot --backend headless --instance worker-a --json bridge status
./cli/beidou-pilot --backend headless --instance worker-a --json capabilities
./cli/beidou-pilot --backend headless --instance worker-a --json snapshot
```

无头 profile 须为 `0600`，包含已有账号及 `character_id`；`world/channel` 为从 0 开始的索引，CLI 返回的频道从 1 开始。`open` 可以复用身份相符的现有实例；`--timeout` 只限制启动等待，容器在命令返回后仍运行。默认运行根是本源码树的 `cli/`；若使用 `--root`，后续所有命令沿用同一绝对路径，它选择运行状态目录，不切换加载的代码版本。

入图需同时确认新鲜状态中的 `ready`、角色 ID/名称、地图及位置；桥的 `instance_id/run_id` 应保持属于本次运行，CLI 会核对登记与原生身份。报告实际核对的服务器、频道、角色、地图和所用后端；缺字段时保留未知。仅有容器运行、登录认证或角色选择成功，不足以判断已入图。启动失败后先读 `status` 和错误中的运行目录；重开前确认原实例情况。

## 观察、选择能力并核对结果

先读 `snapshot`，再按需使用 `inspect scene/inventory/quests/skills`，参数及输出见 [CLI](CLI.md#启动观察与关闭)。`capabilities` 的 `native_actions` 来自有效在线桥，离线为 `null`；具体领域还需检查响应的支持状态、来源和时效。未知值保持未知，例如当前无头任务是完整角色包快照，不能当作实时任务进度。

在已确认安全区域，先选择一项有界动作并比较前后观察。下面只适用于已核实右侧可安全短移的场景：

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json walk right --seconds 0.2
./cli/beidou-pilot --backend headless --instance worker-a --json snapshot
./cli/beidou-pilot --backend headless --instance worker-a --json script status
```

根据实际坐标与场景判断移动；按经验/等级判断战斗成长，按库存及 HP/MP 判断消耗恢复，按槽位变化判断换装。请求受理、输入派发、脚本完成和放键分别是不同事实，均不能独立证明命中、拾取或任务完成。消费、交易、奖励、加点等结果不明时先重新观察，避免重放不可逆操作；成长决策依据已核实的职业路线和本地养成计划。

持续策略写 Lua，入口为 `script run FILE --seconds N` 或 `script run --code CODE --seconds N`；文件与源码二选一，持续模式需明确 `--continuous`。运行中可继续只读观察。写脚本先查 [Lua API](LUA_API.md)，维护公共策略另读 [shared/scripts/AGENTS.md](../shared/scripts/AGENTS.md)。同层移动、单根绳梯和门户能力均有场景前提；缺少能力或静态资料时按当前错误与[缺口索引](CLIENT_LIMITATIONS.md)处理。

## GUI 与首次登录的边界

需要当前仅 GUI 支持的操作时，先按授权完成实例与角色交接，再按 [GUI 准备与登录](CLI.md#原版-gui)运行。GUI 使用默认单实例；账号来自运行根的 `account.private.json`，已有角色可用 `open --character NAME --channel N --target PATH` 明确选择。通过 `snapshot`、`inspect stage` 和 `screenshot` 核对当前界面，优先使用当前对话正文与新鲜引用操作；GUI 桌面 `click X Y` 使用根桌面坐标，需根据当次截图定位。

已有角色自动登录尚不覆盖新账号的全部流程。首次登录可能停在声明或性别选择；声明须在原界面滚到底部才可确认。空角色列表可能返回 `character_not_unique`，这时需要正常创建角色，不能解释为已选中或已入图。无头首次声明、性别和建角能力由 [#72](https://github.com/Diluka/beidou-pilot/issues/72) 跟踪；当前 GUI 正常界面路径可在明确账号、角色名及选择意图后执行。无法确认的选择留待决定，不反复重试登录。

GUI 遇到上述界面时先截图；现有根桌面点击及 `python3 cli/beidou_pilot/engines/desktop.py scroll --help` 可帮助定位所需原语。桌面入口通过 `CLIENT_ROOT` 选择运行根，默认本源码树的 `cli/`，不接受统一 CLI 的 `--root`。使用自定义运行根时须显式指向同一目录，例如：

```bash
CLIENT_ROOT=/external/client-cli python3 cli/beidou_pilot/engines/desktop.py scroll down --ticks 1
```

滚轮作用于当前鼠标所在控件，须先按当次画面定位，再有界滚动并重新截图确认。该路径不代表 CLI 已自动识别首次流程，也不补齐无头能力。NPC 接交任务等无头缺口见 [#48](https://github.com/Diluka/beidou-pilot/issues/48) 与[两端能力表](ARCHITECTURE.md#两端能力)。

## 停止、下线与交接

活动 Lua 通过原执行 CLI 的 Ctrl+C/SIGTERM 取消并等待收尾；使用 harness 时先由其 `pause` 或 `stop` 确认取消与放键，再交接。不要用第二个动作命令接管仍活动的脚本。详情见[控制协议](CONTROL.md#控制权期限与取消)与 [harness 协作通道](HARNESS.md#开发-ai-的协作通道)。

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json script status
./cli/beidou-pilot --backend headless --instance worker-a --json bridge status
./cli/beidou-pilot --backend headless --instance worker-a --json close
./cli/beidou-pilot --backend headless --instance worker-a --json status
```

取消后核对同一原生身份下的脚本/命令终态和 `held_keys=[]`；有惯性或动画时继续观察实际停止。空闲遗留控制可用 `stop`，它不抢占其他活动控制者。短脚本结束与取消保留客户端；`close` 才正常关闭所属容器，最后确认 `running=false`。危险区域结束执行后，先到已知安全位置或关闭所属实例，再做长时间分析。

在本地保留所用源码/镜像或桥版本、目标与实例身份、场景、动作前后事实和未确认项；公开记录只给无私密结论。离线检查、构建、入图、移动、战斗和恢复分别报告；指南、请求成功或另一端结果均不能替代本端实际证据。
