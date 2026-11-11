# 游戏 AI 操作指引

本篇供新会话从已有授权继续工作台。宿主使用仓库根的 `./beidou-pilot`，客户端命令由它转发给所属容器。以下 `/external/workbench` 和 `worker-a` 须替换为本次已确认的工作台与实例名；参数以 `--help` 为准，完整命令、Lua 与支持范围见 [CLI](CLI.md)、[Lua API](LUA_API.md) 和[架构说明](ARCHITECTURE.md)。

可使用仓库技能 [beidou-pilot-client](../.agents/skills/beidou-pilot-client/SKILL.md) 按当前状态选择最短路径；缺少账号、没有角色或停在首次界面时，查其[账号准备与首次登录](../.agents/skills/beidou-pilot-client/references/first-login.md)，不要反复执行已有角色的 `open`。

## 先确认目标、角色和操作者

从用户指令及已有记录确认服务器用途、专用账号与角色、允许的玩法和本次操作者。工作台中的养成方案和交接记录负责跨会话连续性，源码版本不会替代这些资料。可从本机 `LOCAL.md` 等索引找到配置；文件存在、服务运行或账号可登录均不能替代授权。凭据只从授权私密文件读取，不进入参数值、日志或 Issue。

工作台提供成对的 `account.json`、`server.json`，以及 `resources.json`。先核对服务器的 `project/service/expected_image` 和可选 `network`，再执行只读检查：

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --json plan
./beidou-pilot --workbench /external/workbench --instance worker-a --json status
```

`plan` 不构建、不启动客户端或服务。确认返回的项目、服务、容器和镜像属于本次目标。显式指定的网络必须是同项目 internal 网络，隔离服务器不得发布宿主端口。常驻 `beidou-ms/beidou-server-all` 仅在已有授权时给 `plan/open` 加 `--workspace-server`；`server.json` 未指定网络时，启动器为新实例准备所属 internal 连接。核验失败先查当前配置与实际原因，不切换到另一服务器代替。

结合本地认领、其他工作台与外部操作者、服务器在线账号/角色列表判断占用。`status` 只说明当前工作台实例，停止的历史登记不能证明账号空闲。同一目标同一角色只交给一名控制者，GUI 只保留一名明确操作者；发现占用先完成交接。

## 用已有角色完成最小上手

准备方式见 [README](../README.md#准备)和[外部资源配置](ARCHITECTURE.md#外部资源与配置)。新实例默认使用 `main` 当时的已提交版本构建或复用镜像；开发验证明确加 `--ref COMMIT`。已有容器后续命令继续使用启动时的 CLI 与内置 Lua，不重新装载当前主检出。

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --backend headless --json open
./beidou-pilot --workbench /external/workbench --instance worker-a --json doctor
./beidou-pilot --workbench /external/workbench --instance worker-a --json status
./beidou-pilot --workbench /external/workbench --instance worker-a --json bridge status
./beidou-pilot --workbench /external/workbench --instance worker-a --json capabilities
./beidou-pilot --workbench /external/workbench --instance worker-a --json snapshot
```

两端使用同一份 `account.json`（权限 `0600`）：`username/password/character_id`，以及默认各为 0 的 `world/channel`。`character_id` 指已有角色；频道索引从 0 开始，返回的实际游戏频道从 1 开始。启动器可显式接收 `--account/--server/--resources` 覆盖工作台默认路径，将本次账号和完整服务器配置保存在工作台的 `runtime/INSTANCE/RUN_ID`。整个工作台读写挂到容器 `/work`，`CLIENT_ROOT` 指向本次运行目录。`--timeout` 只限制入图等待。

入图需同时确认新鲜状态中的 `ready`、角色 ID/名称、频道、地图和位置，原生 `instance_id/run_id` 仍须属于本次运行。`status` 还提供 `source_revision/image/run_id`，用它说明正在验证哪个版本。容器运行、认证成功或角色选择成功都不足以证明已入图。启动失败先读 `status` 和工作台 `runtime/INSTANCE/` 中的运行日志，保留未确认事实，再决定是否重开。

## 观察、选择能力并核对结果

先读 `snapshot`，再按需使用 `inspect scene/inventory/quests/skills`。`capabilities.native_actions` 来自有效在线桥；领域响应中的支持状态、来源与时效分别判断，未知保持未知。无头任务支持正常增量，但原始进度串及关联语义不推断。

在已确认安全区域选择一项有界动作并比较前后事实。下面仅适用于已核实右侧可安全短移的场景：

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --json walk right --seconds 0.2
./beidou-pilot --workbench /external/workbench --instance worker-a --json snapshot
./beidou-pilot --workbench /external/workbench --instance worker-a --json script status
```

按真实位置判断移动，按经验/等级判断成长，按库存和 HP/MP 判断恢复，按槽位变化判断换装。请求受理、输入派发、脚本完成与放键是分别可观察的事实，不能单独证明命中、拾取或任务完成。消费、交易、奖励、加点等结果不明时先观察，不重放不可逆操作；成长决策延续已核实的养成计划。

持续策略写 Lua。宿主入口转发 `script run --code CODE --seconds N`，或读取容器路径中的 UTF-8 文件；工作台内的 `scripts/` 直接位于 `/work/scripts`，例如 `script run /work/scripts/control.lua --seconds 20`。文件与源码二选一，持续模式须明确 `--continuous`。内置 Lua 随镜像固定，用户提交的 Lua 是本次明确输入，可在已有实例中更新。维护公共策略前阅读 [shared/scripts/AGENTS.md](../shared/scripts/AGENTS.md)，写脚本查 [Lua API](LUA_API.md)。

同层移动、单根绳梯和门户都有场景前提。缺能力或静态资料时按实际错误与[缺口索引](CLIENT_LIMITATIONS.md)处理，不用另一端或服务端补造未知事实。

## GUI 与首次登录的边界

需要 GUI 特有操作时，先完成账号和控制权交接，再按 [GUI 准备](CLI.md#原版-gui)从对应工作台启动：

```bash
./beidou-pilot --workbench /external/gui-workbench --backend beidou --json open
./beidou-pilot --workbench /external/gui-workbench --json snapshot
```

GUI 在一个工作台中只使用 `default`，账号配置只支持 `world=0`，并按角色 ID 和频道正常登录。两端共享 CLI，但各自保留能力范围。GUI 的 `--character/--character-index/--channel` 和固定账号/名称文件已退役。

通过当前 `snapshot`、`inspect stage` 和 `screenshot` 定位界面，优先使用新鲜对话正文与引用。根桌面 `click X Y` 必须依据当次截图。需要滚轮原语时，在所属 GUI 容器内执行，例如：

```bash
docker exec --user 1000:1000 CONTAINER python3 -m beidou_pilot.engines.desktop scroll down --ticks 1
```

原语直接操作该容器的显示环境。首次声明、性别选择或空角色列表仍不等于自动建角；需要正常 GUI 首次流程时先确认账号和选择意图。无头首次登录与建角由 [#72](https://github.com/Diluka/beidou-pilot/issues/72) 跟踪，未知选择不反复重试。

当前统一 `open` 要求真实已有角色 CID，尚无无角色账号的启动模式。已有且归属正确的 GUI 会话可以接续正常首次流程；全新账号没有可接续会话时，须明确这个引导缺口，不用占位 CID 或其他角色身份绕过。

## 停止、下线与交接

活动 Lua 从原宿主命令发送 Ctrl+C/SIGTERM，薄入口会向该次容器内 CLI 转发取消，并等待原生收尾。不要只杀 Docker exec 进程后假定已放键，也不要用第二个动作命令抢占。使用 harness 时由其 `pause/stop` 确认取消与放键，再交接；详情见 [控制协议](CONTROL.md#控制权期限与取消)和 [harness 协作](HARNESS.md#开发-ai-的协作通道)。

```bash
./beidou-pilot --workbench /external/workbench --instance worker-a --json script status
./beidou-pilot --workbench /external/workbench --instance worker-a --json bridge status
./beidou-pilot --workbench /external/workbench --instance worker-a --json close
./beidou-pilot --workbench /external/workbench --instance worker-a --json status
```

取消后核对同一原生身份下的终态和 `held_keys=[]`；有惯性或动画时继续观察。空闲遗留控制可用 `stop`，不抢占活动控制者。短脚本结束保留客户端；宿主 `close` 才经 Docker 正常关闭、核实退出并回收。容器内 `close` 会提示使用宿主生命周期入口。危险区域结束有界执行后，先进入已验证安全位置或关闭所属实例，再长时间分析。

交接保留账号角色的计划、实际进度、下一步、所用源码/镜像/桥版本与必要证据引用。公开记录只给无私密结论。离线检查、构建、入图、移动、战斗和恢复分别报告，另一端或仅构建成功不能替代本端真实结果。
