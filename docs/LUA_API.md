# Lua 脚本 API

本文是编写脚本的优先参考，描述当前共享运行时实际提供的 `game` 接口。两端使用同一套字段、函数签名和结果模型，以 headless 的脚本契约为基准；可选能力与原生执行前提分别说明。

脚本组织、控制权与传输机制见 [CONTROL.md](CONTROL.md)，复合策略维护约定见 [shared/scripts/AGENTS.md](../shared/scripts/AGENTS.md)。修改公开 API 时同步维护本文；不要在记忆或策略目录再维护一份字段全集。

## 启动与基本约定

从项目根运行受信的 UTF-8 文本脚本：

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json script run /path/control.lua --seconds 20
# 需要持续执行时显式使用 --continuous
```

- 脚本源必须是 UTF-8 纯文本，原生装载上限为1 MiB，不接受预编译字节码。自定义 `script run` 默认30秒，`--seconds` 可设为 `0.001..4294967.295` 秒；`--continuous` 表示无总期限。项目复合策略包装的单独预算范围不应当作所有用户脚本的运行时上限。
- 每次脚本启动创建独立 Lua 状态，脚本返回、超时、错误或取消后由运行时释放控制。脚本结束不会关闭客户端容器。
- 自定义脚本没有自动提供的 `options` 全局变量。可以自行声明 `local options = {...}`；项目的复合能力由 CLI 装载器在脚本前注入 `local options`，不能把这些文件当作无参数用户脚本直接运行。
- `game.state()` 返回一次采样的 Lua 表拷贝；后续状态变化不会修改旧表。执行动作或等待后重新读取。连续读取可能得到同一 `seq`。
- 未知字段为 `nil`，在 Lua 表中等同于缺键。已知的 `false`、`0`、空表 `{}` 与未知不同；例如 `inventory == nil` 不能按没有物品处理。
- 所有 `seconds` 参数使用秒。可选参数省略或传 `nil` 时采用默认值；有效时间向上取整为毫秒，实际恢复受游戏更新、释放确认和调度影响，不保证精确墙钟时长。

## 函数总览

| 函数 | 参数与默认值 | 是否让出执行权 | 返回值 |
| --- | --- | --- | --- |
| `game.state()` | 无 | 否 | [状态表](#状态表) |
| `game.capabilities()` | 无 | 否 | [能力表](#能力表) |
| `game.time()` | 无 | 否 | 单调时间，单位秒 |
| `game.sleep(seconds)` | 默认 `0`，有限数且 `0 <= seconds <= 30` | 是，包括 `sleep(0)` | 无 |
| `game.move(direction, seconds)` | 方向 `left/right/up/down`；默认 `0.3`，有限数且 `0 < seconds <= 30` | 是，等待输入释放确认 | [动作结果](#动作结果) |
| `game.face(direction)` | 只接受 `left/right` | 是 | 动作结果 |
| `game.jump(seconds)` | 默认 `0.06`，有限数且 `0 < seconds <= 30` | 是，等待输入释放确认 | 动作结果 |
| `game.attack(seconds)` | 默认 `0.06`，有限数且 `0 < seconds <= 30` | 是，等待输入释放确认 | 动作结果 |
| `game.pickup(seconds)` | 默认 `0.06`，有限数且 `0 < seconds <= 30` | 是，等待输入释放确认 | 动作结果 |
| `game.use_item(item_id)` | 整数 `1..2147483647`；当前原生实现只接受普通 `200` 类药品 | 是 | 动作结果 |
| `game.stop()` | 无 | 是，等待释放确认 | 动作结果 |
| `game.log(text)` | 字符串，限制见[日志与预算](#日志与预算) | 否 | 无 |
| `game.keys(keys, seconds)` | 原版可选；默认租期 `0.1`，`0 < seconds <= 30` | 否 | 无 |
| `game.press(keys, seconds)` | 原版可选；默认 `0.06`，`0 < seconds <= 30` | 是，等待释放确认 | 动作结果 |
| `game.skill(skill_id)` | 原版可选；整数 `1..2147483647` | 否 | [技能结果](#原版直接技能) |

动作函数的等待范围是原生输入释放或该动作的本地执行边界，不是服务器效果确认。一次函数调用也不保证只发生一次原生重复输入、只攻击一个目标或只拾取一个物品。

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
| `raw_keys` | boolean | 是否实现 `keys/press`；当前 headless 为 `false`，原版为 `true` |
| `skill` | boolean | 是否实现直接技能；当前 headless 为 `false`，原版为 `true` |

能力只表示有实现，不保证当前角色、地图、装备、库存或动作状态允许执行。可选函数在两端均已注册；`if game.skill then ...` 不能用于判断支持，必须读取能力表。没有 `native_skill`、`skills` 等能力别名。

## 状态表

以下五个字段总是存在：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `instance_id` | string | 原生进程实例身份，用于发现实例变化 |
| `seq` | integer | 当前实例的采样序号，不是脚本步数 |
| `observed_at_ms` | integer | 采样的 Unix 时间戳，毫秒 |
| `scene_generation` | integer | 原生场景代次；同地图重新进入也可能变化 |
| `ready` | boolean | 地图、角色、位置等基础对象已就绪；不表示角色存活、动作允许或全部领域已知 |

其余字段在对应信息已知时提供，否则为 `nil`：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `map_id` | integer | 当前地图 ID |
| `character` | table | 角色属性，见下表 |
| `position` | table | `x/y` 为地图世界坐标数值，通常向右 x 增加、向下 y 增加；不是桌面像素位置 |
| `facing` | string | `Left` 或 `Right`，注意大小写与动作参数不同 |
| `settled` | boolean | 已知的本地物理/攻击收束状态；`nil` 表示未观察到该事实 |
| `monsters` | array | 当前客户端已知怪物，元素结构见下文 |
| `inventory` | array | 五类背包的已占用正槽；不含身上装备负槽 |
| `drops` | array | 当前客户端已知掉落，元素结构见下文 |

`settled` 在 headless 中依据不处于攻击、不移动，且在地面/攀爬/水下计算；原版目前保持未知。它不是服务器 ACK。字段已知程度可以因后端或过渡状态不同而不同。

Lua 状态不含 `in_game/inGame`、`backend`、频道、任务、NPC、金币总额、技能表、已装备列表，也不含主机桥 JSON 的 `command/script/held_keys/last_skill/action_result`。不要把 CLI 的快照或 `state.json` 字段直接当作 `game.state()` 字段；后端名用能力表读取。

### character

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `id`、`name` | integer、string | 角色 ID 与名字 |
| `level`、`job` | integer | 等级与职业 ID |
| `strength`、`dexterity`、`intelligence`、`luck` | integer | STR、DEX、INT、LUK |
| `hp`、`max_hp`、`mp`、`max_mp` | integer | 当前与最大 HP/MP |
| `ability_points`、`skill_points` | integer | 未分配 AP/SP |
| `experience` | integer | 当前客户端记录的经验值 |

属性字段仅在已知时出现。当前两端通常整组采集属性；脚本仍应核对自己需要的字段，尤其不能用 `ready` 代替 `hp > 0`。

### monsters 的元素

`object_id: integer`、`x/y: number`、`active: boolean`；已知时有 `template_id: integer` 与非空 `name: string`。

- `object_id` 是本次场景对象 ID，`template_id` 是怪物模板 ID，不可混用。
- `active` 来自本地模型，不等于服务器确认的 HP 或击杀。
- 没有怪物 `hp/max_hp` 字段，也没有通过任意 OID 强制命中的攻击接口。

### inventory 的元素

`inventory_type: integer`、`slot: integer`、`item_id: integer`，数量已知时有 `quantity: integer`。

`inventory_type` 当前为 `1=装备、2=消耗、3=设置、4=其他、5=现金`。一个物品可能占多个槽位，按 ID 求总量时合计各项；任何相关项数量未知时，不能把它按零处理。空槽不列出，身上装备负槽不属于这张表。

### drops 的元素

总有 `object_id: integer`、`x/y: number`；已知时有 `item_id: integer`、`money: integer`、`landed: boolean`。

原版可能提供金币金额；headless 当前没有金额数据，`money` 保持未知。`item_id == nil` 不能单独证明是金币，`landed == nil` 不能按已落地处理。掉落 OID 与物品模板 ID 也不可混用。

## 动作结果

`move/face/jump/attack/pickup/use_item/stop/press` 返回以下表：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `dispatched` | boolean | 本地动作或释放请求是否已派发；不等于游戏效果成功 |
| `control_released` | boolean | 原生控制是否已确认释放 |
| `settled` | boolean 或 nil | 本地动作/物理是否已收束，未知为 nil |
| `effect` | string | 当前为 `unknown`，不能据此认定命中、拾取或恢复 |
| `reason` | string 或 nil | 原生执行说明；例如 `native_action_dispatched`、`already_facing`、`native_attack_not_allowed`、`item_use_requested`、`control_released` |

原生暂不准入可以返回 `dispatched=false`，例如 headless 攻击尚未允许或原版已朝目标方向。它与抛出 Lua 错误不同。`reason` 是诊断信息，不是完整稳定的业务枚举；优先根据状态和结果事实决定下一步。

### 基础动作的边界

- `move` 是方向输入，不是“走到坐标”；`up/down` 按原生状态用于攀爬、门户等。没有独立的 `game.climb` 函数。坐标到达、绳梯目标和转场确认由复合策略实现。
- `face` 可能造成少量移动。共享层请求短动作，headless 直接设置方向，原版可能短按方向或已同向时无需派发；不能据此要求两端固定同样时长或位置完全不变。
- `jump/attack/pickup` 的可选时间是输入持续时间，不是完整动画时长。攻击、空中运动和惯性可能在释放输入后继续。
- `stop` 释放当前脚本控制后继续执行，不结束 Lua。结束脚本用 `return` 或自然运行完毕。其结果的 `dispatched=true` 表示释放请求，不表示向游戏服务器发出了动作。
- 不要在 `game.keys` 持键期间立即接另一个语义动作；先用 `game.stop()` 等待释放，再开始新的独立动作。

### 单次用药

`game.use_item(item_id)` 当前只接受 `item_id // 10000 == 200` 的普通 HP/MP 药品，且库存必须存在。原版还要求物品已绑定可用原生快捷键；没有绑定会报错，不自动修改键位。非200类食品或传送卷不属于这个共同接口，原版 GUI 的对应工作流另行处理。

共享层使用60毫秒动作请求，headless 可能立即进入原生释放阶段，原版按自己的输入消费确认；API不承诺固定等待60毫秒，更不等待药量与HP/MP恢复确认。重复用药、目标阈值与每次消耗确认由 `recovery/recover.lua` 负责。

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

除单字母大小写等价外，按上表精确匹配；没有 `Enter/Esc/PageUp/PageDown` 等别名。键名被识别后，当前客户端原生键映射仍须支持它，否则会报 `unsupported_native_key`。

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

每次 `keys` 完整替换期望集合并续租；集合未变化的键不会被重复抬起/按下。租期结束由原生宿主释放。函数不让出、无返回值，持续循环必须主动等待；不能连续忙循环而期待角色同步移动。`keys({})`发起释放但不等待确认。

### press：有界按住并等待释放

```lua
if game.capabilities().raw_keys then
    local result = game.press("Right", 0.2)
    -- 此处已等待控制释放，仍不能把它当作移动到达确认。
end
```

`press`让出直到原生释放确认，返回标准动作结果；它不识别宏表达式或 `Left+Alt:0.2` 这类文本。

## 原版直接技能

```lua
if game.capabilities().skill then
    local result = game.skill(1001004)
    game.log("native_result=" .. tostring(result.native_result))
end
```

返回值只有：

```text
{ native_result = integer, dispatched = true }
```

这里的 `dispatched=true` 表示已调用原生入口。`native_result=0` 表示原生本地拒绝，非零仍不能证明动画、MP消耗、命中或服务器效果。技能调用不让出，也不等待技能完成；持续/蓄力/特殊技能需要按实际原生行为另行验证。调用失败或后端不支持时抛错，没有标准动作结果的 `effect/settled/control_released` 字段。

## 错误、期限与生命周期

API 参数无效、后端能力缺失、原生状态或输入路线不可用时会抛出 Lua 错误；原生暂未派发的正常动作结果则可能仅返回 `dispatched=false`。

| 类别 | 常见信息与处理方式 |
| --- | --- |
| 参数错误 | 方向、时长、整数ID、键表或键名不合法；修正调用，不盲重放 |
| 能力不支持 | `unsupported: raw_keys/skill/...`；执行前检查能力，不用“函数存在”判断 |
| 原生前提不满足 | 如 `state_unavailable_or_dead`、`action_in_progress`、`item_not_in_inventory`、`inventory_unavailable`；重新观察真实状态与已发生效果 |
| 脚本执行错误 | API错误或 `assert/error` 导致脚本进入 `script_error`，保留错误文本并释放控制 |
| 日志失败 | 超限会抛错；宿主写日志失败则取消为 `script_log_write_failed` |

运行时在角色ID改变时取消为 `character_changed`，确认离开游戏时取消为 `left_game`，执行期限到达时为 `time_limit`；外部取消原因由调用方提供。场景代次变化会暂停当次调度，不会单凭换图自动取消脚本，脚本应决定是否允许转场并核对目的地。`ready=false`或HP为0也不直接等同于运行时自动取消；原生层可能先释放控制，后续动作会因前提不满足报错，脚本仍需主动检查。

发生结束、错误或取消后，运行时先请求释放，等待原生确认后才发布终态。主机 CLI 另核对请求/实例身份和新鲜采样；控制释放无法确认时可能返回 `bridge_release_unconfirmed`。脚本没有自动重连或跨实例重放。

## 日志与预算

- `game.log`单条最多4096字节，每次协程恢复期间累计最多65536字节，均按字符串字节数而非字符数计算。每次恢复结束后日志批量写入宿主的 `script-events.jsonl` 并清零累计；日志不作为函数返回或游戏效果ACK。
- 运行时大约每50000条Lua VM指令让出一次，游戏更新继续。若在不能让出的原生调用中耗尽指令预算，会报错；不要依赖自动预算代替正常控制循环中的 `sleep`。
- 这不提供任意原生C函数的CPU或内存隔离，脚本必须受信。使用 `game.time()`计算期限，`observed_at_ms`是Unix采样时间，二者不可相减。

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
