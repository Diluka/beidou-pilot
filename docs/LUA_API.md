# Lua 脚本 API

本文是编写脚本的优先参考，描述当前共享运行时实际提供的 `game` 接口。两端使用同一套字段、函数签名和结果模型，以 headless 的脚本契约为基准；可选能力与原生执行前提分别说明。

脚本组织、控制权与传输机制见 [CONTROL.md](CONTROL.md)，复合策略维护约定见 [shared/scripts/AGENTS.md](../shared/scripts/AGENTS.md)。修改公开 API 时同步维护本文；记忆或策略目录只引用该入口。

## 启动与基本约定

从项目根运行受信的 UTF-8 源码或文本脚本文件：

```bash
private/workbenches/workbench /external/workbench script run --code 'game.log("你好，Lua")' --seconds 20
private/workbenches/workbench /external/workbench script run /work/scripts/control.lua --seconds 20
# 需要持续执行时显式使用 --continuous
```

文件路径按容器内部解析；完整工作台读写挂到 `/work`，用户脚本直接读取 `/work/scripts`，内置 Lua 随镜像版本固定。

`script run` 同步等结果，`script start` 等待原生受理。CLI 中断、等待超时或观察失败只结束等待，已发布的任务继续运行；先读 `script status` 核对当前会话，再决定下一步。需要取消时明确 `script cancel --session SCRIPT_ID` 并核对终态与放键，客户端关闭另用 `close`。

- 脚本源必须是 UTF-8 纯文本，原生装载上限为1 MiB，不接受预编译字节码。自定义 `script run` 默认30秒，`--seconds` 可设为 `0.001..4294967.295` 秒；`--continuous` 表示无总期限。项目复合策略包装的单独预算只作用于该策略。
- 文件与 `--code` 二选一。直接源码须按调用方 shell 的引号规则传为一个参数，CLI 保留传入的引号、中文和换行；文件每次读取当前内容。两者使用相同 `game` API 与执行链，可在现有实例中提交生效。直接源码结果的 `script_file` 为 `null`。
- 每次脚本启动创建独立 Lua 状态，主任务名为 `main`。多个任务共享这次 Lua 状态；主任务返回后，已创建任务继续执行，全部任务结束且输入释放确认后脚本才结束。原生执行期限到达、脚本错误或明确取消会停止本次会话全部任务。脚本结束不会关闭客户端容器。
- 自定义脚本自行声明 `local options = {...}`；项目的复合能力由 CLI 装载器在脚本前注入 `local options`，这类文件配合对应参数装载使用。
- `game.state()` 返回轻量状态采样，`game.observe(domain)` 按需读取一个原生领域。两者都返回独立 Lua 表拷贝，后续状态变化不修改旧表。执行动作或等待后重新读取，连续读取可能得到同一 `seq`。
- 未知字段为 `nil`，在 Lua 表中等同于缺键。已知的 `false`、`0`、空表 `{}` 与未知不同；`inventory == nil` 表示未知，按未知值处理。
- 所有 `seconds` 参数使用秒。可选参数省略或传 `nil` 时采用默认值；有效时间向上取整为毫秒，实际恢复受游戏更新、释放确认和调度影响，以真实恢复时间为准。

## 函数总览

| 函数 | 参数与默认值 | 是否让出执行权 | 返回值 |
| --- | --- | --- | --- |
| `game.state()` | 无 | 否 | [状态表](#状态表) |
| `game.observe(domain)` | 必填领域名，见[按需领域观察](#按需领域观察) | 否 | 领域状态、采样身份与原生数据 |
| `game.capabilities()` | 无 | 否 | [能力表](#能力表) |
| `game.time()` | 无 | 否 | 单调时间，单位秒 |
| `game.sleep(seconds)` | 默认 `0`，有限数且 `0 <= seconds <= 30` | 是，包括 `sleep(0)` | 无 |
| `game.spawn(name, priority, fn)` | 会话内唯一名称，1..64字节且不含NUL，保留 `main`；优先级为有符号32位整数；`fn` 为函数 | 否 | 任务名 |
| `game.acquire()` | 无，使用当前任务的优先级 | 新取得控制时让出；已持有时不让出 | 无 |
| `game.cancel(name)` | 已创建的任务名 | 取消自身时结束当前任务 | 是否发生取消；已结束为 `false` |
| `game.tasks()` | 无 | 否 | [任务与控制权快照](#任务与控制权) |
| `game.move(direction, seconds)` | 方向 `left/right/up/down`；默认 `0.3`，有限数且 `0 < seconds <= 30` | 是，等待输入释放确认 | [动作结果](#动作结果) |
| `game.face(direction)` | 只接受 `left/right` | 是 | 动作结果 |
| `game.jump(seconds)` | 默认 `0.06`，有限数且 `0 < seconds <= 30` | 是，等待输入释放确认 | 动作结果 |
| `game.attack(seconds, direction, skill_id)` | 默认 `0.06`；可选 `direction=left/right` 同窗保持移动，可选 `skill_id` 请求指定技能；`0 < seconds <= 30` | 是，等待输入释放确认 | 动作结果及本窗技能准入 |
| `game.pickup(seconds)` | 默认 `0.06`，有限数且 `0 < seconds <= 30` | 是，等待输入释放确认 | 动作结果 |
| `game.use_item(item_id)` | 整数 `1..2147483647`；两端接受普通 `200` 类药品，无头另接受 `201` 类食品 | 是 | 动作结果 |
| `game.equip(backpack_slot, equipped_slot, seconds, ref)` | 普通装备；背包正槽、身上负槽；默认期限 `3` 秒，可选当前对象引用，范围见正文 | 是，等待槽位变化或本次执行结束 | 动作结果 |
| `game.unequip(equipped_slot, backpack_slot, seconds, ref)` | 无头普通装备；身上负槽、空背包正槽；确认期限同 `equip` | 是，等待槽位变化或本次执行结束 | 动作结果 |
| `game.allocate_ap(stat, count, seconds)` | 两端；明确基础属性与 `1..100` 点；每点确认期限默认 `1.2` 秒，`0 < seconds <= 30` | 是，逐点双确认或有界停止 | 动作结果及 `allocation` |
| `game.allocate_sp(skill_id, count, seconds)` | 两端；明确冒险家职业技能与 `1..100` 点；每点确认期限同 AP | 是，逐点双确认或有界停止 | 动作结果及 `allocation` |
| `game.window(name, opened, seconds)` | GUI 的 `inventory/stats/skills`，明确开关布尔值；默认 `3` 秒，`0 < seconds <= 30` | 是，等待当前窗口与释放确认 | 动作结果及 `ui` |
| `game.focus(seconds)` | GUI 游戏焦点；默认期限 `3` 秒，范围同窗口 | 是，等待焦点与释放确认 | 动作结果及 `ui` |
| `game.revive(seconds)` | 无头普通复活；默认确认期限 `6` 秒，`0 < seconds <= 30` | 是，等待同角色恢复或期限结束 | 动作结果 |
| `game.activate(ref)` | 当前原生控件或场景目标的不透明引用，仅接受这一个参数 | 是，等待单次控件处理和控制释放 | 动作结果 |
| `game.stop()` | 无 | 是，等待释放确认 | 动作结果 |
| `game.log(text)` | 字符串，限制见[日志与预算](#日志与预算) | 否 | 无 |
| `game.keys(keys, seconds)` | 原版可选；默认租期 `0.1`，`0 < seconds <= 30` | 否 | 无 |
| `game.press(keys, seconds)` | 原版可选；默认 `0.06`，`0 < seconds <= 30` | 是，等待释放确认 | 动作结果 |
| `game.skill(skill_id)` | 后端可选；整数 `1..2147483647` | 否 | [技能结果](#直接技能) |

移动、战斗和按键函数等待原生输入释放或该动作的本地执行边界，服务器效果另行判断；普通换装等待正常库存更新中的源、目的槽位确认，普通复活等待同一角色实际恢复。一次函数调用可能对应多个原生重复输入、多个攻击目标或多个拾取对象。

## 任务与控制权

`spawn` 创建由共享运行时调度的独立 Lua 任务。一个任务等待动作、控制权或 `sleep` 时，其他任务仍可调用 `state/observe/time/log/tasks`，观察和判断。任务共享 Lua 全局变量与闭包，协程由 `spawn` 统一管理。

普通单脚本的 `main` 默认拥有控制，优先级为 `0`，`stop()` 后继续动作会自动恢复控制，已有动作写法继续可用。多个动作任务先调用 `game.acquire()`，取得控制后重新读取 `game.state()`，再决定下一步。`move/face/jump/attack/pickup/use_item/equip/unequip/revive/activate/keys/press/skill` 都要求当前任务拥有控制；失去控制后直接调用会报 `control_not_owned`。

优先级越大越先取得控制。高优先级任务请求接管时，旧任务立即停止派发冲突动作，运行时请求释放原生输入，确认释放后才授权新任务；等待释放期间其他任务仍可观察。相同优先级保持当前控制者，等待者按请求顺序取得控制。控制权跨 `sleep()` 保留，直到 `stop()`、任务完成、任务取消或更高优先级接管。

被接管的有界动作仍返回标准动作结果，`reason="control_preempted"`；`dispatched` 保留本次动作是否已派发的事实，`effect` 仍是 `unknown`。运行时分别保存每项任务的结果。被接管任务再次 `acquire()` 后读取当前角色、场景、位置和目标，重新规划；旧动作保留为历史，已发生的动画、惯性、药品消耗或服务器效果按实际记录。

`game.stop()` 只释放当前任务拥有的控制，不结束任务。非控制者调用时不触碰其他任务输入；自己原有输入仍在交接释放时等待确认，否则返回 `dispatched=false`、`control_released=true`、`effect="unknown"`、`reason="control_not_owned"`，其中释放事实只针对调用任务。`game.cancel(name)` 停止指定名称的当前最新版本；未知名称报错，已经结束则返回 `false`。停止旧任务只释放其自身输入，后续控制者的输入保持。任务正常返回会释放自己仍持有的控制；任一 Lua 错误沿用 `script_error`，取消本次会话全部任务并等待放键。

任务结束或取消后，运行时解除协程的保活引用，局部变量与返回值可由 Lua 回收；任务名称和状态历史保留到会话结束。取消自身会先让出，再在本次协程恢复返回后解除引用。

`game.tasks()` 返回一次快照，格式为：

```lua
{
    tasks = {
        {name = "main", revision = 1, priority = 0, status = "completed", wait = "none",
         reason = "script_returned"},
        {name = "chase", revision = 2, priority = 10, status = "waiting", wait = "control"},
        {name = "retreat", revision = 3, priority = 20, status = "waiting", wait = "action"}
    },
    control = {
        owner = "retreat", pending = "chase",
        from = "chase", to = "retreat", reason = "priority_preempted"
    }
}
```

任务 `status` 为 `running/waiting/completed/cancelled`，`wait` 为 `none/sleep/action/raw_keys/release/control`；`reason/error` 已知时提供字符串。`revision` 是会话内分配的非零版本号，每个新任务或替换版本都不同。同名替换后的历史版本保留，当前版本是该名称的最新revision。`control.owner` 是当前控制者名称，`pending` 是等待取得控制的首个任务，`from/to/reason` 记录最近一次交接；没有对应值时为 `nil`。CLI `script status` 的 `script.tasks` 和 `script.control` 提供相同状态，JSON 中未知文本为 `null`。旧桥未提供这些字段时，CLI 保留缺失事实，并明确拒绝缺少revision的任务管理请求。

下面只演示同层追击坐标与撤退的协调。调用方依据已核实场景提供目标坐标、撤退坐标和触发秒数；实际策略还须核对角色、场景、安全范围和目标有效性。

```lua
local function start_pair(target_x, retreat_x, trigger_after)
    local function approach(x)
        while true do
            game.acquire()
            local s = game.state()
            assert(s.ready and s.position and s.character.hp > 0, "not_ready")
            local dx = x - s.position.x
            if math.abs(dx) <= 12 then return end
            -- 抢占后下一轮先重新取得控制和采样，不重放上次移动。
            game.move(dx > 0 and "right" or "left", 0.1)
        end
    end

    game.spawn("chase", 10, function() approach(target_x) end)
    game.spawn("retreat", 20, function()
        game.sleep(trigger_after)
        approach(retreat_x)
        game.stop()
    end)
end
-- 在调用方脚本中以已确认的场景参数调用 start_pair。
```

运行期间可由已有 Lua 任务按条件调用 `spawn()` 补充逻辑，也可由调用方通过 `task add/replace/stop` 管理独立任务，具体命令见 [CLI参考](CLI.md)。新源码是共享本会话全局环境的独立chunk，不捕获旧任务局部变量；主任务 `main` 保留给整会话入口。`spawn()` 的历史名称唯一规则保持，外部显式替换才允许创建同名新版本。

替换源码的编译失败只拒绝该管理请求，旧任务和控制权保持；新版本运行后发生Lua错误，仍沿用整会话 `script_error` 语义。外部管理不延长原会话期限、不创建第二个动作控制者。整会话结束后需重新 `script run`，新任务在新的会话中提交。

## 能力表

```lua
local caps = game.capabilities()
if caps.skill then
    local result = game.skill(1001004)
end
```

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `backend` | string | 当前为 `headless` 或 `beidou` |
| `move`、`face`、`jump`、`attack`、`pickup`、`use_item`、`stop` | boolean | 后端是否实现该语义动作；当前两端均实现 |
| `equip`、`unequip` | boolean | 无头支持普通穿戴/卸下；GUI 支持唯一兼容槽位的普通穿戴，卸下为 `false`；歧义槽位按未知处理 |
| `allocate_ap`、`allocate_sp` | boolean | 两端均支持明确逐点双确认；仅冒险家普通职业 SP 池，其他池明确拒绝 |
| `window` | boolean | GUI 支持三种必要窗口与游戏焦点；无头为 `false` |
| `revive` | boolean | 是否实现正常复活请求与确认；当前 headless 为 `true`，原版 Lua 为 `false` |
| `activate` | boolean | 是否实现原生控件引用激活；当前 headless 为 `true`，原版 Lua 为 `false` |
| `raw_keys` | boolean | 是否实现 `keys/press`；当前 headless 为 `false`，原版为 `true` |
| `skill` | boolean | 是否实现直接技能入口；两端为 `true`，具体技能类型随后端支持范围 |
| `attack_move` | boolean | 是否支持 `attack` 的方向与技能窗口参数；新两端构建均为 `true`，旧构建缺失时按无该能力处理 |
| `monster_hp_percent` | boolean | 是否能读取服务端目标HP百分比；headless 为 `true`，原版为 `false` |

能力只表示有实现，当前角色、地图、装备、库存或动作状态是否允许执行另行判断。可选函数在两端均已注册；支持判断以能力表为准，例如读取 `caps.skill`。能力名称以表中字段为准。

## 状态表

以下六个字段总是存在：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `instance_id` | string | 原生进程实例身份，用于发现实例变化 |
| `seq` | integer | 当前实例的采样序号，不是脚本步数 |
| `observed_at_ms` | integer | 采样的 Unix 时间戳，毫秒 |
| `scene_generation` | integer | 原生场景代次；同地图重新进入也可能变化 |
| `ready` | boolean | 地图、角色、位置等基础对象已就绪；角色存活、动作许可与领域完整性另行判断 |
| `in_game` | boolean | 原生是否仍在游戏中；`false` 表示宿主已确认离开游戏，与短暂的 `ready=false` 是两项事实 |

其余字段在对应信息已知时提供，否则为 `nil`：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `map_id` | integer | 当前地图 ID |
| `character` | table | 角色属性，见下表 |
| `position` | table | `x/y` 为地图世界坐标数值，通常向右 x 增加、向下 y 增加；桌面像素位置另见 GUI 坐标字段 |
| `facing` | string | `Left` 或 `Right`，注意大小写与动作参数不同 |
| `settled` | boolean | 已知的本地物理/攻击收束状态；`nil` 表示未观察到该事实 |
| `dead` | boolean | 无头已就绪角色的原生 HP 为零时为 `true`，HP 为正时为 `false`；读数不可用或后端未提供该事实时为 `nil` |
| `revive_requestable` | boolean | 无头已知死亡且当前原生控制已释放，可提交一次普通复活请求；服务器或事件脚本许可由实际请求结果确认，未知为 `nil` |
| `monsters` | array | 当前客户端已知怪物，元素结构见下文 |
| `players` | array | 当前客户端已知的同图其他玩家，元素结构见下文 |
| `players_complete` | boolean | 已知时表示本端能否完整解释当前场景的玩家封包；`nil` 表示未知 |
| `inventory` | array | 五类背包的已占用正槽；不含身上装备负槽 |
| `drops` | array | 当前客户端已知掉落，元素结构见下文 |

`settled` 在 headless 中依据不处于攻击、不移动，且在地面/攀爬/水下计算；原版目前保持未知。它只描述本地状态。字段已知程度可以因后端或过渡状态不同而不同。

轻量状态的字段以本表为限，频道、任务、NPC、金币总额、技能表、已装备列表等由 `game.observe(domain)` 提供；CLI 快照或 `state.json` 的字段与 `game.state()` 字段分别定义。

### character

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id`、`name` | integer、string | 角色 ID 与名字 |
| `level`、`job` | integer | 等级与职业 ID |
| `strength`、`dexterity`、`intelligence`、`luck` | integer | STR、DEX、INT、LUK |
| `hp`、`max_hp`、`mp`、`max_mp` | integer | 当前与最大 HP/MP |
| `ability_points`、`skill_points` | integer | 未分配 AP/SP |
| `experience` | integer | 当前客户端记录的经验值 |

属性字段仅在已知时出现。当前两端通常整组采集属性；脚本仍应核对自己需要的字段，角色存活以 `hp` 判断。

### monsters 的元素

`object_id: integer`、`x/y: number`、`active: boolean`；已知时有 `template_id: integer` 与非空 `name: string`。

- `object_id` 是本次场景对象 ID，`template_id` 是怪物模板 ID，两者分别使用。
- `active` 来自本地模型，服务器确认的 HP 与击杀另行观察。
- `hp_percent`、`hp_sequence`、`hp_source` 在无头收到该对象的服务端HP包后才提供，分别为0..100百分比、该对象生命周期中的包更新序号及 `server_mob_hp`。未收包、旧对象或GUI未支持时为未知，默认值按未知处理。
- HP下降证明观察到目标状态变化；该包不带攻击者或动作ID，攻击归因结合实例、场景与OID判断。新对象的序号重新开始。
- 怪物字段以本节为准，攻击入口为 `game.attack`，按方向与技能窗口派发。

### inventory 的元素

`inventory_type: integer`、`slot: integer`、`item_id: integer`，数量已知时有 `quantity: integer`。

`inventory_type` 当前为 `1=装备、2=消耗、3=设置、4=其他、5=现金`。一个物品可能占多个槽位，按 ID 求总量时合计各项；任何相关项数量未知时保持未知。空槽不列出，身上装备负槽另见 `equip` 相关字段。

### drops 的元素

总有 `object_id: integer`、`x/y: number`；已知时有 `item_id: integer`、`money: integer`、`landed: boolean`。

原版可能提供金币金额；headless 当前没有金额数据，`money` 保持未知。金币掉落以 `money` 字段判断，`landed == nil` 表示落地状态未知。掉落 OID 与物品模板 ID 分别使用。

### players 的元素

`reference: string`、`x/y: number`；已知时有 `character_id: integer`、`name: string`、`level: integer`、`facing: "Left"/"Right"`。

- `reference` 是本端本场景内的稳定引用，换图或重新进入场景（`scene_generation` 变化）后失效，不能与旧场景的玩家对应。
- `character_id` 是角色 CID；`reference` 和它分别表达本端引用与已知角色标识，未收到时为 `nil`。
- 列表只描述本端已经知道的同图其他角色，不承诺屏幕可见范围、全服玩家目录或对方真实位置；位置与朝向是当前原生采样。
- `players_complete` 只在能完整解释当前场景玩家封包（无头）或完整校验当前用户池快照（GUI）时为 `true`；不完整时为 `false`，此时列表可能缺少角色，空数组不能当作“没有其他玩家”。
- 无头端从已解析的原生角色对象读取，GUI 端从原版客户端用户池读取；两端字段口径一致，等级、朝向等字段按本端能力提供，未知时省略。
- HP、装备、队伍与好友关系不在此观察范围；GUI 用户池是否包含隐身等不可见状态尚未确认，读数只代表本端已知对象。

## 按需领域观察

`game.observe(domain)` 在当前原生更新线程同步读取指定领域，调用无需动作控制权，结果在进程内直接返回。只有调用时才采集该领域；`game.state()` 的每帧轻量采样保持精简。按业务决策需要查询，长循环仍通过 `sleep` 或动作函数让出执行权。

`domain` 精确接受下表名称。未知名称或缺少参数会产生 Lua 参数错误；合法但后端未实现的领域返回 `status="unsupported"`。

| 领域 | 两端支持与主要原生字段 |
| --- | --- |
| `stage` | 两端；阶段、频道与角色摘要，具体已知范围随后端和当前阶段变化。GUI 的 `windows` 为同次原生采集的活动窗口原始数组，采集不可用时为 nil 并在 `unavailable` 说明；无头不承诺该字段。窗口含地址、vtable、已验证的 `type_name`、尺寸、`layer_rect`、`game_rect`、`window_position_source` 和已识别按钮的 ID、尺寸、局部位置及启用状态；`layer_rect` 是原生图层缓存的未投影矩形，尺寸不一定与窗口匹配；`game_rect` 是以相机原点转换的游戏区相对矩形，仅在图层尺寸匹配窗口、窗口头及图层边界复读一致且相机前后一致时提供，不使用按钮父坐标推断；可结合当前桌面 `game_geometry` 的 x/y 换算 root 坐标。二者是非原子采样候选，不等同于已验证点击坐标，截图及几何应重新核验；`login_page_candidate` 仅在登录对象及窗口完整 vtable、尺寸匹配单次 GUI 实测样本时为 `terms` 或 `gender`，其余为 nil。`login.raw_world_selection` 是只读世界选择窗口的 `{count, selected_index, raw_world_id}` 原始候选；其中 `raw_world_id` 为所选数组项的原始 WORD，仅基于同哈希 PE 的 `0x5f8092` 静态访问链，未实测映射，未选中或读取不稳定时为 nil；不满足登录 step 1、活动窗口与完整类型核验、前后稳定性或读取失败时为 nil，`selected_index=-1` 表示原始未选择值，不表示世界 0，索引与世界 ID 的关系未知。反汇编依据同哈希 PE 的 `0x624ab7`、`0x624ef6` 及世界窗口虚表；count 按静态控件容量保守限制在 0..30。快照并非原子或动作成功证明。登录窗口可提供 `login_edit_focus`（`account`/`password`/nil）与 `account_empty`、`password_empty`（boolean/nil）；只读取控件身份、焦点及字符串长度头，不读取或返回文本、长度或凭据。基于同哈希 PE 的登录窗口构造、edit getter 与 CWndMan 焦点路径；不稳定或读取失败为 nil，重复采样不是原子保证，输入前须重新核验。性别候选窗口的 `raw_gender_selection` 是稳定采样的原始字节 0 或 1，读取失败、变动或其他值为 nil，不声明性别对应关系，也不授权自动点击。依据为单次实机窗口样本及 SHA256 `1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df` 的原版 PE 静态反汇编：`0x61362e` 处理控件 8004 通知并通过 `0x61366c` 写入 `+0x15c`，`0x613b98` 在确认路径读取该字段。外观窗口匹配时 `raw_appearance_candidates` 可返回八个无语义的原始 DWORD；仅依据同哈希 PE 的 `0x5f7f84`、`0x5fe0b2` 和 `0x5fd2e8` 静态路径，两个快照须一致，空数组、读取错误、溢出或状态不符为 nil。重复采样不保证原子性，索引与值尚未经过实机变化验证，不能用于自动输入或推断外观。候选不是页面或可点击性的确认，实际输入仍须结合当前截图和状态核验；未知值为 nil。该数组不是与桌面截图同帧的保证 |
| `scene` | 两端；`map_id`、`player`、`player_facing`、`monsters`、`npcs`、`drops`、`players`。NPC 提供 `object_id/template_id/name/x/y`；`players` 两端分别从本端原生角色对象/原生用户池读取；保留本端已知字段及限制 |
| `inventory` | 两端；`items` 为已占用正槽，`equipped` 为身上负槽，元素含 `inventory_type/slot/item_id/quantity`；`capacities` 以字符串背包类型为键 |
| `character` | 两端；`character_id`、`mesos`、`skills`、`skills_complete` 及本端校验说明。`skills` 以字符串技能 ID 为键，记录含 `level/master_level`；名称、需求和效果的覆盖情况见本端校验说明 |
| `quests` | 两端；`quests` 元素含 `quest_id/state/progress`，状态为 `started/completed`，进度保留原始文本。无头从完整角色包和本端正常增量维护记录；未核实的 `linked_progress` 为 nil |
| `hotkeys` | GUI；原生快捷键与快捷栏映射、已知布局和限制 |
| `interaction` | 无头；`data.page` 是当前通用页面或 nil，页面和控件结构见[控件交互](#控件交互)；GUI 使用 `dialog` |
| `dialog` | GUI；`dialog_open`、`npc_id`、`dialog_type`、`lines`、`choices`、`buttons` 及来源窗口说明；无头使用 `interaction` |
| `ui` | GUI；`windows`、`dialog` 与原生游戏区布局 |
| `notifications` | GUI；所有同类原生通知气泡的种类、已知来源、期限、状态和实际按钮 |
| `shop` | GUI；`open`、`npc_id`、`buy_items/sell_items`、选择/滚动位置、`busy` 和数量窗口状态 |

`notifications.data.notifications` 的每项保留 `id/native_kind/kind`、`source_text/text`、`sender_id/party_id/interaction_id/quest_id`、`expires_at_ms/remaining_ms`、`pending/available`、`window/buttons`。`native_kind` 保留原生整数，`kind` 只提供已证实标签，未识别为 `nil`；响应通路按当前按钮决定。关联字段未知为 `nil`，交易的 `interaction_id` 与玩家 ID 是两个字段。原生来源槽的文字是 `source_text`；完整渲染正文尚未提取，`text=nil`，`not_covered` 明确包含 `rendered_body_text`。

原生 duration 为0时表示没有自动到期时间，两个期限字段为 `nil`，可操作状态按当前 pending 与真实控件判断；服务端有效期另行判断。每个实际按钮保留 `control_id/layout_x/layout_y/width/height`，2000标为 `primary`、2001标为 `dismiss`，其他 `action=nil`；按钮组成按类型不同，主按钮含义以当前正文为准。

Lua 使用原生控件引用与游戏区坐标，`@notification` 引用由 CLI 提供。本域只读。使用 CLI 响应时必须重读当前引用，派发事实、气泡状态和业务结果分别确认。组队成员观察与真实闭环继续由 #92 单独交付，公共气泡采集不依赖它。

每次返回的外层结构为：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `domain`、`backend` | string | 本次领域及后端 |
| `status` | string | `ok` 表示已完成领域读取；`unsupported` 表示该端未实现；`unavailable` 表示本次无法读取 |
| `source`、`readonly` | string、boolean | 固定为 `client-native-api`、`true` |
| `instance_id`、`seq`、`scene_generation`、`observed_at_ms` | string、integer | 与当前轻量采样相同的原生身份、序号、场景代次和 Unix 毫秒时间 |
| `ready`、`in_game` | boolean | 当前基础对象就绪及仍在游戏的事实 |
| `character_id`、`map_id` | integer 或 nil | 本次当前已知角色与地图，不取自历史查询 |
| `data` | table 或 nil | 原生领域对象；读取失败或不支持时为 nil |
| `error` | string 或 nil | 本次失败原因；成功时通常为 nil |

`status="ok"` 表示领域读取完成，字段完整性按 `unavailable`、`not_covered`、checksum、`skills_complete` 等原生说明核对；空集合只代表相应已知范围内没有记录。原生 JSON 的 `null` 投影为 Lua `nil`，数组使用从1开始的索引，对象键保留原文。可表示的整数以 Lua integer 提供，坐标等小数保留浮点值；技能和背包容量对象的键仍是字符串，例如 `data.skills["2000001"]`、`data.capacities["2"]`。

`data` 保留原生字段，与同一实例 CLI 领域查询在可比采样下含义一致。CLI 对来源的重命名、派生校验汇总与桌面坐标投影属于外部投影：Lua 中领域原生 `data.source` 对应 CLI 保留的 `data_source`；GUI 的 `root_rect/game_geometry` 保持 `nil`，已有 `game_rect` 等游戏区坐标照常提供。`dialog_open=nil` 表示未知，按未知值处理；商店单价未知时同样保持未知。

GUI 的 `data.read_seconds` 是本次原生领域采集耗时；CLI 的同名结果还包含外部请求与读取时间，两者覆盖的时间窗口不同。

无头任务的 `data.source="character_data_snapshot_and_updates"`、`data.live_updates=true` 表示完整角色包与同会话正常增量共同维护记录。`live_update_kinds` 为 `not_started/started/completed`；移除或放弃会清除旧记录，进度串保留原文；计数、可接任务与关联按原样保留。`linked_progress=nil` 表示关联语义未知。`observed_at_ms` 是采样时间；任务来源的更新时间另行记录。GUI 同样只读取本端当前记录。

非 `stage` 领域在 `ready=false` 时返回 `unavailable`、`error="native_client_not_in_game"` 和 `data=nil`，旧领域缓存不作为本次结果。换图后重新查询并核对 `instance_id/character_id/map_id/scene_generation`；旧表作为历史拷贝保留，新场景重新取得 NPC OID、UI 对象与任务规划。角色变化、离开游戏与整会话取消仍遵循既有停止规则。

只读示例见 [read-domains.lua](../shared/scripts/examples/read-domains.lua)：

```lua
local current = game.observe("character")
if current.status ~= "ok" then
    game.log(current.status .. ": " .. tostring(current.error))
    return
end
if current.data.mesos ~= nil then
    game.log("当前金币：" .. tostring(current.data.mesos))
end
local quests = game.observe("quests")
if quests.status == "ok" then
    game.log("任务增量支持：" .. tostring(quests.data.live_updates))
end
```

## 动作结果

`move/face/jump/attack/pickup/use_item/equip/unequip/revive/activate/stop/press` 返回以下表：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `dispatched` | boolean | 本地动作或释放请求是否已派发；游戏效果另行确认 |
| `control_released` | boolean | 原生控制是否已确认释放 |
| `settled` | boolean 或 nil | 本地动作/物理是否已收束，未知为 nil |
| `effect` | string | 普通换装槽位或普通复活的同角色恢复已确认时为 `confirmed`；其余动作或未确认的变化为 `unknown`；命中、拾取与恢复另行观察 |
| `reason` | string 或 nil | 原生执行说明；例如 `native_action_dispatched`、`already_facing`、`native_attack_not_allowed`、`item_use_requested`、`control_released` |

原生暂不准入可以返回 `dispatched=false`，例如 headless 攻击尚未允许或原版已朝目标方向。它与抛出 Lua 错误不同。`reason` 是诊断信息，只覆盖常见情况；下一步按状态和结果事实决定。

### 基础动作的边界

- `move` 是方向输入，`up/down` 按原生状态用于攀爬、门户等；坐标到达、绳梯目标和转场确认由复合策略实现。
- `face` 可能造成少量移动。共享层请求短动作，headless 直接设置方向，原版可能短按方向或已同向时直接返回；各端时长与位置按原生状态判定。
- `jump/attack/pickup` 的可选时间是输入持续时间；攻击、空中运动和惯性可能在释放输入后继续。
- `attack(0.15, "right")` 同窗保持向右和普攻输入；`attack(0.15, "right", 1001004)` 同时保持方向并请求一次指定技能。Lua决定下一窗口是否继续，适配器不自动重施技能。移动派发与技能准入分别报告为标准 `dispatched` 和 `skill_dispatched/skill_native_result/skill_reason`，两者各自判断。
- 移动和攻击可以同时持有意图；攻击动画是否限制位移、空中是否能出手由各端原生规则决定。绳梯输入等按真实状态安排。
- `stop` 释放当前任务控制后继续执行，任务与 Lua 会话保持运行。结束任务用 `return` 或自然运行完毕。其结果的 `dispatched=true` 表示释放请求。
- `game.keys` 持键期间，先调用 `game.stop()` 等待释放，再开始下一个语义动作。

### 单次用物

`game.use_item(item_id)` 两端接受 `item_id // 10000 == 200` 的普通 HP/MP 药品，无头另接受 `201` 类食品，包括正常任务给予的苹果类物品；库存必须存在。单次原生请求不因 HP/MP 已满而省略，是否需要使用由调用方判断。GUI按物品ID选择消费背包的真实正槽，在既有原生更新阶段直接调用普通用药入口，与快捷键绑定无关。GUI 的其他200类物品与传送卷由其既有 CLI 背包工作流处理。

共享层使用60毫秒动作请求，headless 可能立即进入原生释放阶段；GUI为不持键的单次原生调用，在Lua恢复栈之外派发。原生入口没有可消费的成功返回值，`dispatched=true` 表示已进入原生调用，`effect` 仍为 `unknown`。原生准入、库存消耗和HP/MP恢复分别观察，药效以实际数值为准。重复用药、目标阈值与每次消耗确认由 `recovery/recover.lua` 负责；无头 CLI 的201类单次消费只确认库存恰减一，恢复效果另按前后 HP/MP 观察。

### 无头正常复活

`game.revive([seconds])` 仅在调用方明确请求时执行。已就绪且存活时返回 `dispatched=false`、`effect="confirmed"`、`reason="already_alive"`，此时无需复活请求；原生角色状态不可用时明确报错。已死亡时发出一次不使用复活道具的正常地图请求，并等待同一角色 HP 为正、地图和位置有效。服务器可能先转场再恢复 HP，等待允许这个场景代次变化。

恢复确认后为 `effect="confirmed"`、`reason="revive_confirmed"`；期限内未确认、角色变化或取消时保留 `effect="unknown"` 及本次派发事实，请求按一次执行。事件脚本等服务端许可由实际请求结果确认，`revive_requestable=true` 表示客户端请求前置已满足。动作结果和最新 `game.state()` 共同决定后续策略，此前战斗、复活或重连按需重新发起。

该 Lua 能力仅 headless 提供。原版 Lua 声明 `revive=false`，调用报 `unsupported: revive`；原版 CLI `revive` 使用已识别 GUI 确认框流程。无头死亡时可以装载只读观察或显式复活 Lua；移动、攻击、用物等原有动作按死亡前提返回。

### 控件交互

无头端通过 `game.observe("interaction").data.page` 观察当前页面，再用 `game.activate(ref)` 激活选定控件。没有当前页面时 `page=nil`。Page严格包含四项：`source`（来源字符串）、`title`（标题字符串）、`text`（正文字符串或nil）、`controls`（控件数组或nil）。每个Control只有 `role/text/enabled/ref`；`role/text/ref` 是字符串，`enabled` 为布尔值或nil。未知正文或控件保持 `nil`，未知启用状态保持 `nil`。

`scene` 中NPC目标的 `ref` 与页面控件引用由同一原生交互组件生产。引用绑定所属实例、角色、场景和页面，调用方不解析格式，也不拼对象ID、页版本、任务ID或协议选择参数。页面或场景变化后重新观察；旧引用由原生拒绝，Python 原样传递。

`reason="control_activated"` 表示本次控件已处理；任务、奖励与消费结果从对应领域退出确认。激活后再读当前交互页判断界面变化，任务和收益分别从 `quests`、背包或角色观察核对。激活预算和取消沿用脚本生命周期，不给函数增加内容参数或动作别名。

普通服务端脚本页和客户端本地任务页共用上述模型。后者的 `source="client_local_quest"`，条目、正文与资格来自只读原版 Quest IMG、当前NPC及本端状态；先打开详情，再明确激活确认控件；任务ID目录只作为资料查询。未接任务只在本地资格已知满足时列出；已接任务可读当前详情，确认控件按当前资格启用。已完成历史与普通交谈并列显示；混合来源界面通过同一模型的“交谈”导航切换。

缺少 Quest IMG、未支持条件、重复或脚本特殊流程、复杂奖励选择保持未知；只有已实现的真实控件可激活。本地UI仅对已核实的普通单目标进度格式判定条件，`quests` 领域保留原始文本；成功正文以真实任务状态为准，奖励另读原生事实。待响应或未解析页面保持未知。GUI 的 `activate` 能力为 false，其已有CLI桌面消费者继续使用原流程。

### 明确 AP/SP 分配

`game.allocate_ap(stat, count[, seconds])` 只接受 `strength/dexterity/intelligence/luck`。`game.allocate_sp(skill_id, count[, seconds])` 接受正 int32 技能 ID。两者绑定本次脚本角色、本实例、当前场景代次与职业；读取、登录和升级只产生观察数据。调用方先核实计划，再明确给出目标与数量。

两端 CLI 与 Lua 共用逐点确认组件。无头通过本端职业链、技能资源和已学记录核对技能资格；GUI 使用本端当前职业技能页和原生按钮使能资格，并读回真实技能记录。两者均只支持冒险家普通职业 SP 池；新手派生池及特殊职业池明确拒绝。GUI 无法预先取得的完整等级上限或具体前置原因保持未知，每点只在当前原生按钮明确可用时请求；达到限制后停止并保留已确认数量。AP 作用于四项基础属性，服务器上限保持未知。

初始点数必须足够本批请求。每点只提交一次，只有目标基础属性/技能等级恰增一、剩余 AP/SP 恰减一才计入 `allocated`；AP 还要求其他三项基础属性不变。点数与技能包可以分批到达，等待期间不重复请求。下一点在之后的原生更新重新核对条件。`seconds` 是每点确认期限，GUI 每次必要窗口/页签定位另有至多6秒准备期限；整批仍受脚本总时限、控制权和显式取消约束。

结果沿用 `dispatched/control_released/effect/reason`，增加 `allocation`：`kind` 为 `ap/sp`，`stat/skill_id` 表示明确目标，`requested/allocated` 为请求/已双确认数量，`point_pending=true` 表示曾发出一点而尚未双确认。`points_before/value_before` 是批次开始事实，`points_after/value_after` 是最近一次事实；不可读为 `nil`。`character_id/scene_generation` 是原请求身份，`current_character_id/current_scene_generation` 标识当前读数，身份变化后的值作为新事实单独记录。

全部确认时 `effect="confirmed"`、`reason="allocation_confirmed"`；其他情况保留 `effect="unknown"`、已确认数量及事实，有界停止。点数不足、上限/前置/职业不符可能在派发前拒绝；单侧变化、冲突、身份/场景变化、取消或未知时，先观察实际结果再决定后续。取消先停止新派发；鼠标尚待真实释放时继续保留待确认点，在释放时以同上下文的新鲜双读数收敛已确认数量，等待放键期间保留已观察变化。取消只影响后续派发，已经发生的加点按实际记录；真实释放与客户端关闭是两类独立事实。

```lua
-- 仅在已核实计划明确要求本次角色加一点力量时执行。
local result = game.allocate_ap("strength", 1)
assert(result.effect == "confirmed" and result.allocation.allocated == 1)
if game.capabilities().window then
    assert(game.window("stats", false).effect == "confirmed")
    assert(game.focus().effect == "confirmed")
end
game.face("right")
```

### 明确普通换装

`game.equip(backpack_slot, equipped_slot[, seconds[, ref]])` 从装备背包正槽穿到明确的身上负槽。目的槽已有普通装备时，正常替换会让原装备回到源背包槽。`game.unequip(equipped_slot, backpack_slot[, seconds[, ref]])` 从身上负槽卸到指定的空背包正槽；目标背包槽被占用时返回错误，槽位以调用方指定为准。

无头使用正常装备请求和库存更新；GUI 通过本端已校准普通背包的正常双击路径穿戴，职业、等级和其他装备资格按原客户端正常处理。两端只执行正常装备请求。角色、装备、槽位及本地可核实的条件仍需满足；声望要求以正常服务端处理和实际库存结果为准。GUI 的唯一槽位穿戴与未支持范围见下文，原 CLI 保留声明的自动选择路径。

请求只派发一次。穿戴/替换成功需源槽与目的槽的装备对象对应关系同时符合本次请求；卸下则需源身上槽清空且目标背包槽收到原装备。确认后返回 `effect="confirmed"`；派发、脚本返回或物品 ID 相同属于过程事实，同一件装备以源、目的对象交换为准。

确认期限默认3秒，第三参数仅控制本次等待。超时、任务接管或换图结束等待时，未确认的结果保留 `effect="unknown"`；取消会停止所属任务，不保证继续执行此函数后的源码。这些结束方式不撤销已经派发的服务器请求，请求按一次执行。恢复后先调用 `game.observe("inventory")` 核对当前槽位，再决定后续操作；角色变化及整会话停止仍按既有生命周期处理。

以下使用调用方已经依据最新背包、装备和养成计划确定的 `backpack_slot` 与 `equipped_slot`。多任务先取得控制；结果未确认时保留实际状态，按最新读数决定下一步：

```lua
if not game.capabilities().equip then return end
game.acquire()
local result = game.equip(backpack_slot, equipped_slot)
game.log("换装结果：" .. result.effect .. "，原因：" .. tostring(result.reason))
```

GUI 仅接受原生装备实例被明确识别为普通装备、原生物品/槽位/性别谓词给出唯一目标、且目的槽在 `-19..-1` 的穿戴。戒指、双吊坠等多目标或特殊槽位明确拒绝；原 CLI 的既有自动选择路径仍可使用。GUI 的 `unequip` 为 `false`。背包展开、布局/视口/引用不明、窗口或装备对象变化时停止；窗口、技能页、槽位等待均复用本次 Runtime 控制权，不产生另一操作者。

装备库存条目可提供 `equipment.object_ref`；它绑定本实例、角色、场景代次和当前原生对象。可作为第四参数，派发前不匹配即拒绝。省略时绑定动作开始时的当前对象；旧槽位请求按历史记录保留。GUI 另提供已知的 `ordinary/body_slots`；这些字段在其他后端缺失时保持未知。换装确认要求同一源、目的对象实际交换；GUI 结果的 `equipment` 保留前后引用。取消后只对本次识别的拖拽发送一次正常 Escape 收尾；释放不可确认时按未确认返回。

GUI 连续换装在本次期限内等待原生背包输入就绪后才排队第一次双击；下一次原生请求的就绪状态单独核对。等待原因可为 `equipment_waiting_native_ready`，期限内未就绪以 `equipment_native_not_ready` 停止；就绪事实不可读则为 `equipment_native_readiness_unavailable`。每次按下前重新核对就绪、窗口与对象，排队后失效立即停止并释放；派发后的未知结果按一次执行处理。

### GUI 必要窗口与连续消费

`game.window(name, opened[, seconds])` 的 `name` 仅为 `inventory/stats/skills`，`opened` 必须为布尔值；`game.focus([seconds])` 恢复可确认的游戏焦点。开窗前解析当前原生窗口动作键位，派发前再次核对，按实际键位派发。使用唯一且布局已确认的窗口，拒绝遮挡、对话/商店占用或未知目标。未确认时按当前窗口状态处理；结果的 `ui` 包含窗口名、开关状态、当前窗口引用和游戏焦点。

GUI 养成动作可保留已打开窗口；后续角色动作前由脚本明确关窗、恢复焦点并核对。三种必要窗口之外的 NPC/商店仍使用既有声明范围。

语义动作结果的 `session_id` 表示所属 Lua 会话；快照保留的最后动作属于其所属会话。CLI 养成投影只接纳与本次 `script_id` 匹配的结果；新会话在动作前取消时，旧分配数量与旧窗口确认按历史记录保留。原始按键等扩展没有相应标记时保持未知。

```lua
local bag = game.observe("inventory")
assert(bag.status == "ok")
-- source_slot/target_slot 来自已核实计划与当前原生读数。
local selected
for _, item in ipairs(bag.data.items) do
    if item.inventory_type == 1 and item.slot == source_slot then selected = item end
end
assert(selected and selected.equipment and type(selected.equipment.object_ref) == "string")
local changed = game.equip(source_slot, target_slot, 3, selected.equipment.object_ref)
assert(changed.effect == "confirmed")
assert(game.window("inventory", false).effect == "confirmed")
assert(game.focus().effect == "confirmed")
game.face("right")
```

## 原版按键

`keys` 和 `press` 的第一参数为一个键名字符串或最多16项的密集字符串数组。数组限制按传入项数计算；原生期望集合会合并重复键。空数组 `{}` 表示清空期望键集；`game.stop()`是跨后端且可等待释放的方式。

精确支持的键名：

| 分类 | 键名 |
| --- | --- |
| 方向 | `Left`、`Right`、`Up`、`Down` |
| Ctrl | `Control_L`、`Control_R`、`Ctrl`、`Control` |
| Alt | `Alt_L`、`Alt_R`、`Alt` |
| Shift | `Shift_L`、`Shift_R`、`Shift` |
| 其他 | `space`、`Return`、`Escape`、`Tab`、`Home`、`End`、`Prior`、`Next`、`Insert`、`Delete`、`BackSpace` |
| 字母/数字 | 单字母 `a..z` 或 `A..Z`、单数字 `0..9` |
| 功能键 | `F1..F12` |

除单字母大小写等价外，按上表精确匹配，别名以上表为准。键名被识别后，当前客户端原生键映射仍须支持它，否则会报 `unsupported_native_key`。

### keys：声明完整键集并续租

```lua
if game.capabilities().raw_keys then
    local deadline = game.time() + 0.5
    while game.time() < deadline do
        game.keys({"Right"}, 0.1)
        game.sleep(0.05)
    end
    game.stop()
end
```

每次 `keys` 完整替换期望集合并续租；集合未变化的键不会被重复抬起/按下。请求先写入宿主的单份期望输入，原生更新阶段消费；同一次Lua恢复内的连续更新只保留最新集合。租期结束由原生宿主释放。函数不让出、无返回值，持续循环需主动等待，角色按原生更新推进。`keys({})`发起释放但不等待确认。

`keys()` 后立即返回或停止任务，可以在原生消费前撤销请求，此时没有实际按键派发。需要实际输入时，主动 `sleep` 让出，或使用等待释放的 `press`；运行时不会在任务结束后补发旧输入。

### press：有界按住并等待释放

```lua
if game.capabilities().raw_keys then
    local result = game.press("Right", 0.2)
    -- 控制已释放；移动到达另行按位置确认。
end
```

`press`先提交期望输入并让出，在原生更新阶段派发，等待真实释放确认后返回标准动作结果。`dispatched`保留实际派发事实，消费前已撤销的请求为 `false`；它不识别宏表达式或 `Left+Alt:0.2` 这类文本。

## 直接技能

```lua
if game.capabilities().skill then
    local result = game.skill(1001004)
    game.log("native_result=" .. tostring(result.native_result))
end
```

返回值：

```text
{ native_result = integer, dispatched = boolean, reason = string, effect = "unknown" }
```

GUI 的 `dispatched=true` 表示已进入原生技能入口，`native_result` 保留真实返回，0为原生本地拒绝。无头首批支持战士普通近战 `1001004/1001005`，原生准入枚举0为成功，拒绝由 `dispatched=false` 和 `reason` 说明，包括未学、职业、武器、HP/MP、冷却或动作条件；其他技能类型明确不支持。原生数值按各后端各自解释，命中与效果以实际战斗结果为准。

技能调用直接返回，动画由原生继续推进；持续策略应正常让出并根据原生结果再决定。其结果为技能结果字段，动作收束状态按 `settled` 另行观察。复合 `attack` 窗口会等待所属输入释放，其 `skill_*` 字段只记录本窗单次技能请求，效果仍为未知。

## 错误、期限与生命周期

API 参数无效、后端能力缺失、原生状态或输入路线不可用时会抛出 Lua 错误；原生暂未派发的正常动作结果则可能仅返回 `dispatched=false`。

| 类别 | 常见信息与处理方式 |
| --- | --- |
| 参数错误 | 方向、时长、整数ID、键表或键名不合法；修正调用，不盲重放 |
| 能力不支持 | `unsupported: raw_keys/skill/...`；执行前检查能力，不用“函数存在”判断 |
| 合法领域当前无法读取 | `game.observe` 返回 `status="unsupported"` 或 `"unavailable"`，检查 `error`；这类结果本身不结束脚本 |
| 原生前提不满足 | 如 `state_unavailable_or_dead`、`action_in_progress`、`item_not_in_inventory`、`inventory_unavailable`；重新观察真实状态与已发生效果 |
| 任务控制前提不满足 | `control_not_owned`；动作任务先 `acquire()`，取得控制后重新采样和规划。重复任务名、未知取消名称或无效任务参数也会报错 |
| 脚本执行错误 | API错误或 `assert/error` 导致脚本进入 `script_error`，保留错误文本并释放控制 |
| 日志失败 | 超限会抛错；宿主写日志失败则取消为 `script_log_write_failed` |

运行时在角色ID改变时取消为 `character_changed`，确认离开游戏时取消为 `left_game`，执行期限到达时为 `time_limit`；外部取消原因由调用方提供。场景代次变化会暂停当次调度，不会单凭换图自动取消脚本，脚本应决定是否允许转场并核对目的地。`ready=false` 或 HP 为 0 时由脚本主动检查前提；原生层可能先释放控制，后续动作按前提不满足报错。

任务级结束或取消只释放自己仍拥有的控制；会话结束、错误或外部取消先停止全部任务，等待原生释放确认后才发布会话终态。主机 CLI 另核对请求/实例身份和新鲜采样；控制释放无法确认时可能返回 `bridge_release_unconfirmed`。脚本只作用于所属实例，重连与重放由调用方决定。

## 日志与预算

- `game.log`单条最多4096字节，每次协程恢复期间累计最多65536字节，都按字符串字节数计算。每次恢复结束后日志批量写入宿主的 `script-events.jsonl` 并清零累计；日志只记录过程，游戏效果另行确认。
- 子任务日志自动带 `[任务名] ` 前缀，`main` 日志保留原文，便于定位独立任务的实际推进。
- 每项任务大约每50000条Lua VM指令让出一次，其他可运行任务与游戏更新继续。若在不能让出的原生调用中耗尽指令预算，会报错；正常控制循环仍按需要调用 `sleep`。
- 原生C函数的CPU与内存由受信脚本自身约束。使用 `game.time()`计算期限，`observed_at_ms`是Unix采样时间，二者不可相减。

## 策略文件入口与运行上下文

策略文件可在顶层声明固定 `main(context)` 入口。`script run/start FILE` 检查策略注释，在原生 Runtime 内先核对调用时的实例、角色、地图和场景代次，再调用入口；顶层代码用于声明策略和函数，控制逻辑写在入口内。入口只接收一个上下文表，基础状态和动作仍使用本文件前述的 `game.state()`、`game.observe()` 与动作 API。通用执行期限仍由 CLI `--seconds` / `--continuous` 控制；策略自有预算应使用独立的 `budget_seconds` 运行参数，避免与执行期限混淆。

运行参数用紧邻策略源码的 `@option` 注释声明。支持 `int`、`number`、`string`、`boolean` 四种类型；未标 `opt`、也没有 `default` 的非布尔参数必填。布尔参数始终可省略：未显式声明 `default` 时默认 `true`，显式 `default=false` 可覆盖该默认值。可选修饰符为 `default=值`、数值型 `min=值` / `max=值` 和 `choices=值1|值2`。默认值、正向布尔 flag 和显式值按声明校验；`--no-flag` 作为无值负向开关直接传入 `false`，不参与 `choices` 校验。

```lua
--- 按目标怪物 ID 观察当前场景。
-- @option[type=int,min=1] mob_id 目标怪物模板 ID
-- @option[type=int,opt,default=1001005] skill_id 可选技能 ID
-- @option[type=boolean] observe_only 仅观察；省略时默认 true
-- @option[type=boolean,default=false] attack_enabled 默认关闭攻击
local function main(context)
    local map_id = context.scene.map_id
    game.log("map=" .. tostring(map_id)
        .. ", mob=" .. tostring(context.options.mob_id)
        .. ", observe_only=" .. tostring(context.options.observe_only)
        .. ", attack_enabled=" .. tostring(context.options.attack_enabled))
end
```

CLI 参数名把 Lua 下划线转为连字符，例如 `mob_id` 使用 `--mob-id 1001001`。布尔选项可用裸 `--flag` 与 `--no-flag` 分别传入 `true`、`false`，也可显式写成 `--flag true|false`。省略布尔选项时，`context.options` 收到声明的默认值；未显式声明时收到 `true`，`default=false` 时收到 `false`。`choices` 校验默认值、正向 flag 和显式值；`--no-flag` 不会因 `choices` 未列出 `false` 而拒绝。其他可选参数仅在实际提供或声明默认值时出现在 `context.options` 中。`script describe FILE` 根据注释输出每项参数的类型、必填状态、有效默认值、范围、候选值和调用用法。

`context.scene` 绑定 CLI 装载前观察到的当前场景，包含只读身份锚点 `instance_id`、`character_id`、`map_id`、`scene_generation` 与静态 `terrain`。地形可用时，`terrain.status` 为 `available`，并提供来源路径 `source`、`footholds` 和 `ropes`；`footholds` 中 `x1 == x2` 的条目是竖直墙段（`y1`/`y2` 为上下端），其余是水平或倾斜地面，`prev`/`next` 是原始连接；数据不可用或当前地图只引用另一张地图时，状态分别为 `unavailable` 或 `unsupported`，并提供错误代码、说明和来源详情，不提供空地形或借用地图的坐标。策略需要静态地形时，应先检查 `terrain.status`。身份字段由 CLI 创建，不能作为普通 `@option` 覆盖；动态 HP、位置、技能和库存等事实仍从当前 `game.state()` / `game.observe()` 读取。

通用入口调用前会重新读取 `game.state()`，并对比就绪状态及上述身份锚点；不匹配时以 `strategy_scene_context_stale` 结束，策略主体不会运行。策略入口内若再采样初始状态，也应在派发动作前与 `context.scene` 再核对一次，以覆盖预检与主体之间发生的场景变化；后续跨地图或可能换角色的操作仍按业务边界核对。静态数据读取或验证失败时，CLI 在发布脚本前报告错误。该上下文不会替代 `game.state()` / `game.observe()` 返回的动态事实。

没有顶层 `main(context)` 声明的 Lua 文件仍按原始 chunk 执行。`--code` 始终保留原始源码语义，不解析策略注释或注入入口上下文。

## Lua 环境

开放基础库及 `table/string/math/utf8`。可正常使用函数、表、条件、循环、`assert/error`等Lua语法和这些库。

未开放 `io/os/debug/package/coroutine`；不存在 `require` 或自建协程入口。基础库移除了 `dofile/loadfile/load/print/pcall/xpcall/setmetatable/getmetatable`。使用 `game.log`记录消息；错误会交回公共运行时，脚本不能用已移除的 `pcall/xpcall`包住动作后吞掉未知效果。

## 最小公共动作示例

```lua
local before = game.state()
assert(before.ready and before.character and before.character.hp > 0, "not_ready")
assert(before.position and before.map_id, "position_unknown")
local caps = game.capabilities()
assert(caps.move, "move_not_supported")

local result = game.move("right", 0.1)
if not result.dispatched then
    game.log(result.reason or "not_dispatched")
    return
end

local after = game.state()
if after.ready and after.instance_id == before.instance_id
    and after.character and after.character.id == before.character.id
    and after.map_id == before.map_id and after.position then
    game.log("dx=" .. tostring(after.position.x - before.position.x))
end
game.stop()
```

这里核对的是一次本地移动尝试与读数，不承诺一定移动。复杂状态判断与操作编排放复合策略；先查本API参考，再按真实场景迭代，不把示例参数或初步脚手架当作成熟打法。

实现核对入口：[Runtime.cpp](../shared/lua-runtime/Runtime.cpp)、[headless适配器](../headless/src/SharedLuaAdapter.cpp)、[原版适配器](../beidou-ijl15/ezorsia/AgentBridge.cpp)。

## 可选旅行函数库

`script run/start --library travel` 将公共旅行函数与消费者源码组成一个原生 Lua chunk，脚本内可使用局部表 `travel`。这不是新的 `game` 原生绑定；未显式装载时该表不存在。`--library island-supply` 还提供示例表 `island_supply`。两者不依赖 `require/loadfile`，不解释动作列表或 JSON 预设；地图资料与已知路段由普通 Lua 消费者明确提供，持续控制仍在客户端。

`travel.begin(spec)` 核对当前角色与合法起点并绑定当前实例、角色及场景，返回路线对象。`spec` 必须包含 `name`、`seconds`（1至600秒）、`start_map`、`start`、`destination_map`、`destination`，可选 `min_hp_ratio`（默认0.25，范围0至1）。地图必须已知，`999999999` 不能作为已知目的地。区域均为 `{min_x,max_x,min_y,max_y}`，缺失或非有限值在输入前拒绝。外层原生会话期限仍有效，不因函数库调用延长。

| 普通 Lua 函数 | 输入与结果 |
| --- | --- |
| `route:walk(x, y_tolerance?, label?)` | 在当前楼层对齐X，默认高度容差10；停止后再确认，换层、身份变化或无进展时停止 |
| `route:drop_to(edge_x, landing, label?)` | `edge_x`为已知出边点，`landing`为下层已知矩形区域；出边前有界推进，观察到下降后释放输入并等待实际进入落区，复采确认后再由后续步骤对齐门户 |
| `route:portal(x, y, target_map, label?)` | 对齐同层已知门户，发一次Up，等待同角色进入已知相邻地图；仅此阶段接受预期转场并更新场景绑定 |
| `route:finish()` | 停止输入，复采目标地图和区域；返回 `{arrived=true,stage="arrived",map_id=...,position=...}` |

`walk/drop_to/portal` 返回同一路线对象，可以在普通 Lua 函数中组合复用。到达以复采证据为准；受控失败抛出 `route_failed arrived=false stage=... reason=...`，终止脚本后续动作，并由 Runtime 释放所属输入。每段开始记录 `route_stage`，原生抛错、整会话取消或期限结束时结合该最近阶段与原始原因判断。控制被接管后，路线按最新状态重新规划；多任务调用者先按正常规则取得控制并重新观察。

首轮 `island_supply` 提供以下路线事实，其他地图或起点按各自资料处理：

| 调用 | 合法起点 | 目的地 |
| --- | --- | --- |
| `island_supply.to_town(options?)` | 地图50000东上层，X1100..1350、Y-95..-75 | 向东落到Y275门户层，进入1000000西入口区域X-90..-40、Y264..284 |
| `island_supply.to_field(options?)` | 地图1000000西入口区域X-100..20、Y264..284 | 返回50000东下层区域X1400..1440、Y265..285 |

可选 `options` 只设置总预算 `seconds` 与 `min_hp_ratio`；默认出发30秒、返回20秒，HP下限0.5。例子：

```lua
local outward = island_supply.to_town({seconds=30, min_hp_ratio=0.5})
assert(outward.arrived and outward.map_id == 1000000)
-- 真实补给/任务消费者可在此观察，再决定后续；买卖与交任务由对应命令完成。
local back = island_supply.to_field({seconds=20, min_hp_ratio=0.5})
assert(back.arrived and back.map_id == 50000)
```

两端位置与运动事实仍分别来自各自客户端；GUI `settled` 保持未知，区域复采字段单独命名。本示例上层东沿为X1389，下层地面连续到X1530；出边点1398和落区X1390..1500、Y270..280分别表达已知离边位置与保留边缘空间的下层区域，门户X1420仅在下层确认后对齐。函数库按原生惯性处理横移。固定地形坐标来自已核实同源Map资料与既有私有路线证据，现场通行以真实执行结果为准；更换资源或遇阻时需重新验证。正式双端试用结果与组件版本集中在 #44 / #122 的交付 PR，离线合同与真实试用分别记录。危险地图返回后继续按原有约定安全结束或关闭所属实例。
