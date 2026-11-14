# Tick Lua API（逐次决策引擎）

本页只描述显式声明 `-- @mode tick` 的 **tick 引擎**。入口按档位到期执行，以 `context.state` 保存跨调用状态，通过只读领域观察和非阻塞 `player` 状态机提交意图。本引擎没有 coroutine 的阻塞动作、`game.state()`、`game.observe()` 或任务控制函数；另一套引擎见 [Coroutine Lua API](LUA_COROUTINE_API.md)，选择入口见 [Lua API 导航](LUA_API.md)。

两端使用本页同一公开契约，能力缺口和未知事实按后端如实保留。脚本组织与传输见 [控制协议](CONTROL.md)，维护约定见 [共享脚本约定](../shared/scripts/AGENTS.md)。修改 tick 公共 API 时同步维护本页。

## 启动与基本约定

将下节带有前导 `-- @mode tick` 和顶层 `main(context)` 的 UTF-8 文件保存到工作台的 `scripts/control-tick.lua`，从宿主运行：

```bash
private/workbenches/workbench /external/workbench script describe /work/scripts/control-tick.lua
private/workbenches/workbench /external/workbench script run /work/scripts/control-tick.lua --ticks 10 --seconds 20
```

- 文件路径按容器内部解析，工作台读写挂到 `/work`；内置 Lua 随镜像版本固定。源码上限为1 MiB，只接受UTF-8文本，不接受预编译字节码。
- `script run` 同步等结果，`script start` 等原生受理。自定义执行默认30秒，`--seconds` 范围为 `0.001..4294967.295` 秒；显式 `--continuous` 表示无总期限。总期限与单次调用的 `budget_ms` 分开。
- CLI 中断、等待超时或观察失败只结束等待，已发布任务继续运行。先用 `script status` 核对当前会话；取消用 `script cancel --session SCRIPT_ID` 并核对终态与放键，客户端关闭另用 `close`。
- 文件与 `--code` 二选一。直接源码按调用方 shell 规则传为一个参数，保留引号、中文和换行，结果的 `script_file=null`；其入口形式与不注入参数的限制见下节。
- 每个会话新建独立Lua状态，不跨会话恢复内存；所有tick会话共享客户端级player。未知字段为 `nil`，与已知 `false`、`0`、空表不同。时间及间隔使用秒，原生更新、释放确认和调度按实际发生时间判断。

## tick 环境

### 入口、配置与装载

```lua
-- @mode tick
-- @tick.gear 3            -- 1=10Hz，2=20Hz，3=30Hz（默认），4=本端原生更新
-- @tick.budget_ms 100
-- @tick.overrun abort     -- abort | skip
-- @tick.abort_commit true -- abort 时先提交本 tick 草稿
-- @option[type=int,default=10,min=1] ticks 观察次数
local function main(context)
    context.state.calls = (context.state.calls or 0) + 1
    local world = context.game.world
    if not world.ready then return end
    if context.state.calls >= context.options.ticks then return "done" end
end
```

运行元数据只读取首段可执行代码之前的前导单行注释，允许空行、普通注释与尾部 `--` 说明；Lua 长注释内部不解释元数据。`@mode` 只接受小写 `tick/coroutine`，重复、未知 mode、未知或重复的 `@tick.*`、格式错误均在发布前拒绝；`@tick.*` 必须配合显式的 `@mode tick`。预算为正有限十进制毫秒数，支持小数，不接受符号、科学计数、NaN 或无穷；`overrun` 为 `abort/skip`，`abort_commit` 为小写 `true/false`。未配置时为 **第3档（30Hz）/ 100ms / abort / true**，单次预算与调用周期独立。

策略文件仍采用唯一顶层 `main(context)` 和既有 `@option` 参数规则。CLI 注入 `options` 和初始 `scene` 身份锚点；原生 tick 引擎随后维护当前只读 `scene`，调用方已有的 `route` 等额外上下文按原规则保留。编译结果向新引擎返回 `{main=main, context=__beidou_context}`，不调用旧 `game.state()`，也不在装载阶段执行 `main`；初始 `scene` 身份由原生 tick 引擎核对。`--code` 保留原始源码、不注入策略参数，但同样读取前导 mode/config：应定义全局 `function main(context) ... end`，或显式返回含 `main/context` 的入口表。

宿主每次更新都推进原生生命周期；`main` 按每会话工作频率档位到期调用，首次稳定帧立即调用，返回后统一提交差异供后续帧消费。GUI 使用 `ClientApplication::Update` 主循环渲染帧，无头使用 `Stage::update` 逻辑步进，不假设渲染与角色物理更新 1:1。

| 档位 | 工作频率 | 用途 |
| --- | --- | --- |
| 1 | 10Hz | 较慢的观察和简单判断，最多约100ms的调度等待 |
| 2 | 20Hz | 中等响应，最多约50ms的调度等待 |
| 3（默认） | 30Hz | 常规即时决策，最多约33ms的调度等待 |
| 4 | 每个本端宿主更新，不节流 | 需要最高采样频率时使用；当前实测无头约125Hz、GUI约60Hz，不是固定保证 |

表中固定频率是目标，实际调用还受宿主更新、工作负载及脚本执行时间影响，不保证严格最大延迟。四档依据两端实际节奏和成本设计：GUI角色物理更新约33Hz，渲染约60Hz会复用样本；无头为8ms逻辑步。30Hz默认减少重复决策，同时保留普通跳跃动作窗口的多个观察机会。两端逐档数据与测量限制见[工作频率实测依据](TICK_FREQUENCY.md)。档位不改变游戏物理速度、按键脉冲长度或动作槽生命周期。`@tick.gear` 只接受单字符整数 `1/2/3/4`，不接受前导零、符号、小数、指数、任意Hz或裸tick倍率。

每会话使用绝对周期相位；慢帧或长回调错过周期时跳过已过区间，不补跑一串旧判断。取消、总期限、原生消费、方向keyup和后继动作槽每宿主更新继续推进，不等待下次Lua调用。降频期间持续方向不必重复提交。落地等瞬态事实需在到期回调重新观察；清方向发生在首次观察到真实落地的决策，不承诺所有档都在下一宿主帧停止。返回 `nil` 继续；`"done"` 或 `{done=true}` 停止继续调用入口，清除所属持续方向，已提交的一次性动作（包括待执行槽）经原生消费和释放确认后正常结束。显式取消或总期限仍可中断这段收尾。Lua 错误终止该会话为 `cancelled/script_error`。每次会话重启新建上下文，不恢复上次 Lua 内存。

| 上下文 | 语义 |
| --- | --- |
| `context.tick` | 只读；`index` 为实际调用序号而非宿主帧号，`time/delta` 为各次真实调用的单调时间及间隔（秒），`gear` 为本会话有效档位，`scene_generation` 为当前场景代次，`overrun` 表示上次调用超限 |
| `context.state` | 脚本自有可写表，跨 tick 保留，不解释、不序列化、不落盘 |
| `context.options` | 策略参数及有效默认值；直接源码未提供时为空表 |
| `context.scene` | 原生维护的当前只读静态场景；身份和 `terrain` 随地图及场景代次更新，与动态实体领域 `context.game.scene` 分开 |
| `context.route` | 调用方已有的预计算路线；无路线不伪造 |
| `context.game` | 只读领域入口及客户端级 `player` 状态机 |

单次调用用 Lua 指令 hook 周期核对墙钟预算，包括初始化阶段的执行约束。`abort` 默认先提交已写入的确定草稿，停止继续调用入口并清除所属持续方向；已提交的一次性动作经原生消费和释放确认后，以 `cancelled/tick_overrun` 结束。收尾期间总期限或显式取消仍可立即打断；`abort_commit=false` 时丢弃当次草稿。持续方向不会在会话结束后延续，已经派发的一次性动作的实际效果另行观察。`skip` 中断当次入口、保留已写草稿参与本帧提交并保留会话，下一次 `context.tick.overrun=true`，脚本自行分片或降低负载。脚本内存中的 `state` 修改不是事务回滚对象。预算 hook 约束 Lua 指令执行，不能抢占正在阻塞的原生 C 函数；这仍是受信本地脚本环境，不是恶意源码沙箱。

### 性能观测

原生桥顶层 `tick_profile` 及会话状态的 `tick.profile` 是同一份 **runtime 生命周期聚合**，不是 Lua `context.tick` 的字段，也不表示该会话独占成本。`host_tick_calls` 包含全部宿主调用和空闲早退，`active_frames` 为实际处理帧，`reentrant_tick_calls` 为重入早退。`tick/observe/refresh_core/lua` 各含 `samples/total_us/max_us`：分别计完整 Tick、宿主快照复制、核心领域刷新及 `main` 调用，单位微秒。Lua 项含调用过程中绑定与惰性领域读取，不含初始化或回调后的动作提交。子阶段已包含在完整 Tick 中，不能相加。排除 Start 初始化、宿主原有 Capture 及桥状态发布；空闲不会为了计时新增领域采集。降频时 `observe` 仍随活动宿主帧推进，`refresh_core` 只计有到期消费者的稳定帧，`lua` 只计实际入口调用，不能直接拿不同分母的均值相减作为净耗时。

比较测量窗口时用累计计数和 `total_us` 的差分计算均值；`max_us` 是生命周期峰值，不能用差分求区间峰值。这些是墙钟时间，不是独占 CPU 时间，也不等同于总帧耗时或动作延迟。

### 独立只读领域

`context.game`（也作为全局 `game` 提供）不提供 `state()`、`observe(domain)`、阻塞动作、`sleep`、`spawn/tasks/acquire/cancel` 或旧按键接口。`game.log(text)` 接受字符串，单条最多4096字节、单次调用日志合计最多65536字节，写入该会话的原生事件日志；时间使用 `context.tick.time/delta`，不提供旧 `game.time()`。标准库开放基础语言和 `table/string/math/utf8`，不开放 `io/os/package/debug/coroutine`；禁用动态装载、`print/pcall/xpcall/setmetatable/getmetatable/rawset`，不会通过捕获预算异常绕过超限处理。每个领域是独立只读 table，嵌套表也只读；写入报 Lua 错误。有到期会话时，核心 `character/world/scene` 在该宿主帧统一刷新一次，所有到期会话共用当帧新鲜结果；没有到期消费者的帧不为Lua刷新核心领域。其余领域每宿主帧按需采集一次，同帧跨会话复用；不会按地图ID复用上次决策的动态scene。领域直接展开原生观察的 `data` 字段并附带 `status/error`，不额外嵌套一层 `data`。不支持或暂时不可读通过领域状态和错误说明，未知字段缺失或为 `nil`，不借另一后端补齐。

| 属性 | 内容与边界 |
| --- | --- |
| `game.character` | 当前玩家实体：共享可移动物体的 `x/y/velocity`，以及 `id/name/level/job/hp/max_hp/mp/max_mp`；长字段 `strength/dexterity/intelligence/luck/ability_points/skill_points/experience` 及简写 `str/dex/int/luk/ap/sp/exp`；`movement` 是角色能力参考，`on_ground/attacking/native_updates` 是本角色原生事实，未知时为 `nil`；与本端可读取的角色领域事实合并 |
| `game.world` | `instance_id/scene_generation/ready/in_game/map_id`；既有角色快照位置仍提供 `x/y` 和 `position={x,y}`，`facing` 沿用 `Left/Right`；`settled/dead/revive_requestable` 未知时不提供。新实体运动字段不挂在此领域，GUI `settled` 保持未知 |
| `game.scene` | `players/monsters/npcs/projectiles/drops` 的实体列表按本端支持范围提供，各行共享可移动物体的位置与向量契约；集合或字段不可读保留未知，不把不支持的集合写成空列表；完整性按本端实际能力声明 |
| `game.inventory`、`game.quests` | 本端原生背包/装备和任务领域；任务动态性仍遵循本端来源声明 |
| `game.chat` | 按本端可读能力；不支持时明确 `status="unsupported"`，不是空聊天记录 |
| `game.dialog/shop/ui/hotkeys/interaction/notifications` | 按需只读观察；支持范围与原生领域一致，不增加窗口动作 API |

buff 归 `game.character`，不在 `player.status()`。首版两端都没有可靠的完整 buff 效果及剩余时间来源，返回 `buffs=nil`（JSON `null`）、`buffs_status="unsupported"` 和 `buffs_unavailable="native_buff_details_unavailable"`；不把未知列表伪造成 `{}`，不通过服务端查询补齐。

### 当前静态场景与跨图

`context.scene` 由本端原生 tick 引擎维护，文件策略及直接 `--code` 都可读取：

- `instance_id/character_id/map_id/scene_generation` 表示这份静态场景的身份；每次稳定回调中，地图和代次与 `game.world`、`context.tick.scene_generation` 一致。初始调用方的身份锚点仍先核验，随后不以调用方旧地形作为回退。
- `terrain.status="available"` 时提供 `source`、`footholds`、`ropes`。平台段含整数 `id/x1/x2/y1/y2/prev/next`，绳梯含整数 `index/x/y1/y2`，本端已知的整数 `l/uf` 可选保留；坐标沿用地图原始像素方向，绳梯列表可为空。
- 缺图、坏字段、无法读取等返回 `unavailable`，空自身地形且存在 `info.link` 返回 `unsupported`；`error` 及可用的 `message/details/source` 说明原因。不可用时不带 `footholds/ropes`，不把缺失坐标补零，也不跟链接地图或另一后端拼出地形。有本图完整自身几何时可直接使用，不因额外 `info.link` 拒绝。
- 同一会话可以继续跨图，`context.state` 和已有 `options/route` 不重建。换图沿现有规则暂停回调并清除旧输入；转场立即使当前静态场景不可用，首次稳定到期帧再读取本图。稳定但资料不可用时仍调用 `main`，由策略决定等待或退出；资料结果在当前场景有效期内共享，不逐 tick 重读。相同地图ID的新场景代次也重新读取。
- `scene` 槽及嵌套数据只读，不能由策略替换。旧表引用仍是带旧身份的历史只读快照，不能当成当前图；需要缓存路径等进度时放入 `context.state`，发现代次变化后自行重规划。

headless 使用本端已加载的 IMG 地图树；GUI 原生桥按显式配置的同端只读 `game_data` 目录读取单张 IMG，不按工作目录猜资源根，不经 Python 换图回填。`game.scene` 仍只负责动态实体观察，不增加公开的 `game.terrain` 查询，也不改变既有 coroutine 导航。

```lua
local scene = context.scene
if scene.terrain.status ~= "available" then return end
if context.state.scene_generation ~= scene.scene_generation then
    context.state.scene_generation = scene.scene_generation
    context.state.maps_seen = (context.state.maps_seen or 0) + 1
    -- 在此丢弃依赖上一场景的平台图、门户阶段等缓存，再规划本图。
    game.log(("map=%d generation=%d footholds=%d ropes=%d"):format(
        scene.map_id, scene.scene_generation,
        #scene.terrain.footholds, #scene.terrain.ropes))
end
```

### 运动观察与静止参考

移动状态属于实体，不属于世界。共享观察模型的 `MovableObject` 是自己、其他玩家、怪物、NPC、投射物和会移动的掉落物的共同基类，各自拥有 `x/y/velocity`；角色自己的位置和运动向量从 `game.character` 读取，其余从对应 `game.scene` 列表中的实体读取。该统一发生在观察模型，不重写两端不同的原生继承树。`position_source` 标记位置来源；原生位置投影可能为整数，与内部未舍入的运动采样不混用。GUI掉落物现有 `x/y` 是原生目标落点锚点，标为 `native_drop_destination`，不是悬浮或拾取飞行的当前显示位置，其向量保持未知；不为填满共同字段而伪造当前位置或零速度。

`entity.velocity={x,y,source}` 单位为**地图像素/秒**，右、下为正，上升时 `y<0`。`source="native"` 表示本端当前速度字段的已校验读取；`source="native_update_delta"` 表示同一实体完整原生更新前后未舍入坐标的位移除以该逻辑步长，并附 `interval_ms`，是这段更新的平均运动向量。无头逻辑步长为8ms，坐标和速度不使用重复渲染的整数像素作差。初次样本或原生显式重定位无法形成连续区间时保持未知。`nil` 与实际已测得的 `{x=0,y=0}` 不同，不借用自己或另一实体的向量，也不按物体类型硬填零。

向量描述本客户端的运动，不承诺服务器权威速度或下一步轨迹。无头远端玩家存在延迟后追赶目标坐标的跳步；相应区间向量可呈脉冲，不能解释成服务端连续跑速。投射物条目不自动表示碰撞或伤害，也不伪造跨帧稳定ID。已支持的原生飞行集合不代表全部怪物投射物、召唤物或地图危险物，需查看覆盖范围与 `projectiles_complete`；不支持的集合保持未知。掉落物即使 `landed=true` 仍可能悬浮移动，不能据此推断向量为零。

`character.on_ground` 来自本端地面事实，未知时不能靠重复坐标推断；`character.attacking` 的攻击动画目前只在无头已知，GUI保持未知。`character.native_updates` 只随真实角色更新增加，用于识别渲染是否复用了同一个角色物理样本；不是输入消费或服务器效果成功的凭据。

`game.character.movement` 与当前速度分开，是**静止平地、正常行走/普通跳跃、无额外外力和障碍**的模型参考。已知时提供：

| 字段 | 含义 |
| --- | --- |
| `kind="model"`、`model`、`conditions` | 推算性质、本端模型名、`stationary_flat_ground_normal` 适用条件 |
| `effective_speed/effective_jump` | 当前本端物理实际使用的有效 SPEED/JUMP 百分比属性，不是配置上限或默认100 |
| `max_speed` | 正常平地完整方向输入的参考最大移速，地图像素/秒；不是所有状态下的硬速度截断 |
| `max_jump_height` | 从静止起跳可上升的参考高度，地图像素；不是当前位置相对目标平台的可达保证 |

无头 `headless_normal_v1` 使用当前 `get_walkforce/get_jumpforce` 和同一 `Physics` 实现的摩擦、重力及8ms步长：参考移速由地面递推的稳态求得；跳高按首个地面起跳步不加重力的离散积分推算。GUI `v17_normal_continuous_v1` 使用原版当前属性对象的已校验比例及本端已加载物理系数，以正常场地系数为1、平地坡度为0推算连续参考；实际离散更新及整数位置可造成高度差异。不能互换两端公式。有效属性变化后参考随采样更新；来源或校验不可用时为 `nil`，不用另一后端、静态模板或属性cap补齐。

无头行走渐近趋于稳态，不能用速度严格等于参考值作为起跳条件；示例按目标方向达到参考移速的99%判断，不用固定时长、距离或仅凭速度不再变化。斜坡、墙、绳梯、水下、技能、推力、平台运动、天花板等不符合参考条件，需另行判断。

### 角色状态机与动作槽

同一客户端的所有 tick 会话共享唯一 `context.game.player`；各会话按接纳顺序调用，跨会话冲突首版采用后写覆盖，不提供优先级或所有权治理。coroutine 引擎的控制权和输入状态与它分开。

| API | 语义 |
| --- | --- |
| `player.move("left"/"right"/"up"/"down")` | 设置持续方向；重复设置幂等，改变方向覆盖；`up` 可用于门户，不另外提供传送 API |
| `player.move(nil)` | 清除移动意图 |
| `player.jump()`、`player.attack()`、`player.pickup()` | 提交一次跳跃、普攻、拾取 |
| `player.skill(skill_id)`、`player.use_item(item_id)` | 正 int32 ID；技能及普通恢复品按本端实际能力准入 |
| `player.stop()` | 清除持续意图及待执行动作，发起当前动作释放；收束从后续状态读取 |
| `player.status()` | 只读操作快照：`moving/action/phase/busy/held/pending_action/reason/effect/dispatched/control_released`；当前技能或药品动作另附 `skill_id/item_id` |

每个动作提交返回 `ok, reason`：受理为 `true`；暂忙为 `false, "busy"`；能力不支持为 `false, "unsupported"`，均不因为暂不可用而结束脚本。参数类型错误、非法方向和越界 ID 报 Lua 错误。幂等重复不产生新动作；同 tick 多次有效提交只保留最后一次，不在中途投放输入。

一次性动作同一时间只有一个活动槽。**忙时提交不同动作会写入单个后继槽，同时返回 `false, "busy"`**；当前动作完成后执行该待执行动作，后写覆盖已排队动作，不累积无界队列。同 tick 多次提交也只保留最后一个有效输入。`jump/attack/skill` 保持移动方向；`pickup/use_item` 执行期间暂停移动，完成后恢复持续意图。`held` 是语义键名数组，`phase` 为 `idle/running/releasing`；`effect="unknown"` 不表示游戏失败或成功。

“动作完成”仅限本端能够观察的边界：jump 确认起跳按键的消费及释放，不等待落地，允许仍在空中时接续 attack；飞行与落地另看本端物理事实或场景观察。无头 attack/skill 等待本地攻击动画结束；用药和拾取确认请求及按键消费/释放，游戏效果仍为 unknown。GUI 仅确认原生输入/请求生命周期，缺失完整动画完成事实时不伪造；一次 60ms 按键脉冲不是完整攻击动画。动作槽空闲或 `control_released=true` 均不能当作命中、拾取、药效或 buff 生效证据。

取消、期限、角色变化、离开游戏及错误只结束对应会话，不结束另一引擎或其他 tick 会话。会话终态在所属输入已经过原生消费/释放确认后发布；取消某个 tick 会话不清空其他会话仍有效的输入。窗口、对话、商店、AP/SP、装备界面等非即时交互不纳入 tick player，由 CLI 逐步操作。内置旅行/狩猎/恢复脚本仍是 coroutine，未在本需求迁移；验证用 tick 文件是独立输入，不代表内置策略已经迁移。


## 策略参数与静态场景

运行参数用紧邻策略源码的 `@option` 注释声明。支持 `int`、`number`、`string`、`boolean` 四种类型；未标 `opt`、也没有 `default` 的非布尔参数必填。布尔参数始终可省略：未显式声明 `default` 时默认 `true`，显式 `default=false` 可覆盖该默认值。可选修饰符为 `default=值`、数值型 `min=值` / `max=值` 和 `choices=值1|值2`。默认值、正向布尔 flag 和显式值按声明校验；`--no-flag` 作为无值负向开关直接传入 `false`，不参与 `choices` 校验。

```lua
-- @mode tick
-- @option[type=int,min=1] mob_id 目标怪物模板ID
-- @option[type=boolean] observe_only 仅观察；省略时默认true
-- @option[type=boolean,default=false] attack_enabled 默认关闭攻击
local function main(context)
    if not context.game.world.ready then return end
    game.log("map=" .. tostring(context.scene.map_id)
        .. ", mob=" .. tostring(context.options.mob_id)
        .. ", observe_only=" .. tostring(context.options.observe_only)
        .. ", attack_enabled=" .. tostring(context.options.attack_enabled))
    return "done"
end
```

CLI 参数名把 Lua 下划线转为连字符，例如 `mob_id` 使用 `--mob-id 1001001`。布尔选项可用裸 `--flag` 与 `--no-flag` 分别传入 `true`、`false`，也可显式写成 `--flag true|false`。省略布尔选项时，`context.options` 收到声明的默认值；未显式声明时收到 `true`，`default=false` 时收到 `false`。`choices` 校验默认值、正向 flag 和显式值；`--no-flag` 不会因 `choices` 未列出 `false` 而拒绝。其他可选参数仅在实际提供或声明默认值时出现在 `context.options` 中。`script describe FILE` 根据注释输出每项参数的类型、必填状态、有效默认值、范围、候选值和调用用法。

CLI 提供的初始场景身份不能作为普通 `@option` 覆盖；核验后，当前身份及地形由原生维护，跨图规则见[当前静态场景与跨图](#当前静态场景与跨图)。`footholds` 中 `x1 == x2` 的条目是竖直墙段（`y1/y2` 为上下端），其余为水平或倾斜地面，`prev/next` 保留原始连接。策略先检查 `terrain.status` 再使用几何；动态 HP、位置、技能和库存等事实仍从当前 `context.game` 独立只读领域读取。

初始化与后续宿主更新均由原生 tick 引擎核对身份及场景。初始化或初始身份核验失败时不进入 `main`；稳定场景的静态资料不可用则仍进入 `main` 并明确返回该状态，策略在动作前检查当前领域的就绪、角色、场景及所需地形事实。调用方已有的预计算 `context.route` 可保留，没有路线不自动生成；当前内置旅行、狩猎和恢复脚本仍使用另一套引擎，不是本引擎的函数库。

## 示例与实现入口

从 [tick-jump-attack.lua](../shared/scripts/examples/tick-jump-attack.lua) 学习持续意图、按真实速度起跳及落地确认；脚本说明与运行命令见 [共享脚本README](../shared/scripts/README.md#tick-动作入门连续移动跳砍)。例子按真实事实推进，不以动作接纳代替游戏效果。

实现入口：[TickRuntime.cpp](../shared/lua-runtime/TickRuntime.cpp)、[无头tick适配器](../headless/src/TickNativeAdapter.cpp)、[GUI桥](../beidou-ijl15/ezorsia/AgentBridge.cpp)。领域与预算、状态机和停止语义以本页为准，不向旧引擎转发。
