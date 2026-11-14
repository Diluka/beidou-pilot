# Lua 与原生控制

## 执行入口

用户策略使用 `script run FILE --seconds N` 或 `script run --code CODE --seconds N`，文件和源码二选一，需要持续运行时明确 `--continuous`。两种输入复用同一装载、身份核对、错误、取消与放键链，可在现有实例中执行，无需重启客户端。脚本按前导 `@mode` 选择独立的 coroutine 或 tick 引擎；coroutine 基础动作调用旧 `game` API，tick 即时操作使用 `context.game.player`。复合能力装载 `shared/scripts/` 的 Lua 文件，调用方传入业务参数，Python只处理参数、装载、显式取消与结果。

带顶层 `main(context)` 的文件声明策略入口；`script run/start FILE` 从 Lua 注释读取选项合同、校验动态 CLI 参数，并由 CLI 注入本次地图与可用的静态地形。coroutine 按旧行为核对场景并调用一次入口；tick 返回 `{main=main,context=__beidou_context}` 供新引擎核对初始场景后按会话档位调用，不执行旧 `game.state()`；后续地图及场景代次变化由原生更新只读 `context.scene`，保留 `context.state` 和额外上下文，不通过 Python 逐图回填。`script describe FILE` 输出 mode、有效 tick 配置和动态参数用法。没有策略入口的旧文件继续作为原始 chunk 执行；tick 策略文件须有 `main(context)`。`--code` 不启用 `@option` 或上下文注入，但仍识别前导 `@mode/@tick.*`，由原生按源码声明分派。start 受理、状态查询与显式取消仍是同一组 CLI 操作。

```bash
private/workbenches/workbench /external/workbench script run --code 'game.log("你好，Lua")' --seconds 20
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --seconds 20
private/workbenches/workbench /external/workbench script status
```

文件路径按容器内部解析；完整工作台读写挂到 `/work`，用户脚本直接读取 `/work/scripts`，内置 Lua 随镜像版本固定。

原始按键与直接技能也是 Lua 的原版扩展。持续动作、分支和循环直接写 Lua，控制逻辑集中在脚本层。

## 两套独立运行环境与策略分层

省略 mode 或 `-- @mode coroutine` 进入现有 Runtime，其 API 和调度冻结保留；`-- @mode tick` 进入独立 TickRuntime。两者不共享上层状态、动作槽、控制权和输入生命周期，只共享适配器所需的原生 I/O；任一引擎的取消、错误和期限不结束另一引擎的会话。两端按共同的公开契约提供各自原生实现，不建立旧 API 的兼容包装。

客户端 tick 引擎只有一份角色输入状态机，全部 tick 会话共享持续方向与单个持续动作意图，按接纳顺序调用、后写覆盖。宿主推进原生保持/消费、期限、取消和放键，各会话按 `@tick.gear` 到期读取当帧新鲜事实并提交意图差异；相同输入不重按，动作忙时仍可替换或撤下意图。输入B不覆盖原生正在执行的A，没有历史后继请求队列；B被撤下后不会补发。`player.skill(nil)`撤下整个动作槽（跳跃、普攻、技能、用药或拾取），方向保持；`stop()`清方向与动作，角色已发生动画自然收束。连续触发由各端原生消费者推进，不按Lua频率重放；仅用药增加专属100ms派发保护。状态、支持边界和完整预算语义见 [tick API](LUA_TICK_API.md#tick-环境)。

以下基础动作、任务控制和内置策略描述均为 coroutine 环境。以 headless 当前面向脚本的 `State`、`Action`、`ActionResult` 为共同标准，绑定与调度位于 `shared/lua-runtime/`；原版 DLL 提供同一模型。内置策略不在本次迁移范围，选择性验证用 tick 文件不替换内置脚本。

相同函数签名与事实边界用于两端，各端读取对象、调用原生输入或技能的实现留在适配器。可选按键/技能能力由 `game.capabilities()` 声明，headless 未支持时明确拒绝；已知程度不同的物理收束等信息保留未知。公共 `use_item` 限普通200类恢复药品。

无头普通换装使用共享 `game.equip/unequip`，按明确槽位派发一次正常装备请求，在原生更新阶段核对源、目的槽位的装备对象变化后确认效果。Python 仅负责参数、装载/取消和结果投影。等待中的取消、接管、超时或换图保留未确认事实，按一次性派发处理；后续操作先重新观察库存。GUI Lua 支持已校准普通背包中、原生谓词给出唯一兼容槽位的普通穿戴；卸下及歧义/特殊目标走原 CLI 的相应自动选择路径。窗口、点数和换装复用同一 Runtime 所有权与取消；语义结果标记所属 session_id，新请求以本次会话的结果为准。

GUI普通200类用药按物品ID与实际消费槽直接调用原生入口，与键位绑定无关。请求仍只占一个活动动作，在Lua恢复栈外的原生阶段消费；未派发时可取消，调用已进入表示本地派发完成，药品消耗与恢复另行观察。显式 `keys/press` 和其他语义动作的现有路径分别保留。

各脚本用途、调用入口和弃用状态集中维护在 [Lua 脚本目录说明](../shared/scripts/README.md)。连续狩猎使用 `combat/hunt.lua`；该策略不包含拾取或结束后撤退。

基础操作是 `game` API 的积木，直接调用即可。策略当前是初步脚手架，已有参数、时序和流程需按实际情况迭代，局部维护约定见 [shared/scripts/AGENTS.md](../shared/scripts/AGENTS.md)。执行期限、取消与放键由公共运行时提供；`_common.lua` 是公共辅助库，目录按实际能力创建。

`hunt` 从当前配置的只读原版 IMG 装载地形，实时选怪、路径和动作全部在 Lua 中执行。移动意图与攻击意图分别判断，`game.attack(seconds, direction, skill_id)` 可在同一输入窗口保持方向与普攻或指定技能；原生动画和物理仍决定实际动作。优先处理当前层可达目标，接近绳梯时先停稳并重新确认对齐，再跳起抓绳。绳梯、相连平台、有限台阶和落层按当前现场确认；接近仍有进展时，时限按跨层阶段的实际进展顺延。路段无进展时先释放输入，记录种类、平台、阶段、实际位置、目标坐标与计时；能确认当前落层时跳过本次会话已失败的具体有向边，再寻找可达替代路线或目标。无法确认落层或没有可达目标时明确停止，并保留已有尝试记录。狩猎固定启动时的实例、角色、地图和场景代次，门户与换图由独立操作处理。

限时狩猎与 `--continuous` 共用原生 Runtime 的脚本执行链；CLI 等待被中断后，已启动的狩猎继续运行。无头桥 `held_actions` 展示语义输入，GUI `held_keys` 展示实际持键；命中与服务器确认另行核对。经验变化及已知的服务端目标 HP 百分比下降用于判断实际进展，尝试计数作为参考。`hunt` 的移动和攻击计时可能重叠，总耗时按实际时间窗口统计。

## 脚本 API 入口

编写脚本先按 [Lua API 导航](LUA_API.md) 选择 [coroutine API](LUA_COROUTINE_API.md) 或 [tick API](LUA_TICK_API.md)。两份参考分别维护各自的状态结构、能力字段、函数签名、默认参数、返回值、错误和标准库限制，本篇只说明执行与控制协议。

公共接口变更时，运行时实现和 API 参考在同一改动中更新；策略不通过重复实现基础操作来补出未声明的接口。共享策略仍按其局部维护约定迭代，已有参数属于脚手架阶段。

## 控制权、期限与取消

coroutine 引擎仍只允许一个活动会话，其内部任务共享一份动作控制；tick 引擎允许多个会话，也可与 coroutine 同时存在。`script run` 同步等待结果，`script start` 在原生受理后返回；两者的脚本会话均由客户端 Runtime 持有，CLI 等待不拥有脚本生命周期。一个 coroutine 脚本会话内可通过 `game.spawn/acquire/cancel/tasks` 协作运行多个 Lua 任务；它们共享 Lua 状态，由公共 Runtime 串行派发原生动作。任务等待动作或控制权时，其他任务继续观察和判断。主任务返回后子任务继续，全部任务结束且放键确认后会话结束。公共接口与示例见 [Lua API 的任务与控制权](LUA_COROUTINE_API.md#任务与控制权)。

动作控制按任务归属。高优先级任务可请求接管，旧任务立即失去派发资格，原生确认释放后新任务取得控制；相同优先级保持当前控制者。被接管动作返回标准结果并标记 `reason=control_preempted`，游戏效果保持未知。旧任务重新取得控制后读取新状态并规划，运行时不保留待重放动作。指定任务取消、正常返回或 `game.stop()` 只释放该任务仍拥有的输入；停止原任务只释放其自身输入，后续控制者的输入保持。`keys/press/skill` 同样受任务归属约束。

GUI按键由适配器保留单份最新期望集合，Lua调用提交后，实际按键在运行时与管理请求处理返回后的原生更新阶段派发。原生NPC窗口处理可以同步进入嵌套更新，此时Lua恢复栈已经归还，嵌套更新继续处理释放、观察和后续脚本。新请求或取消会使旧按下批次失效；已经持有的按键仍需完整发送keyup，并在全部投递返回后等待真实角色消费确认。该阶段划分保持请求按单份期望集合处理，直接技能继续同步返回。

`script status` 保留 `script` 为最新接纳会话，新增 `scripts` 数组列出 coroutine 与全部 tick 会话；`script status --session SCRIPT_ID` 按 ID 选择会话，不改变最新会话。coroutine 的 `tasks/control` 继续展示任务名称、revision、状态、优先级和交接；tick 额外展示 `tick` 调度与共享 `player` 操作状态。外部 `task add/replace/stop` 只管理 coroutine 的指定会话，最新 `script` 变成 tick 也不影响按 ID 定位原 coroutine。

动作锁和桥命令锁只保护源码发布及原生受理，不包住整个 `script run` 的终态等待。第二个 tick 或另一引擎的会话可在等待期间受理；coroutine 本身仍受原生单会话 busy 检查约束。普通 GUI 输入继续与发布互斥，并在任一活动 Lua 会话存在时拒绝接管。

任务管理使用独立短锁与 `task-request.txt`，不覆盖 `command.id`；会话生命周期仍由所属 Runtime 维护，跨会话命令由会话 ID 区分。两端使用同一份 `TaskTransport` 解析请求并调用共享 Runtime；它们不从管理入口直接派发原生输入。请求绑定原生 `instance_id/run_id` 与 `script.id`，替换、停止还核对任务 `revision`；新增、替换核对场景代次。源码文件仍原子放在 `scripts/`，结果按请求 ID 保存在 `task-results/`，不覆盖动作或只读观察响应。

替换先编译独立chunk，编译通过后才切换任务。编译后旧版本停止派发，运行时按旧任务的输入归属等待释放确认，再安装同名新版本。管理等待超时或中断时整会话继续运行；原会话的取消、期限和角色身份规则优先生效，会话结束后不再安装未完成的替换。管理结果写入失败时宿主以 `task_result_write_failed` 报错，保留反馈并进入既有整会话停止与放键流程。

`script run` 的同步等待或 `script start` 的受理等待收到 Ctrl+C、SIGINT 或 SIGTERM 时，只结束 CLI 等待，已受理的原生脚本继续运行。等待超时、陈旧观察等 `ClientError` 只结束 CLI 等待，已发布的原生任务继续运行。等待中断或失败后，先用 `script status` 观察当前任务及 `script.id`，核对受理和执行事实；结果未确认时先观察再决定后续。

调用方需要取消脚本时，明确执行 `script cancel --session SCRIPT_ID`，在当前原生身份内核对脚本 ID，并等待终态与实际放键。库调用方提供的 `cancel_file` 仍是显式取消输入，新桥同样只取消该请求所属会话；没有 `scripts` 的旧桥保留单会话 `stop` 兼容。CLI 等待超时与 Lua 执行期限分别判断：原生期限到达、角色身份变化、离开游戏及任一脚本错误仍停止整个会话。只读状态、领域查询和事件监听可并行；普通 GUI 操作在活动 Lua 期间返回 `input_busy`，不自动接管。

LLM 是可选旁路控制端，其暂停或退出时 shell、Lua 与客户端保持运行。没有 LLM 时客户端与已受理脚本继续运行；重新接入先观察当前脚本、任务和控制归属，再按现状续接。模型进程锁只保护模型会话，脚本与任务控制权由原生 Runtime 维护，CLI 提交明确操作并核验身份。需要停止脚本时显式 `script cancel --session` 并确认放键；需要关闭客户端时另行 `close`。协作入口见 [HARNESS](HARNESS.md#开发-ai-的协作通道)。

`bridge stop` 的底层 `stop` 操作仍停止两引擎的全部会话并释放所属输入；只取消一个会话应使用 `script cancel --session`。普通 `stop` 仍经旧动作入口处理遗留控制，不代替精确脚本取消。宿主工作台 `open/close` 使用独立生命周期锁，宿主 `close` 可通过 Docker 结束活动 Lua 及整个所属实例；同实例正在启停时返回 `lifecycle_busy`。容器内 `close` 会提示使用宿主生命周期入口。

Lua 期限控制整个脚本会话，容器没有进程自退期限。脚本结束、超时或取消时容器继续运行；`close`/Docker stop 关闭实例。真实断线和错误会退出并保留原因，调用方决定是否重开，旧动作保留为历史。

动作结果按层次解释：意图受理、输入派发、输入释放、原生动作收束、游戏效果分别确认。tick 的 `input_action` 与当前已开始的 `action` 独立，两端 `character.action_idle` 读取本端原生动作锁；GUI 的单次动作索引不代表已经命中，也不能把任意单次动作标成攻击。跳跃输入释放不等于落地，输入清空也不强制打断动画。用药/拾取的输入结束不保证消费、拾取或 buff 成功，未知效果保留 unknown。普通换装的 `effect=confirmed` 来自正常库存更新中的源、目的对象核对；`completed`、原生调用非零或 `held_keys=[]` 作为过程事实，命中或拾取成功需另行核对。释放后攻击动画、空中运动和受击惯性仍可能继续。采样失效或身份变化时控制只作用于所属实例，释放未确认时返回 `bridge_release_unconfirmed`。

## 观察与传输

CLI 通过原生观察 API 消费 `stage/scene/inventory/character/quests/hotkeys/dialog/ui/shop/notifications`。前五域两端共用，其余为原版 UI 观察扩展。原版在游戏线程读取 V17 对象，DLL 内部仍依赖版本布局；无头端读取自己的游戏对象，外部 Python 不读取游戏进程内存。

coroutine Lua 通过 `game.observe(domain)` 按需调用相同原生采集函数，共享值类型和 Lua 投影由 `shared/lua-runtime/` 维护，进程内直接传递。查询只占用当前原生采集路径，响应附带当前实例、角色、地图、场景代次及采样时间。轻量 `game.state()` 按需采集基础字段；调用者在等待或动作后重新读取。无头任务仍是登录快照，GUI 桌面几何增强不属于原生 Lua 数据，完整字段与未知语义见 [Lua API](LUA_COROUTINE_API.md#按需领域观察)。tick 使用独立只读领域属性，有到期消费者的宿主帧刷新一次共享核心域，其他域按需读取，同一宿主帧内复用；不向旧 `game.observe` API 转发。

只读 `observation-request.txt/observation.json` 与动作/Lua的 `command.txt/state.json` 使用独立通道。响应核对请求ID、原生 `instance_id/run_id`、序号和采样年龄；实例名只选择工具会话，进程身份以 `instance_id/run_id` 为准。请求派发不覆盖活动 Lua。

Lua 发布仍使用原有单行 `script` 操作和 UTF-8 源码文件，原生读取源码头决定引擎，不新增逐帧 CLI 操作。精确取消的单行格式为：

```text
1 INSTANCE_ID SCENE_GENERATION REQUEST_ID cancel_script 0 SCRIPT_ID
```

`stop 0` 保留全停语义；新桥 `cancel_script` 只停止对应 `script.id` 并确认其输入释放，不全局放键。没有 `scripts` 字段的旧后端仍按旧单会话合同先核对 ID，再回退 `stop`；旧桥装载 tick 则直接返回 `bridge_tick_unsupported`，不回退到旧引擎。

`state.json` 保留 `script`（最新接纳会话）及稳定的旧字段，新增 `scripts` 数组，每项沿用 `id/status/reason/error/resumes/budget_yields/last_resume_us/max_resume_us/tasks/control` 并携带 `mode="tick"/"coroutine"` 和会话级 `control_released`。tick 额外有 `tick={index,time,delta,scene_generation,overrun,overruns,budget_ms,overrun_policy,abort_commit}` 与客户端共享 `player` 操作快照。`player` 只区分当前输入槽和已开始的原生动作，不暴露 `input_settled/control_released`；Lua直接返回done，由Runtime确认停止所属持续输入（持键路径包含真实释放），槽空不表示停止已确认。原始 `command` 只反映最近命令，不代表所有会话；CLI 等待按 `scriptId` 定位自己的会话，不能在其他命令更新 `command.id` 后失联。

完成或取消的释放判断使用该会话的 `control_released`，不要求全局 `held_keys=[]`；全局仍可能包含其他 tick 或 coroutine 的合法持键。`bridge stop` 才要求全部会话停止及全局输入释放。旧后端没有多会话能力时仍保留原 command/held_keys 判定，未确认释放时报 `bridge_release_unconfirmed`。

原生异步事件使用独立 `events.json`：共享 `EventTransport` 按本进程单调事件序号保留最近128条，首次发布空流，事件变化后原子替换文件；不混入每帧状态或 Lua 文本日志。事件保留实例与运行身份、捕获时间、场景代次、可知角色、来源、类型与数据；期限已知时填写 `expires_at_ms`。生产者是同类 GUI 原生通知气泡，业务种类和未知种类共用采集、按钮与生命周期；无头端的事件接口按原生能力返回。

`events read/watch` 只验证新鲜桥与事件身份，读者各自保存 `instance_id/run_id/seq` 游标，不占动作锁或观察请求通道，不消费其他读者的事件。保留区缺口、无效游标和身份变化明确报错。通知只提供曾发生的事实；操作前须重新读取当前气泡引用和真实按钮；主按钮与气泡关闭属于界面事实，入队或成交另行核对。CLI 与共享 Runtime 保持独立；外部消费者负责把事件交给模型，模型中断和游戏脚本取消分别处理。

持续事件读者遇到 `stale_bridge_state` 时停留在原游标，等待相同实例恢复新鲜采样；不可用与恢复各输出一次流健康诊断，不向消费者投递失效样本。等待可以超时或取消，游戏侧保持原状态；身份及协议错误仍向外报告。单次读取按当前采样结果返回。

原版 checksum 保留真实校验结果；无头端未执行的校验为 `null`，值是否可用由 `native_values_valid` 表达。无头对话/可见性及未实现领域保持明确未知或不支持。

## 原版桌面边界

`engines/desktop.py`只承担登录、鼠标、滚轮、截图和短线性 GUI 操作。GUI 的普通唯一槽位穿戴、AP/SP 和三种必要窗口/焦点已由 Lua 原生适配消费；原生鼠标和键盘脉冲归同一控制权，取消放开与所属拖拽收尾确认后才交接。歧义/特殊装备、非普通200类可用物品、传送卷和其他尚未替换的桌面消费者继续保留，承担一次性 GUI 操作。无头普通换装继续走自身的 Lua 与原生库存确认链。

匹配的 `ijl15.dll` 只安装到独立 GUI 运行副本，并登记构建清单；EXE、原代理 DLL 和桥 DLL 的实际指纹由 [binaries.py](../cli/beidou_pilot/binaries.py) 核验。完整客户端素材和 GUI 环境均由外部准备。
