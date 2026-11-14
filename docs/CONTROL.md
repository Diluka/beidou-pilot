# Lua 与原生控制

## 执行入口

用户脚本通过 `script run FILE --seconds N` 或 `script start FILE --seconds N` 提交；需要持续运行时显式 `--continuous`。两种等待方式复用同一装载、身份核对、错误、取消与放键链，可在现有实例中执行，无需重启客户端。客户端只有 tick 引擎：入口按会话频率档位到期调用顶层 `main(context)`，通过 `context.state` 保存跨调用状态，通过只读领域观察，并用 `context.game.player` 提交方向与动作意图。Python 只处理参数、文件读取、显式取消与结果投影，不做逐帧控制。

文件必须包含顶层 `main(context)` 函数，`@mode` 可省略并视为 tick；`@tick.gear/budget_ms/overrun/abort_commit` 可单独或与显式 `-- @mode tick` 一起使用。`script describe FILE` 输出有效配置和动态参数用法。CLI 注入 `context.options`、初始 `context.scene` 身份锚点与调用方已有的 `route` 等上下文；原生 tick 引擎随后维护当前只读 `scene`，换图与场景代次变化不需要 Python 回填。没有顶层 `main(context)` 的文件会在发布前被拒绝。

```bash
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --seconds 20
private/workbenches/workbench /external/workbench script start /work/scripts/control.lua --continuous
private/workbenches/workbench /external/workbench script status
private/workbenches/workbench /external/workbench script cancel --session SCRIPT_ID
```

文件路径按容器内部解析；完整工作台读写挂到 `/work`，用户脚本直接读取 `/work/scripts`，内置 Lua 随镜像版本固定。

## tick 运行与动作槽

每次会话新建独立 Lua 状态，`context.state` 跨调用保留但不解释、不序列化、不落盘。所有 tick 会话共享客户端唯一 `context.game.player` 状态机，按接纳顺序调用、后写覆盖；不提供优先级治理，也不维护历史后继请求队列。入口返回后统一提交动作草稿，同一宿主帧仅末值投放；取消、总期限、原生输入保持/消费、释放每宿主更新继续推进，不等待下次 Lua 调用。

方向与动作意图分别保持。动作槽存放当前持续输入意图，原生已开始的动作单独观察；原生忙时仍可替换或撤下意图，已撤下的历史输入不会在后续动作结束后补发。`player.skill(nil)` 撤下整个动作槽（跳跃、普攻、技能、用药或拾取），方向保持；`player.stop()` 清方向与动作。连续触发由各端原生消费者推进，不按 Lua 调用频率重放；仅用药路径有 100ms 最小派发保护。

会话完成、取消、期限、角色变化、离开游戏或错误只结束对应会话；清除该会话仍拥有的方向与动作输入，原生确认最新释放后发布会话终态，不清后来者的有效输入。换图暂停回调并清除旧输入，稳定后的新入口须根据当前只读静态场景重新决定。状态字段、支持边界和完整预算语义见 [tick API](LUA_TICK_API.md#tick-环境)。

## 脚本 API 入口

编写脚本查 [Lua API 导航](LUA_API.md) 和 [tick API](LUA_TICK_API.md)。该页维护上下文、只读领域、运动观察、动作槽、返回值、错误和标准库能力；本篇只说明执行与控制协议。公共接口变更时，运行时实现和 tick API 参考在同一改动中更新；策略不通过重复实现基础操作来补出未声明的接口。

## 控制权、期限与取消

`script run` 同步等待结果，`script start` 在原生受理后返回；两者的脚本会话均由客户端 Runtime 持有，CLI 等待不拥有脚本生命周期。同一客户端可追加多个 tick 会话，它们共享唯一角色状态机；任一活动 Lua 会话存在时普通 GUI 输入返回 `input_busy`。动作锁和桥命令锁只保护源码发布及原生受理，不包住整个 `script run` 的终态等待。

`script status` 保留 `script` 为最新接纳会话，并新增 `scripts` 数组列出全部会话；`script status --session SCRIPT_ID` 按 ID 选择会话，不改变最新会话。每项保留基本状态，并含 `mode="tick"` 和会话级 `control_released`；tick 另有调度与共享 `player` 状态。`stop` 与 `bridge stop` 停止全部会话并释放所属输入；只取消一个会话应使用 `script cancel --session`。

`script run` 的同步等待或 `script start` 的受理等待收到 Ctrl+C、SIGINT 或 SIGTERM 时，只结束 CLI 等待，已受理的原生脚本继续运行。等待超时、陈旧观察等 `ClientError` 只结束 CLI 等待，已发布的脚本继续运行。等待中断或失败后，先用 `script status` 观察当前会话及 `script.id`，核对受理和执行事实；结果未确认时先观察再决定后续。

调用方需要取消脚本时，明确执行 `script cancel --session SCRIPT_ID`，在当前原生身份内核对脚本 ID，并等待终态与实际放键。CLI 等待超时与 Lua 执行期限分别判断：原生期限到达、角色身份变化、离开游戏及脚本错误也会结束会话。只读状态、领域查询和事件监听可并行；普通 GUI 操作在活动 Lua 期间返回 `input_busy`，不自动接管。

LLM 是可选旁路控制端，其暂停或退出时 shell、Lua 与客户端保持运行。没有 LLM 时客户端与已受理脚本继续运行；重新接入先观察当前脚本、控制归属和 `script.id`，再按现状续接。模型进程锁只保护模型会话，角色与脚本控制权由原生 Runtime 维护，CLI 提交明确操作并核验身份。需要停止脚本时显式 `script cancel --session` 并确认放键；需要关闭客户端时另行 `close`。协作入口见 [HARNESS](HARNESS.md#开发-ai-的协作通道)。

宿主工作台 `open/close` 使用独立生命周期锁，宿主 `close` 可通过 Docker 结束活动 Lua 及整个所属实例；同实例正在启停时返回 `lifecycle_busy`。容器内 `close` 会提示使用宿主生命周期入口。Lua 期限控制整个脚本会话，容器没有进程自退期限；脚本结束、超时或取消时容器继续运行，真实断线和错误会退出并保留原因。

动作结果按层次解释：意图受理、输入派发、输入释放、原生动作收束、游戏效果分别确认。`input_action` 与当前已开始的 `action` 独立，`character.action_idle` 读取本端原生动作锁；GUI 的单次动作索引不代表已经命中，也不能把任意单次动作标成攻击。跳跃输入释放不等于落地，输入清空也不强制打断动画。用药/拾取的输入结束不保证消费、拾取或 buff 成功，未知效果保留 unknown。释放后攻击动画、空中运动和受击惯性仍可能继续；采样失效或身份变化时控制只作用于所属实例，释放未确认时返回 `bridge_release_unconfirmed`。

## 观察与传输

CLI 通过原生观察 API 消费 `stage/scene/inventory/character/quests/hotkeys/dialog/ui/shop/notifications`。前五域两端共用，其余为原版 UI 观察扩展。原版在游戏线程读取 V17 对象，DLL 内部仍依赖版本布局；无头端读取自己的游戏对象，外部 Python 不读取游戏进程内存。

tick Lua 使用独立只读领域属性：有到期消费者的宿主帧刷新一次共享核心域，其他域按需读取，同一宿主帧内复用；领域不提供阻塞动作或任务控制。领域结果携带本端来源、支持状态和未知说明，`character.world.scene` 之外不新增公开的 `terrain` 查询（静态地形位于 `context.scene`）。

只读 `observation-request.txt/observation.json` 与动作/Lua 的 `command.txt/state.json` 使用独立通道。响应核对请求 ID、原生 `instance_id/run_id`、序号和采样年龄；实例名只选择工具会话，进程身份以 `instance_id/run_id` 为准。请求派发不覆盖活动 Lua。

Lua 发布仍使用原有单行 `script` 操作和 UTF-8 源码文件。精确取消的单行格式为：

```text
1 INSTANCE_ID SCENE_GENERATION REQUEST_ID cancel_script 0 SCRIPT_ID
```

`cancel_script` 只停止对应 `script.id` 并确认其输入释放，不全局放键；旧桥不提供 `scripts` 能力时直接返回 `bridge_tick_unsupported`，不回退到其他引擎。

`state.json` 保留 `script`（最新接纳会话）及稳定的旧字段，新增 `scripts` 数组，每项沿用 `id/status/reason/error/resumes/budget_yields/last_resume_us/max_resume_us` 并携带 `mode="tick"` 和会话级 `control_released`。tick 额外有 `tick={index,time,delta,scene_generation,overrun,overruns,budget_ms,overrun_policy,abort_commit}` 与客户端共享 `player` 操作快照。`player` 只区分当前输入槽和已开始的原生动作，不暴露 `input_settled/control_released`；Lua 直接返回 done，由 Runtime 确认停止所属持续输入（持键路径包含真实释放），槽空不表示停止已确认。原始 `command` 只反映最近命令，不代表所有会话；CLI 等待按 `scriptId` 定位自己的会话，不能在其他命令更新 `command.id` 后失联。

完成或取消的释放判断使用该会话的 `control_released`，不要求全局 `held_keys=[]`；全局仍可能包含其他会话的合法持键。`stop`/`bridge stop` 才要求全部会话停止及全局输入释放。

原生异步事件使用独立 `events.json`：共享 `EventTransport` 按本进程单调事件序号保留最近128条，首次发布空流，事件变化后原子替换文件；不混入每帧状态或 Lua 文本日志。事件保留实例与运行身份、捕获时间、场景代次、可知角色、来源、类型与数据；期限已知时填写 `expires_at_ms`。生产者是同类 GUI 原生通知气泡，业务种类和未知种类共用采集、按钮与生命周期；无头端的事件接口按原生能力返回。

`events read/watch` 只验证新鲜桥与事件身份，读者各自保存 `instance_id/run_id/seq` 游标，不占动作锁或观察请求通道，不消费其他读者的事件。保留区缺口、无效游标和身份变化明确报错。通知只提供曾发生的事实；操作前须重新读取当前气泡引用和真实按钮；主按钮与气泡关闭属于界面事实，入队或成交另行核对。

持续事件读者遇到 `stale_bridge_state` 时停留在原游标，等待相同实例恢复新鲜采样；不可用与恢复各输出一次流健康诊断，不向消费者投递失效样本。等待可以超时或取消，游戏侧保持原状态；身份及协议错误仍向外报告。单次读取按当前采样结果返回。

原版 checksum 保留真实校验结果；无头端未执行的校验为 `null`，值是否可用由 `native_values_valid` 表达。无头对话/可见性及未实现领域保持明确未知或不支持。

## 原版桌面边界

`engines/desktop.py` 只承担登录、鼠标、滚轮、截图和短线性 GUI 操作。GUI 的 NPC 对话、普通商店、背包换装、复活、快捷键绑定和控件激活由原生桥与桌面消费者提供，原生鼠标和键盘脉冲归同一控制权，取消放开与所属拖拽收尾确认后才交接。无头端没有桌面输入入口，控件激活与 NPC 交互按能力声明返回不支持；需要这些操作时使用 GUI 会话。

匹配的 `ijl15.dll` 只安装到独立 GUI 运行副本，并登记构建清单；EXE、原代理 DLL 和桥 DLL 的实际指纹由 [binaries.py](../cli/beidou_pilot/binaries.py) 核验。完整客户端素材和 GUI 环境均由外部准备。
