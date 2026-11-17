# V17 其余运动规则与 headless 差异

本文是 [#250](https://github.com/Diluka/beidou-pilot/issues/250) 的调查交付：挖掘原版规则、保存可复核依据、记录 headless 后续调整项。普通地面/跳跃/空中规则继续以 [V17_MOTION_RULES.md](V17_MOTION_RULES.md) 为权威入口；本文覆盖其余状态、场地特例、实体与运动包，**本轮未调整 headless 实现**。

## 1. 版本、证据与阅读方式

- 调查日期：2026-11-16。源码对照基线：`main=7ee21cdfad4a71f7451f4013a6918298abfa88f6`。
- 原件：外部只读 `BeiDou.exe`，SHA256 `1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df`，PE i386，image base `0x400000`。地址均为原件 VA；本次涉及的 `.text/.rdata` 可用 `file offset=VA−0x400000` 取字节，其他节须按 PE 节表转换。
- **【观测·静态】** 是原件反汇编可确认的执行顺序/分支；**【源码事实】** 是当前适配器或 headless 的实现；**【观测·动态】** 指真实客户端记录；**【推导】** 是已确认公式的计算结果；**【未知】** 明确限制承诺范围。静态公式没有自动获得实际场景验证。
- `B/C/FA/FM/V` 的定义及单位沿用普通规则第1～3节：位置px、速度px/s、时间秒，duration另以毫秒记录。源码简称 `Character/`、`Gameplay/`、`Net/` 均相对 [`third_party/maplestory-client/`](../third_party/maplestory-client/)；GUI桥在 [`beidou-ijl15/ezorsia/`](../beidou-ijl15/ezorsia/)。
- 原始反汇编和只读解码产物保存在本机 `tmp/250-motion-rules/`，历史动态原始数据保持所属环境；这些目录不随文档分发。正文保留原件指纹、VA、字段、公式、源码符号和必要样本，使关键结论能从同版本原件复取。
- 当前范围是调查与记录。下表“后续调整”均未实施；已有 [#251～#259](https://github.com/Diluka/beidou-pilot/issues/250) 继续承担实现和验收，不以本文完成关闭这些任务。

| 任务 | 本轮已挖掘的规则 | 明确差异/后续入口 | 仍需补证 |
| --- | --- | --- | --- |
| [#251](https://github.com/Diluka/beidou-pilot/issues/251) | 攀爬3px/30ms、抓取查询、顶底退出、跳梯初速 | 8ms攀爬速率/边界/跳梯、GUI桥改参及速度字段适用性 | 绳梯类型门控、完整动作锁、场景覆盖 |
| [#252](https://github.com/Diluka/beidou-pilot/issues/252) | 冲量排队与脱地、方向合并/截断、±1500保护计数 | headless覆写速度且保留附着，保护时间2000ms | 普通触怪完整参数、死亡/复活、各状态真机 |
| [#253](https://github.com/Diluka/beidou-pilot/issues/253) | 90ms路径生成与30ms回放入口、专属边界和序号 | 8ms自主物理、非本控路径未消费 | 模式/属性、控制权、实际触怪和包效果 |
| [#254](https://github.com/Diluka/beidou-pilot/issues/254) | Flash Jump等级冲量、Teleport几何裁决/120ms待执行 | 对应移动分支空；Rush仍为本端自有模型 | Rush完整规则、技能准入和提交、技能场景 |
| [#255](https://github.com/Diluka/beidou-pilot/issues/255) | FA构造、模式/区域、材质驱动与陡坡滑行 | 地图材质未接入，多个坡度/驱动分支缺失 | 资源生产链、缓坡完整顺序、特例地图 |
| [#256](https://github.com/Diluka/beidou-pilot/issues/256) | 三类特殊空中参数选择、超限制动与横向递推 | 单一swim布尔、8ms固定阻尼 | 竖向输入设置者、进出状态和资源键 |
| [#257](https://github.com/Diluka/beidou-pilot/issues/257) | 有向单侧碰撞、承托/反向面响应入口 | 仅向下落地扫掠缺上升反向面接触 | 完整顶头响应、动态平台生产者及携带规则 |
| [#258](https://github.com/Diluka/beidou-pilot/issues/258) | Drop分段显示/锚点/出池、bullet时间窗、远端路径 | 坐标参考点、生命周期和丢段/跳位不同 | Drop时长生产者、bullet完整插值及集合覆盖 |
| [#259](https://github.com/Diluka/beidou-pilot/issues/259) | command布局、速度/时长、nibble输入、包围盒、批量与追赶 | 上一坐标/固定duration、解析长度、序号/附加域 | 各command触发、强制flush、控制权及无拉回 |

<a id="climb"></a>

## 2. 攀爬、绳索与跳梯（#251）

本节基于原件 SHA256 `1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df` 的只读反汇编，headless 对照基线为 `7ee21cd`。本节先记录静态规则及其推导；本轮补充的GUI攀爬、松键和端点实测见第11节。headless对齐尚未实施，双端验收未通过。

**原版规则**

- 【观测·静态】`CVecCtrlUser` 更新 `0x9CBEFB` 先从按键合成横纵输入（左右、上下分别相减，`0x9CBFFF–0x9CC05A`），经 `0x9B7B4A` 写入输入状态。`ZtlSecure(V+0x124)` 为非零绳梯关联时，在 `0x9CC0F7` 转入专门的 `0x9CC627`，绕过普通地面/空中积分 `0x9B19D0`。
- 【观测·静态】攀爬分支处理待执行跳跃/冲量请求后重新检查绳梯关联（`0x9CC634–0x9CC6C6`）；仍附着时，只做 `y += inputY * K`（`0x9CC6CC–0x9CC70E`），`inputY=ZtlSecure(V+0x15C)`，原件 `K=double[0xAF3728]=3.0`。末尾 `0x9CC7DA` 固定以 30 调用状态收尾槽 `vtable+0x18`。这里没有质量、重力、加速或梯形积分。
- 【推导】原件正常攀爬每 30ms 为上/下 3px，等价速率 100px/s；上下同时按或均松开时合成输入为 0，位置保持。
- 【观测·静态】顶底退出不对称。上行后 `y<ladder+0x10` 时，若 `ladder+0x08!=0`，设 `y=top−5` 并调用 setter `vtable+0x14(0,0,0)` 解绑；该标志为零则钳到 top 并保持附着（`0x9CC727–0x9CC779`）。下行后 `y>ladder+0x14` 时，设 `y=bottom+1` 并解绑（`0x9CC77B–0x9CC7D5`）。`ladder+0x08` 的资源键名尚未逐指令闭环，不把它直接称为梯/绳类型。
- 【观测·静态】跳梯走 `0x9B1D3D`：已有关联而横向输入为零时返回，不脱梯；非零时先清附着，再写 `vy=−jumpSpeed*C[+0x48]/FA[+0x24]*(special?0.3:0.5)`、`vx=inputX*C[+0x24]*walkSpeed*1.3`（`0x9B1D6E–0x9B1E3E`）。`special=0x9B214A` 的三个条件是飞行槽、区域谓词 `0x7046AC`、角色 `C[+0x78]>0`。普通倍率、SPEED/JUMP=100 时，初始 `vx=±162.5px/s,vy=−277.5px/s`；特殊条件下纵向为 −166.5px/s。这些是分支写入值，不能直接当下一物理步末态。
- 【观测·静态】抓梯不是只看当前点。查询 `0xA45B03` 把起终点 x 区间向两侧各扩 10，再和各绳梯 `[top,bottom]` 的 y 区间求交，返回遍历中首个命中（`0xA45B03–0xA45B89`）。`0x9CBEFB` 的空中上抓路径还检查 `vy>0`、向上输入、动作准入，用前后物理位置作查询，命中后清 vx/vy 并把 x 对齐绳梯轴；地面上抓查询 y 向上 20 的区间，地面向下抓查询向下 10 并要求 top 落在该区间（`0x9CC130–0x9CC61A`）。完整输入锁与所有抓取门控仍需真机核对。

**带桥 GUI 基准需要单独记录**

- 【源码事实】当前 `beidou-ijl15/ezorsia/Client.cpp:Client::JumpCap` 经 `dllmain.cpp` 无条件调用，将原件 `0x9CC6F9` 的常量指针改为桥自有 `0xC1CF80`，因此原件哈希不能独自确定实际 GUI 攀爬速度。`climbSpeedAuto=false` 时写 `3.0*climbSpeed`；开启 auto 时由 `codecaves.h:calcClimbSpeed` 写 `3.0*clamp(SPEED,80,speedMovementCap)*max(climbSpeed,1.0)/100`。配置缺省为 auto=false、climbSpeed=1.0，才与原件 3px/30ms 一致。本轮实测读取到 auto=false、climbSpeed=1.0，位移符合3px/30ms（第11节）；后续双端比较仍须记录实际桥工件和这两个选项，不能仅凭EXE哈希归因。
- 【源码事实/静态限制】原版攀爬分支直接写 y，未同步写普通 `V+0x50/+0x68` 世界速度；抓梯路径将这两个字段归零。现有 GUI `NativeMotion.cpp:Velocity/CapturePhysics` 总是解码这两个字段，不能仅凭解码成功就宣称取得了攀爬位移对应的瞬时速度；本轮实测已得到“每步上移3px但vy始终为0”的记录（第11节）。需要先修正攀爬速度事实的读取/已知性，再用于逐步验收。

**headless 差异与后续调整**

| 项目 | 当前源码事实 | 后续调整/补证 |
| --- | --- | --- |
| 步长与速率 | `Character/Player.cpp:motion_mode/legacy_update_8ms` 把 LADDER/ROPE 交给 8ms；`PlayerClimbState::update` 写 `±SPEED/100` px/步，SPEED=100 时为125px/s | 攀爬改按原版30ms提交和实际GUI基准系数；缺省100与125px/s已有明确差异，不能只做单位换算 |
| 输入与跳梯 | `PlayerClimbState::update` 用左右任一键判断跳梯；双方向同时按时也可能跳，横向速度用 `get_walkforce()*8`，纵向 `−get_jumpforce()/1.5`，SPEED/JUMP=100时为约±160、−375px/s | 对齐合成方向、无方向不跳、原版1.3倍横向与0.5/0.3纵向，按30ms消费跳跃请求并明确交接首步 |
| 顶底退出 | `MapInfo.cpp:Ladder::felloff` 使用 y±5 提前退出，不读取原版顶端+8标志；退出后 `PlayerClimbState::cancel_ladder` 固定设置1000ms攀爬冷却 | 读取并确认顶端标志与边界语义，分别实现top−5、top钳位和bottom+1；1000ms冷却的原版依据尚缺 |
| 抓取 | `Stage::check_ladders` → `Ladder::inrange` 只看当前整数位置横向±10和y±5 | 对照原版前后位置查询、地面上下区间、空中下降与动作门控，验证高速穿越绳梯轴和端点 |
| 绳/梯差异 | headless 读取 `l` 选择 ROPE/LADDER动作，积分相同；原版已见专用关联对象与顶端标志 | 先核实原版类型与顶端标志的各自消费者；本轮不能宣称绳与梯所有状态完全相同 |
| 观察 | `headless/src/PlayerPhysicsPose.h` 对legacy攀爬保留8ms位姿且速度未知；GUI普通速度字段存在上述适用性限制 | 补可判断的攀爬末态、附着身份和速度语义，再比较抓取/移动/松键/端点/跳梯；未知不补零 |

### 2.1 #251 已落地的 headless 实现（本轮）

- **30ms 攀爬步**：`Gameplay/Physics/V17ClimbMotion.{h,cpp}` 实现原版附着分支（0x9CC627）：每 30ms `y += inputY*3.0`，无重力/加速/梯形积分；顶底退出与跳梯按 §2 规则；`Character/Player.cpp::advance_local_motion` 新增 `MotionMode::CLIMB`（仅附着时；无附着的 LADDER/ROPE 人工状态保留 legacy 兜底）。攀爬提交推进真实 `motionCommitId`/`step_ms=30`。
- **抓取查询**：`Gameplay/MapleMap/MapInfo` 的 `Ladder` 增加 `top/bottom/exits_at_top` 与 `findladder(start,end)`（0xA45B03 的 x 两侧各扩 10、y 区间与 `[top,bottom]` 求交、首个命中）；`Gameplay/Stage.cpp::check_ladders` 按原版路径分别查询地面向上（y−20）、地面向下（y+10 且要求 top 落在区间）和空中向上（`vy>0`，用上一提交起点到当前物理位置）。
- **跳梯**：附着且 pending jump 时，横向输入非零才脱梯，写入 `vx=input*speedRatio*walkSpeed*1.3`、`vy=−jumpSpeed*jumpRatio/fieldGravity*0.5`（普通 profile），并在同一步走普通空中积分；横向为零时丢弃请求、保持附着。`PlayerClimbState::send_action` 记录 jump 边沿。
- **观察**：GUI 桥 `NativeMotion.cpp::CapturePhysics` 读取绳梯关联（`V+0x124` 的 `ZtlSecure<int>`，0x9CC0F5），附着时速度保持未知而不是把抓梯清零后的世界速度字段发布为已知 0；headless 攀爬的速度同样未知，位置/`update_id`/`step_ms` 可比。文档同步见 `LUA_TICK_API.md`、`TICK_FREQUENCY.md`。
- **跳梯两段式与观察语义（双端真机补充）**：原版跳梯的解绑更新只写入 `vx/vy` 并结束，该 30ms 步位置不变；下一次更新才做空中积分。GUI 实测写入样本 `(x=975,y=345,vx=162.5,vy=-277.5)`，下一步 `(979.875,337.575,vy=-217.5)`；headless 已按此修正（`V17NormalMotion::CommitExternalWrite` 发布写入样本，下一普通提交积分），双端写入值、积分、落地一致。唯一可见差异是 GUI 首个积分步不衰减 vx 而当前 headless 空气模型衰减 0.03px/s（累计约 0.0005px，门槛内）。因此 `character.physics` 的单个 30ms 样本可能表示“纯写入态”（速度已知、位置未积分），消费方按普通 update 对齐即可，不把它当位置异常。
- **仍未闭环**：`uf=0` 顶端 clamp 分支的直接真机实测尚未取得（当前可安全到达的测试地图只有 `uf=1` 资源），该分支不作为已验证行为；攀爬冷却/完整动作锁/绳梯类型语义同样未取证。
- **仍未闭环**：`+0x08` 顶端标志的资源字段映射是推导（`l` 已被实测排除、`page` 恒非零、`uf` 是唯一含零候选；尚缺 uf=0 顶端的直接 GUI 实测，clamp 分支不作为已验证行为）；攀爬冷却、完整动作锁与绳/梯类型语义未取证；特殊 profile 的 0.3 纵向系数与 fly/G4 门控属 #254/#256；本轮只有离线合同，双端真机比较待后续提交验证。

本地证据：`tmp/250-motion-rules/raw/user-frame.txt`、`climb-dynamics.txt`、`ladder-query.txt`，跳梯引用既有 `tmp/237-params/raw/asm-jump-alt-0x9B1D3D.txt`。本节保留了原件VA、常量和公式，不依赖临时文件长期存在。

<a id="hurt"></a>

## 3. 受击、击退与死亡/复活（#252）

取证范围：本轮只读校验原件 SHA256 `1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df`，用 GNU objdump 对下述 VA 反汇编，并对照 `main=7ee21cd` 源码；没有运行受击、死亡或复活试验。这里的静态事实可以指导下一轮补证与调整，不能代替两端真机验收。

**原版已确认的冲量处理规则**

- 【观测·静态】原版通过 `0x7A6353` 向 VecCtrl 排队冲量：清 `V+0x17C` 跳跃标志，置 `V+0x188=1`；若原先没有待处理冲量，先清零 `V+0x190/+0x198`，再分别合并 x/y 分量。多个调用在同一物理步前共享这两个暂存值，冲量不会立即改世界速度。
- 【观测·静态】`CVecCtrl::Update(0x9B19D0)` 在分派地面/空中积分前，若 `V+0x188!=0`，调用 `0x9B222A`。后者读取暂存双精度冲量、清待处理标志，已有 foothold 时先调用 `0x9B44C3` 脱地；未附着 foothold 而存在绳梯关联（`ZtlSecure(V+0x124)` 非零）时，调用状态 setter `vtable+0x14(0,0,0)` 清关联。之后才合并世界 `vx/vy`。因此原版冲量消费包括附着状态转换，不能只覆写两个速度字段。
- 【观测·静态】队列合并和实际速度合并都使用有方向的限幅规则。记当前分量为 `v`、新冲量分量为 `d`，则：`d<0 && v>d → max(d,v+d)`；`d>0 && v<d → min(d,v+d)`；其余保留 `v`。它既不是一律相加，也不是一律把速度替换为 `d`。例如 `v=125,d=-200 → -75`，`v=-300,d=-200 → -300`。实际合并的 x/y 最后都调用 `0xA62018` 向零截断为整数，再写回 double；该 helper 以 x87 控制字 `RC=11` 执行 `fistp`，随后恢复原控制字。
- 【观测·静态】`0x9581A9` 是本地角色 vtable `0xB3D1F4+0x60` 的处理函数；它包含怪物来源、伤害、概率抗击退和动作状态分支，末段 `0x9591CA–0x9591F6` 在计算所得 x/y 冲量不全为零时调用同一 `0x7A6353`。该函数中 `0x9589A7` 把常规候选幅值设为 200，`0x958C94–0x958CC7` 按方向参数与 `INT_MAX` 特例产生 ±幅值和 0/−幅值；另有 900/1900 的特例（`0x958B64–0x958B73`）及概率抗击退分支。**200 只说明已定位候选分支，尚不能归纳所有普通触怪都恒为 `(±200,-200)`**；尚需真实调用参数与实际命中路径核验。

**受击保护计数与动作事实**

- 【观测·静态】同一处理函数在正伤害路径写本地角色安全整数 `CUser+0x1EB8=1500`（`0x95921D–0x959227`）；非正伤害路径写 −1500（`0x959205–0x959213`）。`0x9324E7–0x932559` 每轮把正数减 30、负数加 30并夹回零；`0x9581C8–0x9581D5` 在特定参数开启时以该值非零阻止重复处理，触怪相关外层 `0x94B30B–0x94B318` 也以非零跳过后续流程。该值还控制闪烁（`0x93256B–0x93258F`）。这是以 30ms 步推进的正负保护计数，静态上 1500 对应 50 步；保护判定与所有攻击类型之间的覆盖关系仍待动态核验。
- 【未知】受击期间哪些方向/跳跃/技能输入被锁、空中/绳梯/特殊状态对冲量的完整门控、普通触怪参数来源、服务端修正与客户端预测的关系，尚未闭环。没有证据把“所有受击后禁止输入 N 毫秒”写成规则。
- 【未知】死亡触发、死亡期间物理行为、复活请求与服务端落点，以及重定位后的原版速度/输入清理顺序尚未专项取证；不得把换图重定位实现等同于已对齐死亡复活。

**headless 当前差异与后续调整**

| 项目 | 当前源码事实（`main=7ee21cd`） | 后续调整/补证项 |
| --- | --- | --- |
| 受击冲量来源 | `Character/Player.cpp:Player::damage` 在非 miss、非绳梯/死亡、抗击退概率允许时写 `(±187.5,-437.5)` px/s；数值由旧 `±1.5px/8ms、-3.5px/8ms` 换算，原版依据尚缺 | 先确认普通触怪调用参数和幅值分支，再替换冲量来源；不把换算值认作原版常量 |
| 合并与脱地 | `Gameplay/Physics/V17NormalMotion.cpp:ApplyImpulse` 直接覆写 vx/vy，保留 `onGround/footholdId`，也没有原版的待处理冲量与整数截断 | 对齐排队/消费相位、有方向的合并、脱地/脱绳梯、向零截断；地面击退尤其需补验 |
| 地面冲量的下一步 | `Step` 仍依 `state.onGround` 分派；`StepGround` 在平地以切向速度生成 `next.vy=0`（`next.vy=tangentSpeed*sin`），不同于原版冲量先脱地进入空中积分 | 记录为实际状态差异；真机比较地面受击的首个离地步、初速度与落地事件。本轮不修改 |
| 实际时钟 | 普通状态中的受击已经写入 V17 规范状态并继续 30ms 普通积分；非普通所有者才走旧 `phobj` 分支 | 纠正旧审计“受击后一律旧 Journey 重力/8ms”的表述；当前问题集中在规则与附着转换，并非普通路径仍用旧时钟 |
| 保护时间 | `Character/Char.cpp:show_damage` 对任何显示伤害写 `invincible.set_for(2000)`，按 8ms 世界时间推进；原版已定位的是正负 1500、每次趋零30的计数 | 补齐 miss/正伤害/特殊攻击的对应关系后，按已确认原版保护计数及作用域调整 |
| 死亡观察与复位 | `SharedLuaAdapter` 的 `dead/reviveRequestable` 仍为未知；`Stage::respawn` 由 portal 坐标求下方地面，`Player::respawn` 清速度规范状态、按键、held item、攻击与梯子关联 | 继续保留未知；分别取证死亡事件、复活包、落点与运动不连续清理，不以当前 respawn 函数名代替事实 |

### 3.1 #252 已落地实现（本轮）

- **冲量管线**：`Gameplay/Physics/V17NormalMotion.{h,cpp}` 增加 `QueueImpulse`/`HasPendingImpulse`：排队时清待消费跳键、按原版有方向限幅规则累积；下一个普通 30ms 提交在分派积分前消费——先脱地（清 foothold/地面），再以同一有方向限幅规则合并进世界速度并**向零截断**（对应 0xA62018 RC=11），随后同一步进入空中积分。`Reset` 清空待处理冲量，避免重定位后补发旧冲量。
- **受击接入**：`Character/Player.cpp::damage` 的普通规范状态路径由“直接覆写 vx/vy”改为 `QueueImpulse`；非普通所有者仍保留 legacy 写 phobj 路径。
- **普通触怪幅值（真机取证）**：GUI 真实角色 CID7（10级）在地图 `101040000` 被普通怪 `0130100` 连续触怪 6 次（伤害 2–8），按 `character.physics` 逐 30ms 样本反推：排队冲量取 `(±270, −270)px/s`——首样本 vx 与“原速度按方向限幅后截断+空气步微衰减”全部吻合（如原速 −125 遇 +270 → +145，观测 +144.97；vy 观测 −210 = −270+60）；方向由怪物相对角色位置决定。原静态候选 200/900/1900 在本路径未命中，当前实现改用 270。
- **保护时间**：`Character/Char.cpp::show_damage` 的受击保护从旧 Journey 2000ms 改为 1500ms：原版正伤害路径写 `+1500` 保护计数、每 30ms 步减 30（50 步=1500ms）。真机 6 次连续触怪恰好每隔 **50 个 30ms 提交（1500ms）** 再次生效，动态印证该计数与时长；miss/特殊攻击的正负计数覆盖关系仍未闭环。
- **合同**：`v17_normal_motion_contract.cpp` 新增 `hurt-impulse` 场景（脱地+截断+空中积分、方向限幅只抵消到零、较大同向速度不被削弱、连续同向冲量不叠加）；离线全套 527 tests 通过。
- **双端真机**（2026-11-17，常驻服角色 CID7）：GUI 地图 `101040000` 普通怪 `0130100` 6 次触怪、headless 地图 `106000000` 普通怪 `1130100` 2 次触怪，按 `character.physics` 逐 30ms 样本反推：冲量均为 `(±270,−270)px/s`；如原速 −125 遇 +270 → +145（观测 144.97），原速 +125 遇 −270 → −145（headless 观测 −144.97），vy 首样本均为 −210（−270+60）；方向随怪物相对位置变化。保护计数：GUI 连续触怪间隔恰为 50 个 30ms 提交（1500ms），headless 为 51 个提交（保护 50 步 + 1 步判定相位），动态一致。
- **死亡/复活观察（附带取得，未对齐）**：hp 归零后 headless `dead=true`、移动意图返回 `state_unavailable_or_dead`、后续 30ms 提交位置冻结；GUI 死亡态 `dead/revive_requestable` 字段仍未知，`revive` 命令返回 `status=revived, changed=true`，两次均复活到同地图固定复活点（`(2581,567)`/`(2385,-71)`），位置/速度重置，HP=50（max169）而非满血。复活 HP 公式、死亡过程逐物理步轨迹与 GUI 死亡观察语义尚未取证，死亡/复活运动对齐仍留在 #252。
- **仍未闭环**：miss/特殊攻击的正负保护计数覆盖关系、受击期间输入锁、空中/绳梯/特殊状态门控、服务端修正与客户端预测关系、死亡/复活运动；这些继续由 #252 补证。

本地原始证据：`tmp/250-motion-rules/impulse-queue.asm`、`impulse-consume.asm`、`hit-terminal.asm`、`hit-counter.asm`、`hit-early-guard.asm`、`cast-trunc.asm`、`damage-impulse-branch.asm`；全量只读反汇编 `beidou.asm` 可检索调用者。VA 与公式已保留在本节，复核不依赖临时文件长期存在。后续最小验证应覆盖地面/空中受击、同向/反向已有速度、miss/正伤害、绳梯门控与保护计数终点；本节未进行受击、死亡或复活的真实游戏操作。



<a id="mob"></a>

## 4. 怪物运动与 MoveMob（#253）

本节为原件静态规则与 `main=7ee21cd` 源码对照，未进行怪物真机轨迹或网络验收。原件 SHA256 为 `1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df`。VA 均针对该原件。

### 已挖掘的原版规则

1. **【观测·静态】怪物生成路径的物理步参数是 90ms，当前路径每30ms调用回放，内部按缓冲推进30/33ms。两者用途不同。** Mob 主 CVecCtrl 由 `mob+0x118` 的 COM 接口减 `0xC` 获得，主 vtable 为 `0xB3E678`。其 `+0x24` 槽 `0x9BBC89` 调用共同状态准备 `0x9B195F` 后返回 `0x5A=90`；共同派发 `0x9B1928` 在 `0x9B192E` 调该槽，把返回值传给 `+0x28` 的 `0x9BCA2A`（`0x9B194A–0x9B194D`），后者再于 `0x9BCAF7` 传给共同物理函数 `0x9B19D0`。`0x66BBB8–0x66BC01` 可见生成路径的有界循环：检查路径条件 `0x68A828`，未满足时执行该派发，最多 55 次。另一方面，Mob Update 在 `0x6684E8` 调 `0x9B16E8`，后者以固定 30 传给路径回放槽 `+0x34=0x9B1719`，执行 `0x68ADCC`，回写当前 x/y/vx/vy。**不能把玩家的固定30ms物理步、怪物的90ms生成步、怪物当前路径回放混写成一个频率；内部播放的30/33ms追赶见第10节。** 实际重算/发包时刻与运行样本间隔仍需动态闭环。
2. **【观测·静态】物理积分复用共同核心，行为选择和边界处理有怪物专属分支。** `0x9BCA92–0x9BCACE` 按 `V+0x248` 数值 0/1/2/3 分派 `0x9BCB02 / 0x9BCCAF / 0x9BCF48 / (0x9BD487,0x9BD799)`，然后进入共同 `0x9B19D0`。共同核心先按 `V+0x110` 是否附着 foothold 选择 ground `0x9B23F2` 或 air `0x9B2C3C`；碰撞/边界的虚槽 `+0x0C/+0x10` 则分别是 Mob override `0x9BDCB1/0x9BE14F`，并非 User 的 base 实现。数值模式与怪物动作/能力的完整命名尚未闭环，不将它们等同 headless 的控制器 mode。
3. **【观测·静态】边界不是统一“碰到边缘翻转”。** `0x9BDCB1` 的模式 1 分支检查运动方向、相邻 foothold `+0x4C/+0x50` 及其 cos；模式 2 会把当前 foothold 与 `V+0x24C` 指定范围求交，交集宽度超过 40 时左右各缩 20（`0x9BDE53–0x9BDE66`），再根据方向/相邻坡面/目标与区间裁决保持附着、修正切向位置或脱离。air override `0x9BE14F` 的模式 2 同样用该交集及 20px 内缩，超过左右边界时直接回写当前 x，必要时改方向（`0x9BE1BA–0x9BE249`）。该规则并不证明所有怪物都应受同一个 20px 边界；模式来源尚需闭环。
4. **【观测·静态】方向重算有原版分支自身的计数规则。** `0x9BCCAF` 无目标分支用 `(1000 + rng % 2000) / 90` 设置重算计数，并用 `rng % 3 - 1` 得到 -1/0/1 方向（`0x9BCEB5–0x9BCF0A`）；有目标分支另用 `(800 + rng % 400) / 90`（`0x9BCCF1–0x9BCD1F`）。这里只证明算式与调用位置，尚不承诺随机数分布、具体 AI 状态名或真实时间分布。随机选择无须逐次重现，但其作用于何种物理/包状态必须分别对齐。
5. **【观测·静态】出站 opcode 为 `0x00BC`，包头含递增序号及真实控制状态。** `0x66BC67` 构包 opcode `0xBC`；`0x66BC74–0x66BC90` 写 secure OID，`0x66BC95–0x66BCC2` 读取 `mob+0x13C` 的 secure 值、加 1、写回，并按 U16 写入包。后续写 2 个 U8、1 个 U32、另 1 个 U8、3 个 U32，再交给 `0x68A88D` 写路径；其中两个 U32 在分支关闭时写 `0x00FFDDCC`（`0x66BD28–0x66BD56`），不是恒零预留区。写入原语已核实：`0x406549`=U8、`0x427F74`=U16、`0x4065A6`=U32。位域含义、路径元素和服务器接受规则仍待逐字节对账。

### 与 headless 的确定差异及后续调整点

| 消费路径 | 当前 headless 实现 | 与原版证据的差异；后续调整记录 |
| --- | --- | --- |
| 运动与时钟 | `Gameplay/MapleMap/Mob.cpp::update` 每个世界 8ms update 调 `Physics::move_object`；`Physics.cpp` 使用旧 NORMAL/FLYING 算式 | 缺少原版90ms路径生成、每30ms调用回放及内部30/33ms追赶的层次。后续先取得同怪物样本和生成/回放时序，再确定本端持有者；不能只把 8 改 30 或 90。 |
| 地面/飞行参数 | `Mob::Mob` 地面 speed 已按动态证据改为 `(speed+100)*0.002`（`MobWalkSpeed.h`，2026-11-17 #265）；flySpeed 仍为 `(flySpeed+100)*0.0005`；跳跃施加 `vforce=-5`，受击 `hforce=±0.2/±0.1` | 地面基础速度已对齐（同图 3 模板 p50/p90 与原版比值 0.999）；飞行/追击/跳跃参数与 AI 暂停节奏尚无原版公式，继续保留 Journey 值并记录差异。 |
| 边界/掉边 | `TURNATEDGES` + `FootholdTree::update_fh/limit_movement`，清旗后翻转 | 缺少 Mob override 按模式、活动范围、目标、相邻 foothold 的裁决。后续按静态谓词和有代表性的怪物场景覆盖，普通角色 Sweep 不能直接代替该规则。 |
| AI 方向/动作 | `Mob::next_move` 随机漫游、25% 起跳；`update` 通常等待 `counter>200` 和动画结束；`aggro` 被赋值但没有后续读取 | 计数与目标分支结构不同。随机数不要求逐次一致；应先核实实际追击/触怪消费者所需行为，避免把随机 AI 也纳入逐样本相等承诺。 |
| 非控制怪物回放 | `Mob::send_movement` 先 `set_position(start)`，再保存完整 `movements`，仅读 `front()` 更新 stance/fhid；`update` 不消费保存队列，仍运行本地 Physics | 与原版推进路径并回写 x/y/vx/vy 的事实存在直接差异。后续需实现被消费的路径/时长语义，并区分控制权；单纯使用包首位置会丢失其余路径元素。 |
| MoveMob 出站 | `Mob::update_movement` 序号已改为每包递增 U16（2026-11-17 #264，GUI 观察端真机跟随通过）；其余字段仍为 0；`MoveMobPacket` 写入 13 个零；`Movement(phobj,...)` 固定单元素、duration=1 | 原版 U16 序号递增已对齐；13 字节区域含状态与条件哨兵及 ACK 语义仍未闭环，后续按原件编码/实际包对账。 |
| 控制权 | `set_control(mode)` 将 `mode>0` 视为 control、`mode==2` 视为 aggro；受控忽略收到的移动；`SpawnMobControllerHandler` 处理控制器包 | 本端已有控制器结构。原版控制权授予/回收、重算时机和 ACK 全链尚未闭环，不据此断言所有怪物永远由本地模拟。 |
| 观察/触怪 | 当前实体速度为各实体完整 native update 的派生平均值；触怪消费客户端怪物位置 | 先确定怪物路径推进事实和碰撞的同一步口径；不得把模板 speed 或 90ms 生成态直接作为屏幕当前速度。 |

### 受控怪物动态证据与已落地调整（2026-11-17）

- 同图 `102010000`，原版 GUI 控制器（CID6）与 headless 控制器（CID7，`controlled=true`）各 20 秒、10Hz 记录；按模板统计速度分布：
  - 木妖（130100）：原版 p50/p90 = 39.80/49.80 px/s，改动前 headless = 19.92/22.29 → 恰好 2.00 倍；
  - 红蜗牛（130101）：59.76/79.66 vs 29.89/39.81 → 2.00 倍；
  - 黑木妖（1110101）：39.80/49.80 vs 19.92/22.28 → 2.00 倍。
- 已落地：`MobWalkForceFromTemplate((raw+100)*0.002)` 用于地面怪物 hforce；改动后 headless 控制器 p50/p90 = 39.83/49.79、59.79/79.67、39.84/49.80（与原版比值均 0.999），`mob_walk_speed_contract` 覆盖映射值。
- 保留差异（未对齐）：headless 暂停比例约 0.21–0.23，原版约 0.30–0.36（AI 决策/暂停节奏不同）；飞行、追击、跳跃参数与边界 override、控制权授予/回收仍无原版证据。
- **AI 节奏动态证据（2026-11-17，同两份 20 秒记录）**：连续静止样本长度（100ms/样本）原版 p50 0.5s、p90 3.6s、max 9.0s（分布宽），headless 旧实现 p50=p90≈1.6s（固定 `counter > 200`×8ms，节奏僵硬）；每只怪方向变化次数原版约 5.3、headless 约 4.1；跳跃上升高度 p50 原版 14px/headless 12px、p90 58/59px（样本含坠落，未单独闭环）。
- **AI 决策节奏已落地（2026-11-17，#270）**：按 `(1000+rng%2000)/90` 的 11–33 步随机计数，30ms/步（动态速度段拟合 0.33–1.0s 决策间隔），每次决策后重抽；STAND 分支加入 1/3 保持（对应 `rng%3-1` 的一个保持结果），HIT/JUMP 阈值保留。真机 20Hz 速度段统计（29 只/20 秒）：
  - 站立段（原版 → 旧 headless → 新 headless）：n 134→175→159，p50 0.93s→~1.6s→0.75s，p90 3.65s→~1.6s→1.45s，max 10.6s→~1.6s→5.0s；
  - 移动段：p50 0.73s→~1.6s→1.00s，p90 2.70s→~1.6s→2.35s，max 9.05s→~1.6s→5.75s。
  - 剩余差异：原版站立段长尾更长，说明 `rng%3-1` 的保持/切换映射与计数单位仍未完全闭环；方向/飞行/追击/跳跃参数继续待证。
  - **60 秒复测与模型拟合（2026-11-17）**：GUI 原版站立段 n=372、p50 0.62s、p90 3.75s、max 12.45s，移动段 n=992、p50 0.85s、p90 2.95s。对几何保持模型做参数网格（决策间隔 [a,b] 秒、站立保持概率 q）并与 GUI 分位数比较：当前实现 [0.33,1.0]/q=1/3 的 p50/p90 分别约 0.8/1.8s；拟合较优参数约 [0.5,1.5]/q≈0.4（p90≈3.0s、max≈8s），但原版站立段 p50 仍明显更短、长尾更长，不是单一几何模型能解释；长站立分布横跨地图 x=-1207..2019，不支持“贴边卡住”单一解释。按“不猜”原则本轮不继续调参，保留为 #253 待闭环项（可能涉及原版 AI 更新时钟/保持映射或边界 override）。
- 证据：所属环境 `tmp/253-mob-evidence/phaseA-controller.jsonl`、`phaseB-headless-controller.jsonl`、`phaseB2-headless-doubled.jsonl`。

### 证据索引与剩余边界

- 已有来源：`tmp/tick-entity-motion/mob-vector-frame.txt`、`mob-vector-constructor.txt`、`mob-update-assembly.txt`、`derived-vector-dispatch-complete.json`；Mob Update 的 REA evidence 为 `ev_16c61895fafce2c30dab552148fd3473d6a082f42f98e044197c7270a233b184`。既有报告仅作地址导航，本轮对上述关键 VA 用原件 `objdump` 重新核实。
- 本轮保存：`tmp/250-motion-rules/raw/mob-clock-step.txt`、`local-dispatch-interval.txt`、`mob-plan-loop.txt`、`mob-replay-call.txt`、`mob-boundary-override.txt`、`mob-direction-decisions.txt`、`mob-packet-build.txt`。这些是本机原始证据索引，正式文档需保留 VA 与符号，避免只留下无法公开访问的临时链接。
- 【未知】模板属性→原版有效速度/跳跃/飞行参数、各模式完整含义、重算节奏与控制权切换、MoveMob 路径元素/ACK/服务器无拉回、真实触怪边界。本轮没有改headless，也没有用源码或静态反汇编声称这些怪物实际场景已经对齐。


<a id="skills"></a>

## 5. 移动技能（#254）

本轮已拆出“冲量技能”和“目标重定位”两类原生路径，不能用统一 rush 速度替代所有移动技能。下面只记录有地址级证据的分支，首批实现技能仍待结合实际消费者选定。

- 【观测·静态】Flash Jump `4111006` 从分派 `0x968110–0x968982` 进入 `0x96BE38`，在 `0x96BEF8` 与该技能ID比较；`0x96BF52` 要求没有 foothold，另有 `0x705343/0x705309/0x96C1D3/0x96C1AA` 门控。进入成功路径后记已使用标志 `CUser+0x2B58=1`。令 `q=trunc(skillLevel/4)`，在 `0x96BFE9–0x96C04D` 构造 `ix=±(350+40*q)`、`iy=−250−20*q`（符号由 `CUser+0x570` 面向位决定），再调用 `0x7A6353` 排队；这是交给后续物理步合并的冲量，不是立即把世界速度设成该值。这里的skillLevel是函数接收的等级参数；具体运行角色的等级与准入仍需动态核验。其他两个共用此函数的技能ID `11101005/14101004` 有各自门控/等级处理，不能直接套用冒险家公式。
- 【观测·静态】三个 Teleport ID `2101002/2201002/2301001` 经 `0x967C9B/0x967D7B/0x967E11` 分派到 `0x969146`，在 `0x969153` 调用 `0x957B74`。该函数读取技能等级项 `+0x19C` 安全整数作位移距离（`0x957D7A–0x957D9E`），按合成方向生成候选 x/y，再通过平台查找、上下可达落点与碰撞等分支裁决（`0x957DCC–0x958048`）。成功时将目标坐标写 `CUser+0x2B20/+0x2B24`，置 `+0x2B18=1`，保存当前时刻和 `now+120`（`0x958078–0x9580B7`）。所以它是有目标检查和待执行状态的重定位，不能概括为直接改x/y或固定距离冲量。具体提交目标的后续更新点、所有地图禁用分支和服务端结果仍待取证。
- 【源码事实】`Gameplay/Combat/Combat.cpp:apply_use_movement` 中三个Teleport和Flash Jump的case均为空；`apply_move` 的非攻击分支只应用效果/动作并发 `UseSkillPacket`，没有调用移动处理。当前源码不能支持“已会施法所以移动已实现”的结论。
- 【源码事实】当前 rush 仅三职业 `1121006/1221007/1321003` 进入 `Combat::apply_result_movement→apply_rush`：要求命中数非零，以最后目标怪物当前x为终点。`Player::rush` 仅落地允许；规范状态调用 `V17NormalMotion::BeginRush` 设 `vx=1000*(targetX−x)/attackDelay`，地面步期间不加行走力或制动，按墙/离地/越过目标结束并清速度（`V17NormalMotion::StepGround`）。这是当前headless模型，**本轮尚未完成对应原版rush公式、碰撞与结束条件的地址级闭环**，不能标为原版等价。

| 后续项 | 需要调整或补证的具体内容 |
| --- | --- |
【已落地调整（2026-11-17，#276）】Flash Jump `4111006` 已接入 headless：

- 静态公式（§5）：`q=trunc(level/4)`、`ix=±(350+40q)`、`iy=−250−20q`，经与受击相同的 `0x7A6353` 冲量队列合并；`MovementSkills.h` + `movement_skills_contract`。
- 门控（隔离服 GUI 原版动态确认）：等级>0、未使用过、离地、**按住左/右方向**（无方向输入时原生 `dispatched=false`）；`Player.flashJumpUsed` 落地/respawn 重置。
- 补齐 `Combat::apply_move` 非攻击分支调用 `apply_use_movement`（文档此前指出的缺口）。
- 双端真机（隔离服务器，同一 job412/4111006 lvl20 角色）：GUI 原版施放后第 2 个 30ms 提交 **vx=550、vy=−290**；headless 同场景逐提交一致（550 保持、vy −290/−230/−170/−110…）。隔离服务器测试后已 `down --volumes` 关闭并清理数据副本。

| 冲量交接 | 复用原版受击同一个排队/方向限幅/截断/附着转换规则，按技能门控接入；避免直接覆盖速度掩盖已有同向/反向运动 |
| Flash Jump | 核验已用标志的清除时机、门控函数含义、连续释放/落地重置、按等级的真实冲量；headless目前缺移动分支 |
| Teleport | 补目标候选、几何裁决、120ms待执行状态的后续提交与包语义，再实现目标重定位；headless目前缺移动分支 |
| Rush | 对照上述当前模型取证原版起始/目标/持续/墙边/平台边/无目标/中断，确定“命中最后怪物x”是否有依据 |
| 消费者与验收 | 从已授权角色技能与AI实际使用中选首批；每个技能分别记录施放受理、物理位移、结束、取消/换图和服务端修正，不能用其中一种成功代替其他项 |

本地证据：`tmp/250-motion-rules/raw/flash-jump.txt`、`teleport.txt`，共享冲量参考受击节中的 `0x7A6353/0x9B222A`。本轮没有施放技能或双端动态验收。


<a id="ground"></a>

## 6. 坡面、材质与区域谓词（#255）

以下结论为本轮对同一 SHA256 原件的静态核验；没有新增特例地图的 GUI 动态轨迹。证据保存在 `tmp/250-motion-rules/raw/ground-full.txt`、`ground-tail.txt`、`region-predicate.txt`、`secure-int-read.txt`、`region-point-query.txt`；它们可用 `objdump -d --start-address=VA --stop-address=VA` 从只读原件复取。

<a id="field-attributes"></a>

### 6.1 场地属性生产者（G1）

【观测·静态】本轮从 `0xA45B8C` 找到此前未定位的生产链：管理器分配0x54字节（`0xA45B9B–0xA45BA2`），调用 `0xA45C5B` 构造后在 `0xA45BC1` 写 `P+0xAC`。构造依次把四个受保护 double `FA+0/+0x0C/+0x18/+0x24` 初始化为1.0，`FA+0x30` 受保护整数初始化0，`FA+0x3C` 区域对象初始化（`0xA45C67–0xA45CC2`）。随后 `0x437A0C` 取得当前场地，`0xA45BD4/0xA45BEB` 等调用读取场地倍率并覆盖构造值；场地 `+0x158!=0` 时模式置1，否则 `+0x15C!=0` 时模式置2，场地 `+0x758` 区域数组经 `0x597FD7` 装入 `FA+0x3C`（`0xA45C03–0xA45C48`）。这使 G1 的“构造缺省/写入点未知”可以关闭；仍待追踪这些场地字段对应的 IMG 键与覆盖规则，不能把构造1.0当所有地图的最终值。证据为 `tmp/250-motion-rules/raw/ladder-query.txt`。

### 6.2 区域、材质与滑行

**G4 的可确认结构。**【观测·静态】`0x7046AC(V)` 先调用 `0x704710`：当 `FA=V+0x1A0` 非空，读取 `FA+0x30` 的受保护整数，值为 **1** 时为真；否则把当前未圆整物理 x/y 分别向零截断为整数，再用 `0x5983F4(FA+0x3C,x,y)` 查询区域。区域查询返回非零亦为真；FA 空或均不命中为假。`0x42873D` 的完整函数体（`0x42873D–0x4287DC`）逐字节解密一个 4 字节整数并校验，**不能解释为容器长度**。`0x5983F4–0x5985BB` 在两份坐标数组中查找 x/y，再访问二维占用矩阵，故可确认它是区域点查询；区域由哪些 IMG 节点生产、边界精确取舍与该模式的游戏名称仍未知。旧报告中“`FA+0x30` 容器取长度”的推断应撤回。

【观测·静态】G4 为真时，地面方向力乘 `swimSpeedDec=B[+0x88]`（`0x9B2565–0x9B257F`），基础限速也乘同一系数（`0x9B2664–0x9B267E`）。已知资源系数为 0.9；同一谓词会排除普通空中分支。仅凭参数命名尚不能把 G4 的所有命中统一称为水域。

**材质分支。** 设 `u∈{-1,0,1}` 为水平输入，`q=FM[+0x24]`，`m=abs(foothold.sin)`，`h=(foothold.sin<0 ? +1 : -1)`；对非水平坡，`h` 是向上坡的水平符号。以下力与速度均先在 foothold 切向坐标计算，最终仍使用梯形位置积分与世界投影。

| 规则 | 原版地址与静态结论 | 当前 headless 差异 |
| --- | --- | --- |
| 角色倍率选择 | `0x9B2497–0x9B24EE`：只有 `FM[+0x18]==1 && q==0` 使用 `C[+0x18]`；其他材质用 1。`0x9B2715–0x9B2744` 对摩擦角色倍率亦作相同选择：普通材质用 `C[+0x30]`，其他材质用 1。 | `V17NormalMotion::StepGround` 已处理行走力选择，摩擦仍统一用 `frictionRatio`。目前 `Player::motion_multipliers` 把该比率给成1，所以默认材质不会暴露此差异。 |
| 非零材质驱动力 | `0x9B2582–0x9B262B`：`q!=0` 且 `u==0` 时仍生成 `q*walkF`；`u!=0` 时，若 `u*q>0`，已算方向力乘 `2*abs(trunc(q))`；否则乘 `0.2/abs(trunc(q))`。整数转换为 `0xA62018` 向零截断，整数绝对值为 `0xA61A33`。这里记录原指令，不替资源生产者补“q 永为整数/非零截断值”等保证。 | 当前无输入统一减速至零；未实现该方向驱动力或 q 对行走力的调整。q 尚不能仅凭行为确认为传送带。 |
| 非零材质限速 | `0x9B2681–0x9B2712` 对限速使用相同的有输入倍率；无输入时乘 `abs(trunc(q))`。 | 当前限速只为 `walkSpeed*footholdSpeed*speedRatio`。 |
| 坡度方向力 | `0x9B262B–0x9B2655`：上述方向力再乘 `h>0 ? 1−m² : 1+m²`。原版基础限速辅助函数 `0x9B2187–0x9B21D9` 提供 `walkSpeed*FM[+0x0C]*C[+0x24]*(1+sin²*dirAdj)`；地面积分中调用时 `dirAdj=0`，之后自行计算坡度所用限值。 | 当前只以单位切向量投影速度，方向力和限速没有这些坡度分支。 |
| 摩擦 | `0x9B2744–0x9B2802`：按材质选择倍率后，计算 `FM[+0x18]*角色摩擦倍率*FA[+0x0C]`，夹到 `[minFriction,maxFriction]`，小于1再乘0.5。制动力为结果乘 `walkDrag`；为0时备用制动力为 `0.2*walkDrag`。 | 当前普通倍率下已有对应夹取和0.5规则；实际材质和场地值没有从地图送到运行时。 |

**陡坡滑行。**【观测·静态】`0x9B297A–0x9B298E` 比较 `C[+0x3C]` 与 `m`；`m>C[+0x3C]` 进入 `0x9B2A52` 的滑坡路径。构造缺省 `C[+0x3C]=0.9`（沿用既有构造证据），比较量是单位切向量 y 分量的绝对值，不能拿 `dy/dx` 直接比较0.9。

令 `Fdir` 为上表处理后的方向力，`Vbase` 为上述区域及材质处理后的基础限速。该分支依次计算：

```text
F = −h*m*slipForce
L = m*slipSpeed
if u*h > 0:                 # 输入向上坡
    F *= 0.5
    L *= 0.5
elif u != 0 or q != 0:
    F += Fdir
    L += max(0, (1+m²)*Vbase)
# 无输入且 q==0 时，保留纯滑坡力和限速
if h*v > 0:                 # 已有速度向上坡
    v 先按 brakeForce/mass*dt 向0制动，跨0归0
v = 原版0x9B2BCB(v,F,mass,L,dt)
position += (v_old+v)/2*dt
```

地址：力/限值 `0x9B2A52–0x9B2AD7`，上坡速度制动 `0x9B2AD7–0x9B2B3F`，力积分 `0x9B2B3F–0x9B2B62`，位置积分 `0x9B2B69–0x9B2B98`。`0x9B2BCB` 按力的符号限幅，已经超出该方向限值时不硬拉回；这一规则与普通运动相同。【推导】缺省参数下，`m=0.95`、无输入且普通材质时，纯滑坡加速度幅值为 `0.95*60000/100=570px/s²`，滑行限速为 `0.95*120=114px/s`；这是公式计算值，尚无该坡度的 GUI 动态核验。

【观测·静态】较缓坡的 `0x9B28DC–0x9B2A52` 也有方向相关限速、超限制动与摩擦为零时的滑坡力，并非“只有陡坡才使用 slipForce”。本轮确认摩擦为0时会把 `h*m*slipForce` 从方向力扣除（`0x9B2994–0x9B29B6`）。全部较缓坡执行顺序尚未做动态复算，保持待补证，不以陡坡伪代码代替完整地面模型。

**后续调整入口与阻止范围。** `third_party/maplestory-client/Gameplay/Physics/Foothold.cpp::Foothold` 目前只读坐标与 prev/next；`Character/Player.cpp::motion_multipliers` 只设置角色 SPEED/JUMP 等普通值，场地和材质保持结构体缺省。因此先补原版材质/区域资源生产者及本端解析，再把同一地面积分中的分支落入 `V17NormalMotion::StepGround`，分别记录参数来源、适用模式及未知项。本轮不修改实现。不能把“参数表已加载 slipForce/slipSpeed”或“能沿斜坡投影”报告成滑面/传送带/区域物理已对齐；仍需选真实地图核验材质值、坡度分支、进出区域及速度时序。


<a id="water-flight"></a>

## 7. 水域、飞行与特殊空中（#256）

**模式判定。** `0x96C1D3` 排除普通空中路径的三个条件为 G4 为真、VecCtrl 虚槽 `+8` 为真、或 `C[+0x78]>0`。本轮核对本地角色 VecCtrl 构造 `0x9CB89A` 与虚表 `0xB3EAA8`：槽 `+8` 指向 `0x9CB8C1→0x9CB8C6`，实际读取受保护整数 `FA+0x30`，**等于2**时返回真。G4 则检查同一字段等于1或当前位置命中 `FA+0x3C` 区域。由此可以确认原版具有“全图模式1 / 全图模式2 / 局部区域”三种入口；IMG 键到这些字段的生产链仍未知，暂不按名称把它们全部归为 `info.swim`。

**共同状态与积分。** `0x9B2C3C` 开头读取 `mass=C[+0x0C]`、世界瞬时 `vx/vy`，令 `D=FA[+0x0C]*floatDrag1`，`dt=传入毫秒*0.001`。`0x9B2EE3` 后的特例分支与普通空中共用 `0x9B3421–0x9B34BE` 的梯形位置积分与同一步速度写回：`p_new=p_old+(v_old+v_new)*dt/2`。因此当前 headless 的每8ms离散阻尼不能通过“改一个常量”直接视为原版特例运动。

**参数选择。** 令 `r=abs(FA[+0x18])`、`u`为原版水平输入。绝对值来自 `0xA6203F`（有限数路径清 double 符号位），不是正弦函数。三条分支选择如下；`Sx/Sy` 是随后各轴超速制动与力积分使用的限值，`A` 是竖向后续分支使用的加速度量：

| 条件 | 水平方向力 F / 水平限值 Sx | 竖向限值 Sy / 加速度量 A | 原版地址 |
| --- | --- | --- | --- |
| 虚槽+8为真（本地角色 `FA+0x30==2`） | `F=u*flyForce*r`；`Sx=flySpeed*r` | `Sy=FA[+0x24]*fallSpeed*0.015`；`A=flyForce/mass/r` | `0x9B2EE3–0x9B2F79` |
| 虚槽+8为假，G4为真 | 令 `k=C[+0x54]`；`F=u*swimForce*k*r`；`Sx=swimSpeed*C[+0x60]*r` | `Sy=Sx`；`A=swimForce/mass/r*k` | `0x9B313D–0x9B31F9`、`0x9B3342–0x9B335B` |
| 两者为假，特殊能力分支 | 令 `k=C[+0x78]`；`F=u*flyForce*k*r`；`Sx=flySpeed*C[+0x84]*r` | `Sy=Sx`；`A=flyForce/mass/r*k` | `0x9B318B–0x9B31F9`、`0x9B3342–0x9B335B` |

**横向递推顺序。** 当限值非负且当前速度超过 `±Sx` 时，先以 `D/mass*dt` 把速度向该侧限值制动，越过限值即停在限值；随后，无水平输入时再以同一减速量朝0制动，跨0归0；有水平输入时调用 `0x9B2BCB(vx,F,mass,Sx,dt)` 的单向力积分。也就是说，超限且松向时同一步可能经过两段制动。地址分别为模式2的 `0x9B2F79–0x9B3065` 与其他特例的 `0x9B31FC–0x9B32E8`。这与 headless 的 `vx=(1−friction)*vx+force` 不同。

**竖向已确认与剩余边界。** 各特例同样先用 `D/mass*dt` 处理超出 `±Sy` 的竖向速度；模式2随后读取 `V+0x15C` 的受保护整数并分支，出现 `7*Sy` 和 `0.5*A*dt`；其他特例读取同一输入，出现 `0.3*Sy`、`1.5*Sy` 与不对称的 `A*dt/0.5*A*dt`（`0x9B3065–0x9B3138`、`0x9B32E8–0x9B341A`）。本轮未闭环该输入的设置者和动作含义，故不把这些常量包装成“按上/按下/松键”的完整控制规则。`flyJumpDec` 属起跳路径，不能把它当成本节空中递推的统一减速系数。完整竖向输入语义、模式生产者、进出区域和触地/离地切换仍需专项核验。

**headless 对照与后续调整。**

| 当前代码 | 已核实行为 | 后续调整记录 |
| --- | --- | --- |
| `Gameplay/MapleMap/MapInfo.cpp::MapInfo/is_underwater`、`Character/Player.cpp::respawn` | 仅把 `info["swim"].get_bool()` 存为 `underwater` | 先核对资源生产链，保留原版模式1/2及局部区域信息；不能用一个布尔值代替。 |
| `Character/PlayerStates.cpp::PlayerFlyState`、`Player.cpp::get_flyforce` | 根据 underwater 选 SWIMMING/FLYING，四向力固定0.25；攻击时跳过输入力设置 | 原版参数选择要消费实际场地与能力字段，竖向输入需按设置者及分支补证。 |
| `Gameplay/Physics/Physics.cpp::move_flying/move_swimming` | 每8ms使用0.05/0.08线性阻尼，水中另加0.03；不读取 `Physics.img` 的特例参数 | 按真实模式建立与普通运动一致的时钟/规范状态交接，使用本端资源参数与原版有界制动、力积分、梯形位置。 |
| `headless/src/PlayerPhysicsPose.h::PlayerPhysicsPose` | legacy 模式有8ms位置提交，瞬时速度保持未知 | 后续对齐前补对应状态的真实末态观察；当前不能用显示均速或8ms位移冒充原版瞬时速度。 |

证据：既有 REA `tmp/tick-motion-gui/decompile-9b2c3c.json`/`.c` 与本轮重新读取原件的 `tmp/250-motion-rules/raw/special-air-9b2ee3.txt`；虚槽和 fabs 可由上列 VA 复取。未新增原版动态样本。

## 本轮次对齐结论与交接（2026-11-17，30 轮结束）

本段汇总本轮次（#250）实际落地与仍被证据门槛阻塞的内容，供后续会话直接接续；详细证据仍留在所属环境 `tmp/` 与各 Issue。

### 已合并实现（均有离线合同/真机证据）

| PR | 内容 |
| --- | --- |
| #261 | 攀爬 30ms 步、顶端/底端退出、跳离两段式（#251） |
| #262 | 受击排队冲量/方向限幅/向零截断/脱地、`(±270,−270)`、1500ms 保护（#252 受击部分） |
| #263 | 入站路径 command 布局修正 + `MovementReplay` 非受控回放（#253/#259） |
| #264 | MoveMob 出站 U16 序号递增（#259） |
| #265 | 受控地面怪物行走力 `(raw+100)*0.002`，3 模板 p50/p90 与原版比值 0.999（#253） |
| #266 | 远端玩家路径回放（OpenChar→MovementReplay；双端相位对齐中位差 1.0px）（#258） |
| #267 | Drop 悬浮 `yd+3sin`（范围 6px、周期 2s）（#258） |
| #268 | Drop 目标锚点=图标中心（同批 10 对象差 ≤0.7px）（#258） |
| #269 | Drop 落下 30ms 分段公式，D=1000ms（landed 时序与 GUI 一致）（#258） |
| #270 | 受控怪决策节奏 30ms×11–33 步 + STAND 1/3 保持（#253） |
| #271 | MOVE_PLAYER 片段速度字写入真实 vx/vy（#259） |
| #272 | MOVE_PLAYER 完整布局（上下文 0/起点/片段/K=0/bbox）（#259） |
| #273 | MOVE_PLAYER 路径记录/合并/500ms 批量/逐帧方向 nibble（#259） |
| #274 | Drop leave 即时池移除（GUI 0.036s vs headless 16–64ms）（#258） |
| #275 | Drop v=720 分支按 pickuptype 选择（字段来源反汇编闭环）（#258） |

### 当前验证基线

- main 全量离线测试 **535 tests OK**；CI 五项（Python/Headless/Windows bridge/format/harness contract）在对应提交均绿。
- 双端证据目录：`tmp/251-climb/`、`tmp/252-hurt/`、`tmp/253-mob-evidence/`、`tmp/258-otherchar/`、`tmp/258-drops/`、`tmp/259-moveplayer/`、`tmp/259-moveplayer-layout/`、`tmp/259-moveplayer-batch/`、`tmp/263-two-client/`、`tmp/264-*` 等（所属环境保留）。

### 仍被阻塞（不按猜测实现）

- **#258 bullet 时间窗**：记录对象 `+0x0/+0x4` 的绝对开始/结束时刻生产写入点未定位（更新函数 0x43FEEE/列表 0x445117 已核实）；GUI 桥不暴露 projectile，无法双端对账。需进一步 RE 创建路径或抓到实际 bullet 记录。
- **#259 收尾**：抑制分支完整条件、强制 flush（换图/受击/瞬移）、服务器 ACK 未逐项追完。
- **#253 收尾**：AI 长尾（原版站立 p90 3.65s/max 10.6s 非单一几何模型）、飞行/追击/跳跃参数、边界 override、控制权授予/回收。
- **#252 死亡/复活**：复活 HP 公式（观察值 50/max169）、死亡过程物理与 GUI 观察语义未闭环。
- **#254–#257**：需移动技能角色、特殊地形/水域地图或动态平台场景，当前授权角色/地图无法构造。

### 复位/恢复入口

- 工作台统一入口 `private/workbenches/workbench DIR COMMAND`；常驻服与账号池规则见 `AGENTS.md`。
- 离线验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli`；格式 `python3 tools/format.py --check`（需 `STYLUA`）。
- 双端验证脚本/记录：`tmp/` 下各证据目录；GUI 桥工件在 `tmp/client-images/bridges/<sha>`。

## 剩余对齐工作与证据门槛（状态快照 2026-11-17）

本节汇总 #250 子任务已经落地与仍未闭环的部分，供后续会话按证据门槛继续，不把未验证的推断写成实现依据。

### 已落地并有离线/真机证据

- **#251 攀爬**：30ms 步、顶端/底端退出、跳离写速度两段式；离线合同 + GUI/headless 样本。
- **#252 受击/击退**：排队冲量、方向限幅、向零截断、脱地；普通触怪 `(±270,−270)px/s`、1500ms/50 步保护均由双端真机确认。
- **#253 受控怪物基础速度与节奏**：地面行走力 `(raw+100)*0.002`（3 模板 p50/p90 与原版比值 0.999）；随机决策计数（30ms/步，11–33 步，每次重抽）+ STAND 1/3 保持；站立段 p50 0.75s（GUI 0.93），p90 1.45s（GUI 3.65）。
- **#258 远端回放与 Drop**：非受控 Mob/远端玩家按 V17 路径时长/Hermite 回放（远端玩家相位对齐后中位差 1.0px）；Drop 悬浮 `yd+3sin`（范围 6px/周期 2s）、目标锚点=图标中心（同批 10 对象差 ≤0.7px）、落下 30ms 分段公式（D=1000ms，landed 时序与 GUI 一致）。
- **#259**：入站路径 command 布局修正；非受控回放；MoveMob 出站 U16 序号递增（GUI 观察端真机跟随通过）；MOVE_PLAYER 片段速度字改为真实 vx/vy（#271）、出站布局补齐上下文/起点/K/包围盒（#272）、路径记录/合并/500ms 批量发送与逐帧方向记录（#273）。
- **#258（续）**：远端玩家路径回放（#266）；Drop 悬浮 `yd+3sin`（#267）、显示锚点=图标中心（#268）、落下 30ms 分段公式 D=1000ms（#269）、leave 即时池移除（#274）、v=720 分支按 pickuptype 选择（#275）。
- 明显差异但已按证据/合同验证的 legacy 模式（攀爬/受击/回放等）继续保留。

### 仍未闭环的阻塞项（按证据门槛）

| 任务 | 未闭环项 | 阻塞原因/下一步 |
| --- | --- | --- |
| #252 | 死亡/复活运动与观察、复活 HP 公式 | headless 无 revive 能力，GUI `dead/revive_requestable` 未暴露；复活 HP 观察到 50（max169）但生产规则未知。下一步：RE 或服务器侧证据。 |
| #253 | AI 长尾、飞行/追击/跳跃参数、边界 override、控制权 | 60s 速度段显示原版站立 p50 0.62s/p90 3.75s/max 12.45s，单一几何模型拟合不了；长站立横跨地图，非贴边单一解释。需原版 AI 更新时钟/保持映射证据再调参。 |
| #254 | 移动技能（冲刺/瞬移等） | 已授权角色均无移动类技能；需要带技能的角色或合法加点。 |
| #255 | 场地特例（材质/滑/特殊力） | 需要特殊地形地图与材质数据生产链。 |
| #256 | 水域/飞行/特殊空中 | §7 模式1/2/局部区域的生产链未闭环，headless 8ms 离散阻尼与梯形积分不同；需可达游泳图与模式读数。 |
| #257 | 有向碰撞、顶头、移动平台 | 未找到动态平台生产者/反向段实际地图场景，无法真机验证。 |
| #258 | bullet 时间窗 | 原版 bullet 记录 `+0/+4` 绝对开始/结束时刻的生产规则未闭环；GUI 桥不暴露 projectile（capabilities false），无法做双端轨迹对账。 |
| #259（补充） | 抑制分支完整条件、强制 flush（换图/受击）、服务器 ACK | §10 只确认了“同起点/端点/速度/state/无额外记录时抑制”的结构；强制刷新入口与 ACK 未逐一追完。 |
| #259 | MOVE_PLAYER 批量/合并/gate/上下文、MoveMob 其余字段/ACK、远端换图残留 | §10 静态布局已确认，但上下文字段业务含义、合并门控与服务器 ACK 未闭环；需逐字节合同+服务器无拉回验证。 |

### 建议的下一步顺序

1. #259 收尾：抑制分支/强制 flush/ACK 的静态证据核对（MOVE_PLAYER 片段速度、布局、批量、方向记录已落地）；
2. #258：Drop leave/pickup 生命周期与 bullet 时间窗，可用双客户端同批对象对账；
3. #253：#253 长尾与飞行/追击/跳跃参数需要更长原版样本与模式读数；
4. #254–#257 依赖额外授权角色/特殊地图/动态场景，先记录证据门槛，不按猜测实现。

<a id="collision"></a>

## 8. 有向碰撞、顶头与移动平台（#257）

**有向线段规则。**【观测·静态】原版本地角色 VecCtrl 的空中碰撞虚槽 `+0x10` 指向 `0x9B34C8`。它先将本步旧、新世界脚点圆整为整数，向管理器 `+0x44` 查询覆盖整段运动的候选集合（`0x9B34EE–0x9B3652`），随后使用候选 foothold 的原始有向端点 `(x1,y1)→(x2,y2)`。令：

```text
s(P) = (Py−y1)*(x2−x1) − (Px−x1)*(y2−y1)
```

`0x9B3712–0x9B377C` 要求 `s(old)<=0 && s(new)>=0`，且二者不能同时为0；`0x9B3782–0x9B37D2` 再检查两线段交点是否在运动段内。其后按交点的有理比例比较选择接触顺序，并处理端点相接的两候选段（`0x9B380B–0x9B39DC`）。这确认了“有向几何的单侧穿越”，不能概括为“所有非墙foothold只在世界 y 向下时碰撞”。【推导】水平正向段只接受从上到下，水平反向段则接受从下到上；后者能进入上升接触分支，但具体地图是否提供该几何仍需核对。

**碰撞响应边界。** 接触之后原版以切线方向投影速度，`0x9B3C60–0x9B3DDD` 以 `foothold.cos>0` 区分普通承托面与其他朝向；非承托方向在特定调用阶段投影世界速度，并利用剩余时间更新位置，后续仍由 Update 处理余步。当前已定位响应路径，尚未逐场景核验墙、反向顶面、尖角的全部取舍。不能用本轮线段筛选公式声称已完成顶头的真机还原。

**headless 差异。** `FootholdTree::SweepLocalMotion` 已有完整段横向墙限制、普通平台连接、`dy>0` 时的落地扫掠以及地图上下边界夹取；地图上边界会清 `vy`，因此“完全没有顶部限制”不准确。它在 `dy<=0` 时直接提交目标位置，没有与原版有向反向段对应的接触分支；落地候选也没有原版的完整端点相接/朝向响应。后续应先选含反向段的实际地图，核对原版是否命中、响应和余步，再补对应几何合同；不能把任意绘制对象的顶部都当碰撞面。

**移动平台仍未知。** 本轮已审查原版普通 foothold 构造 `0xA4534A–0xA45436`、VecCtrl 的地面/空中碰撞入口，以及 headless `Foothold/FootholdTree` 与 `MapTilesObjs/MapBackgrounds`。当前证据确认了端点、邻接、材质和静态索引；未找到可据以给出角色携带速度或相对位移的动态平台生产者。headless 的背景有独立滚动速度，绘制对象有动画更新，两者未参与 foothold 更新，不能据此声称已支持动态平台。后续先确定实际地图、对象种类及导航消费者，再追对象→碰撞几何的更新链；携带速度、船只/升降台机制和与顶头的组合均保持待取证。

证据：本轮 `tmp/250-motion-rules/raw/environment-collision.txt`；原版 VA `0x9B34C8–0x9B3E55`、`0x9B3FD1`、`0xA4534A–0xA45436`。headless 对照入口为 `Gameplay/Physics/Foothold.cpp`、`FootholdTree.h::FootholdInfo/LocalSweepInput`、`FootholdTree.cpp::SweepLocalMotion`、`Gameplay/MapleMap/MapTilesObjs.cpp::update`、`MapBackgrounds.cpp::Background::settype`。


<a id="entities"></a>

## 9. 掉落物、普通 bullet 与远程玩家（#258）

本节为只读静态规则取证与源码对照，基线 `main=7ee21cd`，原件 SHA256 与本文首页一致；没有新增实机轨迹或服务器效果证据。原版地址是 VA；以下所有公式属于各自实体的原生显示/路径模型，不借用本地角色的普通运动公式。

### Drop：30ms 分段显示轨迹、锚点和出池

【观测·静态】原版 DropPool update `0x504BFF` 以 `drop+0x48` 分派状态。落下 state1 的 `0x505117` 与继续下降 state2 的 `0x504E9C` 都对 `drop+0x4C` 加 `0x1E`（30ms），随后乘 `0.001`。这套显示轨迹没有调用本地角色普通运动积分器。

设 `m=drop+0x4C` 的毫秒计数，`t=m/1000`，`D=drop+0x50`；`x0/y0` 是以 `0x42873D` 解读的 `drop+0x0C/+0x00`，`xd/yd` 是 `drop+0x74/+0x68` 的目的锚点。`v=400`，仅当 `drop+0x2C==3` 时取 `720`（`0x504C56–0x504C72`）。该选择字段的业务名称和 D 的完整生产规则仍未知，不能把两个 v 值推广成所有掉落物的自由落体参数。

【观测·静态】state1 在 `0x505117–0x505226` 计算整数显示点，转换前的 double 为：

```text
u = min(0.002*m, 1)
w = 0                                 (m <= 500)
    min((m-500)/(D-500), 1)            (m > 500)
x = x0 + (xd-x0) * (u+w) / 2
y = y0 - v*t + 400*t*t
```

`0x505229–0x50536D` 在计数达到 D 后判断 `y0 >= yd`：成立则设置 state3、将显示点放到目的锚点；否则设置 state2 并清零 m。state2 再以每次 30ms 推进 `y=y0+v*t`，到达/越过 yd 后设置 state3（`0x504E9C–0x504FD4`）。本节仅记录反汇编可直接还原的既有分支，不为未观察的 D 值补边界行为。

【观测·静态】state3 的 `0x504D98–0x504E62` 每次把 `drop+0x60` 相位加 `0.0942477`，经原件 `sin` 实现 `0xA62114`（实际 `fsin` 位于 `0xA62132`）计算：

```text
显示 x = xd
显示 y = 整数转换(yd + 3*sin(phase))
```

相位和显示 COM（`drop+0x3C`）更新，目的锚点保持原值。因此 GUI 观察适配器 `beidou-ijl15/ezorsia/ObserveWorld.cpp::Drops` 公开的 `native_drop_destination` 是锚点；它既不跟随悬浮，也不代表当帧抛物线显示点。当前同参考点速度保持未知是有据可依的行为。

【观测·静态】OnLeaveField `0x506590` 对 leave type2/3/5 在 `0x50661C–0x506627` 读取拾取者 ID；普通移除路径先在 `0x50663E` 调用 `0x5056AF` 移出 DropPool，再按 leave type 构造显示效果，拾取效果进入 `0x4360C3`。飞向拾取者的效果不再是原 DropPool 中的同一观察成员。type4 读取一个 short 延时，加原生当前时间写 `drop+0x44`，并切 state4（`0x5065E6–0x506608`）；state4 的 deadline 到期后才走移除（`0x504C9D` 起）。state4 应称延迟移除，不能命名为拾取态。

当前 headless 的对应事实：

- `Gameplay/MapleMap/Drop.cpp::Drop` 对 mode0/1 设 `vspeed=-5`、`hspeed=(dest.x-start.x)/48`，由 legacy 8ms `Physics::move_object` 积分并以 foothold 碰撞落地；这与上述 30ms 分段显示公式及 D 时钟不同。
- `Drop::update` 的 FLOATING 每个 8ms 步直接写 `phobj.y=basey+5+(cos(moved)-1)*2.5`，相位增量 `0.025`；以 `basey=dest.y-4` 的落地路径为例，均值为 `dest.y-1.5`、振幅 2.5px。原版显示振幅为 3px，公开锚点保持 yd。
- `headless/src/SharedLuaAdapter.cpp::Capture` 读取 `get_position()` 并采完整 update 的位置差为 velocity，故 headless 的 Drop 公开位置包含其显示摆动；GUI 的公开锚点与它不是同一参考点。两端这组 x/y、velocity 不能直接套用“物理轨迹误差 ≤1px”的比较。
- `Drop::expire(0/2)` 保留 Drop 为 PICKEDUP 成员，`Drop::update` 每步淡出 `1/48`，直到返回 −1 才从 `MapObjects` 删除。mode2 设置向上速度 −4.5，并把下一步横向速度更新为 `looter.hspeed/2+(looter.x-drop.x-16)/48`；GUI 已出池后交独立效果。`expire(1)` 仅 deactivate，与 GUI 的各 leave type 仍需逐一核对。

【后续调整记录】#258 应先明确 AI 拾取消费者需要“目的锚点”还是“当前显示点”，记录/对齐公开参考点和 landed/存在性，再调整落下、悬浮及独立拾取效果的时钟与生命周期。不要把原版的锚点 velocity 填成 headless 的动画位移速度；完成数值规则也不能替代真实拾取时机与拾取结果验收。D 的生产路径、全部 leave type、原版拾取效果轨迹仍需补证。

【同对象字段对账（2026-11-17，#267 双客户端同一批 DropPool）】相同 oid/x 的两个对象：GUI 公开锚点 y=1957（oid60）/1943（oid61），headless `dest.y`（悬浮均值）为 1971/1955，差 +14/+12；headless 的抛物线起点采样两者同为 y≈1955（共享出生点）。说明两端对同一 DropLoot 包的 `dropto/dropfrom` 字段映射或锚点偏移并不一致，不能直接把差值归给显示公式。下一步需抓取/反汇编原版 Drop 创建时 `drop+0x0C/+0x00/+0x74/+0x68` 与包的写入顺序，确认 GUI 公开锚点到底对应哪个包字段，再决定 headless `dest` 的赋值。

【已落地调整（2026-11-17，#275）】Drop state1 的 v=720 分支已闭环：反汇编 DropLoot 解析 `0x505900` 显示 `0x5059E1` 读取的 byte（`0x4065F3`）写入 `[drop+0x2C]`，其顺序对应包字段 mode/oid/meso/itemid/owner/pickuptype，因此 **`drop+0x2C` 就是 pickuptype**；`0x504C66` 在 `pickuptype==3` 时取 v=720（`0xAF3738`），否则 400（`0xAF3740`）。headless 已按 pickuptype 选择速度（`DropFallVelocityForPickupType`），合同覆盖 3/0/2 与 v=720 公式。回归真机：normal 掉落 landed 1.008–1.010s、上升 84–90px（v=400 理论 100px；v=720 应约 260px），确认非 3 类型仍 v=400 无回归；pickuptype==3 的实际场景仍未构造。

【已落地调整（2026-11-17，#274）】Drop leave 已按 §9 的“先出池再播放独立效果”对齐池移除时序：`Drop::expire` 对任意 leave type 置 `instantRemove`，下一次 update 直接返回 -1，由 `MapObjects` 删除；headless 无独立拾取效果对象，因此只保留池移除时序（不再有 48 步淡出/飞行）。`headless_motion_contract` 两个 Drop 场景改为“leave 后一次更新移除”。双端真机：GUI 拾取 `PRESS→GONE` 0.036s；headless 拾取 6 个对象为 0.016/0.040/0.024/0.048/0.064/0.032s（均值约 37ms），同量级；旧实现约 384ms 后才会从公开列表消失。证据 `tmp/258-drop-lifecycle/`。

【已落地调整（2026-11-17，#269）】落下显示已改为 §9 的 30ms 分段公式（`DropFallDisplay.h`）：`m` 每世界步 +8ms；`u=min(0.002*m,1)`、`w=0`（m≤500）或 `min((m-500)/(D-500),1)`；`x=x0+(xd-x0)*(u+w)/2`、`y=y0-400t+400t²`；到 D 后按 `y0` 与锚点关系直接落地或进入 state2 `y=y0+400t`。**D 取 1000ms**：GUI 20Hz 生命周期采样（15 个 DropPool 对象）spawn→landed = 1.009–1.06s，与物品类型/高度无关；`drop+0x2C==3` 的 v=720 分支生产字段未闭环，统一用 400 并保留缺口。真机复核（headless 击杀，20Hz）：9 个新掉落 spawn→landed = 0.957–1.008s、p50 1.007s，与 GUI 时序一致；旧 8ms 物理落下路径已被替换（`PICKEDUP` 物理拾取保留）。

【已落地调整（2026-11-17，#267/#268）】headless 悬浮显示已按 state3 静态公式实现：`y = yd + 3*sin(phase)`、相位按 30ms 的 `0.0942477` 换算到 8ms 世界步（π rad/s、2s 周期），落地显示点改为锚点 `yd`（`DropDisplay.h` + `drop_display_contract`）。双客户端真机（GUI 击杀者 + headless 观察者）测得悬浮范围 6px（±3）、周期 1.95–2.0s，与静态公式一致。

锚点字段差异已由 #268 闭环：GUI 公开锚点与 headless 包目的地差 12–14px，对应图标半高（`4000003` iconRaw 28px→14、meso `09000000` iconRaw 24px→12）；原版 `yd` 是图标中心，即 `yd = 包目的地 − 图标半高`。headless 已加 `virtual get_icon_half_height()`（ItemDrop/MesoDrop 按图标尺寸/2）并按 `dest.y − half + 3sin` 显示。同批 10 个 DropPool 对象复测：headless 落地 x 与 GUI 锚点完全一致、悬浮均值与 GUI 锚点差 ≤0.7px（改动前 12–14px）。证据在所属环境 `tmp/258-drops/`。

【动态证据（2026-11-17，同图 `102010000`）】GUI CID6 击杀怪物后观察 DropPool：掉落物公开锚点 x/y 在生命周期内保持不变，`landed` 在约 1.0–1.06 秒后为真，观察到的生命周期约 2.4/4.6 秒（服务器侧产生）。同图 headless CID6 击杀后观察显示点：落地悬浮稳定后 x 与锚点一致，显示 y 在 1931–1936 间摆动（均值 1933.5，幅度 ±2.5），而 GUI 同 x 的锚点 y 为 1921–1924；即 headless 显示均值比原版锚点低约 11–12px，原版显示公式为 `yd+3*sin(phase)`（锚点均值、幅度 3），headless 为 `dest.y-1.5` 均值、幅度 2.5。headless 新掉落的抛物线落下轨迹已在该窗口观察到（x≈1970–2005、y 1843→1933）。参考点差异与 dest.y 的来源（服务器锚点还是 foothold）仍需闭环，不能直接按屏幕坐标比较两端轨迹。证据在所属环境 `tmp/258-drops/`。

### 普通 bullet：原生时间窗口与 headless 目标阈值

【补充取证（2026-11-17）】记录更新函数 `0x43FEEE` 已复核：入参 `now` 与记录 `+0x4` 比较，`now > +0x4` 时返回 true 并由列表移除；`+0x2C` 显示 COM 为空且 `now > +0x0` 时才创建显示 COM。唯一调用方是列表 update `0x445146`（列表入口 `0x445117`）；记录对象由其它攻击/显示路径创建，其 `+0x0/+0x4` 的绝对开始/结束时刻生产规则尚未定位到写入点，因此仍不能实现或验收 bullet 时间窗。GUI 桥不暴露 projectile（`capabilities.projectiles=false`），也无法做双端轨迹对账。

【观测·静态】已确认的范围是普通 bullet 显示记录子集：owner `*(0xBEBF6C)` 的 `+0x58` 列表，owner update `0x43796B` 调 `0x445117`，遍历后调用记录更新 `0x43FEEE`。资源加载 `0x440DA7` 读取 `bullet`（StringPool sid `0x03D7`）；`bulletSpeed` 是资源参数，不能当当前向量。

本轮补核 `0x43FEEE` 的头部：

- `0x43FF04–0x43FF12`：当 `now > record[+4]`，返回 true，调用列表的 `0x445152 → 0x4469A2` 将记录移除。
- `0x43FF19–0x43FF26`：已经有 `record+0x2C` 显示 COM 时不重建；COM 尚不存在且 `now <= record[+0]` 时也不创建。
- `now > record[+0]` 且未超过结束时间时才创建 `Shape2D#Vector2D`（`0x43FF32–0x43FF5D`），随后组装显示 COM。记录的 +0/+4 因而是原版开始/结束时刻事实；不能用数组下标或 +0x28 资源参数制造稳定实例 ID。

当前 headless `Gameplay/Combat/Bullet.cpp::settarget` 在初始距离 `abs(dx)<10` 时直接完成；否则 `hspeed=clamp(dx/32, ±3..±6)`（每 8ms 位移），`vspeed=hspeed*dy/dx`。`Bullet::update` 先积分，再用横向越过目标的阈值返回完成；`Gameplay/Combat/Combat.cpp::update` 更新目标怪物的头部位置并在完成时应用 damage effect。已确认两端的生命周期驱动不同：原版记录以绝对时间窗口持有显示 COM，headless 以自有积分和目标阈值结束。

【未知】原版 COM 的完整插值参数、各类 bullet 的开始/结束时刻生产规则、当前坐标/速度的纯内存布局，以及其他魔法弹/场景弹的集合覆盖仍未闭环。这里只能确认普通子集的时间窗口和存在性，不能据此声称所有投射物都有相同路径或模板速度。

【后续调整记录】#258 先按 AI 实际使用的普通远程攻击选定 bullet 子集，对照发射/消失时机、消费者所见位置、视觉命中与 damage effect 时机；查清原版 COM 路径后再判断是否替换 `Bullet::settarget/update`。远程玩家/怪物目标丢失与换图残留需要按实际消费者验证，不能以“本地 flight list 非空/为空”代表全世界投射物事实。

### Remote User：逐路径推进与当前末元素跳位

【观测·静态】原版 Remote User update `0x97FDF8` 使用对象自己的 `O+0x11A4` 主 COM（`V=COM-0xC`），调用 `0x9B16E8`。该函数先调 vtable `+0x30` 保存上一物理态，再以 **30ms** 调 `+0x34`；`0x9B1719 → 0x68ADCC` 推进 `V+0x1AC` 路径，并将 x/y/vx/vy 写回自己的 secure 字段 `V+0x20/+0x38/+0x50/+0x68`。调用方传入30ms，路径内部另按缓冲选择30/33ms追赶（第10节），两者应分开记录。这里存在原生路径推进和瞬时速度事实；`0x9B6205` 另以新旧物理步作显示插值，整数显示坐标不等于物理末态。

当前 headless `Character/OtherChar.cpp::send_movement` 仅排队 `newmoves.back()`，丢弃同批前面的 movement，开始时 `timer=50`。`OtherChar::update` 首次约等待 50 个 8ms 世界更新，随后每步取一个队列末元素，令 `hspeed=xpos-current_x`、`vspeed=ypos-current_y` 并 `move()` 一次到达该位置。它没有按 `Movement::duration` 消费整条路径；观察到的 `native_update_delta` 是这种实际跳位的整步均速，不是原版 CVecCtrl 的瞬时速度。

【后续调整记录】#258 与 #259 联动：补齐入站触发、到包调度和特例播放证据，依据第10节已确认的元素布局及duration单位替换 `OtherChar::send_movement/update` 的丢段和固定 50 步等待，保留包语义、路径推进、显示插值、观察向量四者的区别。应由第二名授权客户端发出同一批路径，核对远端到点时机和连续观察；当前静态证据不证明真实玩家重放已经一致。

【已落地调整（2026-11-17，#266）】`OtherChar::send_movement/update` 已按上述联动要求改为复用 `MovementReplay`：以当前显示位置为起点，按 30/33ms 追赶时钟推进接收路径并回写位置/fh/stance；攻击与入场动画保持原逻辑。双客户端真机：CID6 GUI 发送端 16 秒左右移动+跳跃（x 位移 258px），CID7 headless 观察端 `players[]` 中该角色显示轨迹相位对齐 0.5s 后中位差 **1.0px**、p90 5px、max 18px，无跳位残留（证据在所属环境 `tmp/258-otherchar/`）。仍未覆盖：换图/目标丢失残留、远端玩家到点时刻的逐包对账。

### 原始证据定位

本轮从匹配指纹的只读原件重新导出：`tmp/250-motion-rules/raw/drop-update.asm`（`0x504BFF–0x5056AF`）、`drop-leave.asm`（`0x506590–0x5067D0`）、`bullet-update.asm`（`0x43FEEE–0x440B70`）；常量按 `VA−0x400000` 读取 double：`0xAF3718=0.002`、`0xAF3728=3`、`0xAF3730=0.0942477`、`0xAF3738=720`、`0xAF3740=400`、`0xAF0D48=0.5`、`0xAF0E10=0.001`。

复用的既有原始证据位于 `tmp/tick-entity-motion/`：`drop-motion-state-region.txt`、`drop-packet-state-region.txt`、`drop-periodic-function.txt`、`bullet-list-update.txt`、`bullet-list-update-caller-43796b.txt`、`common-vector-frame-dispatch.txt`、`remote-update-assembly.txt`；Remote REA 反编译 evidence 为 `ev_daa2242a9264424dbc2f6c6fb73e99933ea10da925a00e7f0d85f1b8050525dd`。正式文档以内嵌规则、原件指纹、VA 和当前源码符号为可复查依据；这些本地证据路径用于本机复核，未提交原始资源或运行数据。


<a id="wire"></a>

## 10. MOVE_PLAYER、MoveMob 与远端路径（#259）

### 取证范围与结论

本节对照 `main=7ee21cd`，原件仍为本文指定 SHA256。新增证据来自原件只读反汇编，并按静态布局重新解码 #237 已采集的 **11 个 opcode `0x0029` 包**；本节未新增wire采样，复用#237运动包；本轮未修改wire。原始日志包含登录等无关数据，继续保留在所属环境；本节只保留运动结论与无私密字段例子。

- 【观测·静态】已定位原版路径解码 `0x68A33C`、路径序列化 `0x68A563`、发送门控 `0x68A828`、批量提交与清理 `0x68A88D`、逐步记录与合并 `0x68AB85`、路径推进 `0x68ADCC`。原版 `0x9CBB2A` 构造 MOVE_PLAYER，`0x9CBB6C` 调用批量提交，`0x9CBB81` 调用 `SendPacket=0x49637B`。这些地址使“只能靠抓包确定布局”的旧缺口收敛为可交叉核对的静态合同。
- 【观测·动态，复用 #237】11 包均能按下面布局完整解码，长度恰好为 44–100 字节；每包片段时长合计 **510ms**，尾部方向记录均为 **17 项**。时长可能拆为 `16+14ms`、`1+89ms`，所以单片段时长既不是“步数”，也不保证是 30 的倍数。
- 【观测·静态 + 动态】普通绝对片段中，headless 命名为 `lastx/lasty` 的两个 word 对应原版 **当前片段端点速度 vx/vy（px/s）**：创建者 `0x9B108A` 从 VecCtrl 的 x/y/vx/vy 四个加密 double 读取并整数化后交给 `0x68AB85`。既有样本直接出现 `vx=±125`、`vy=-555/670`，与普通运动规则相符。
- 【观测·静态】包尾 8 字节是路径端点的 **minX/minY/maxX/maxY**。`0x68A597–0x68A5BB` 先用起点初始化上下界，`0x68A6A9–0x68A6D6` 对绝对坐标更新 min/max，`0x68A78D–0x68A7C0` 输出四个 word。旧记录“末尾=当前 x,y”需要更正：单调向右平地时，最后一对 maxX/maxY 恰好等于终点；向左、往返和跳跃时不成立。此包围盒覆盖已记录的端点，不保证是连续曲线的精确几何包围盒。

【已落地调整（2026-11-17，#273）】MOVE_PLAYER 已实现路径记录/合并与 500ms 批量发送：`MovePlayerPath` 按 30/8ms 步记录片段，command/附着/state 相同且 vx/vy 同符号类别时合并（更新端点/速度、累加 duration），每步记录 left/right/up/down 4bit 方向；累计达到 **500ms**（捕获本地包 510ms 对应 17 个 30ms 步）后发送一次，`MovePlayerPacket` 写上下文 0/起点/片段数/片段/K nibbles/bbox，并从最后端点重置。respawn 重置路径。纯合同 `moveplayer_path_contract` 覆盖合并/方向/门控/bbox/符号跨越；`headless_held_input_contract` 的 packets 场景改为“空闲不越过 gate”。

双客户端真机（CID6 GUI 观察者 + CID7 headless 移动端，城镇 `102000000`）：headless 位移 179.6px，GUI 观察端显示范围 358–506，服务器持续转发无断线/踢线；批量使观察端约 **+0.8s 相位延迟**（最佳对齐 16 个 100ms 采样，中位差 25.1px），与 500ms gate+插值量级一致。剩余：抑制分支完整条件、上下文生产链、强制 flush（换图/受击）、服务器 ACK。

【已落地调整（2026-11-17，#272）】headless MOVE_PLAYER 出站布局补齐为 §10 结构：1+4 字节未知上下文写 0（生产链未闭环）、路径起点（上一发送端点；首包用当前端点）、片段数 1、fragment 0、方向记录计数 K=0（未逐帧记录输入方向，不伪造 nibble）、尾部 4 word 包围盒（起点/端点分量 min/max，`MovePlayerBounds.h` + `moveplayer_bounds_contract` 覆盖）。`headless_held_input_contract` 的 packets 场景更新为 35 字节布局断言（上下文 0、单片段、K=0、bbox 与 start/end 一致）。双客户端真机（CID6 GUI 观察者 + CID7 headless 移动端，城镇 `102000000`）：headless 位移 76.9px，GUI `players[]` 显示范围 56–124，移动样本相位 0 中位差 3.7px、p90 5.2px，无断线/传送/回拉。剩余：上下文字段生产链、K 的逐帧方向记录、批量/合并/gate 与 ACK。

【已落地调整（2026-11-17，#271）】headless MOVE_PLAYER 片段 0/5/17 的两个速度 word 已按 §10 语义修正：普通 V17 运动写 `LastStep().vx/vy`（px/s），legacy 附着模式用 `PhysicsObject` 8ms 速度换算 px/s；新增 `MovePlayerFragment.h` 做取整/int16 夹取与 `moveplayer_fragment_contract`（0/±125/−555/取整/夹取）。移动检测仍按位置版本 `hasmoved`，只改包内速度字。双客户端真机（CID6 GUI 观察端 + CID7 headless 移动端，同图 `102010000`）：headless 自身位移 124px，GUI `players[]` 显示范围一致（2169–2293），移动样本相位 0 中位差 4.9px（GUI 整数显示/采样量化），无传送/回拉/断开。剩余：上下文 5 字节业务含义、方向记录/包围盒、批量/合并/gate 与 ACK。

### 原版 MOVE_PLAYER 包结构

【观测·静态】下表偏移从未加密 opcode 开始，整数字段为 little endian。MOVE_PLAYER 调用方在 `0x9CBB37–0x9CBB5E` 写入 1 字节上下文和 4 字节上下文，随后调用共享路径编码器；上下文字段的业务含义仍待核实。

| 顺序 | 宽度 | 原版事实与依据 |
| --- | ---: | --- |
| opcode | 2 | `0x0029`。 |
| 上下文 | 1+4 | 来自全局上下文对象 `+0x134/+0x7B0`，当前 headless 用 9 字节零占位同时覆盖了这些字段与后面的起点。 |
| 路径起点 x/y | 2+2 | `0x68A56B–0x68A592` 输出路径对象保存的起点；不是首个片段端点。 |
| 片段数 | 1 | `0x68A5BE–0x68A5C3`，后接 N 个按 command 分派的变长片段。 |
| 方向记录数 K | 1 | `0x68A6FE–0x68A748`，可与运动片段数不同。 |
| 方向记录 | `ceil(K/2)` | `0x68A75B–0x68A784`，每项 4 bit，先低后高。普通输入路径 `0x9CC0A1–0x9CC0CD` 加入 left/right/up/down，`0x68ADA5` 打包为 `left<<3 | right<<2 | up<<1 | down`。特殊分支 `0x9CBF17–0x9CBF24` 可以加入四位全 1，不能只按物理键盘状态解释。 |
| 端点包围盒 | 8 | 4 个 word，minX/minY/maxX/maxY。 |

【观测·静态】原版编码 `0x68A600` 的 23 项跳转表（表 VA `0x68A7CC`）与解码 `0x68A3AF` 的跳转表（表 VA `0x68A507`）相互吻合。下面宽度包含 command 本身，`state` 是一字节动作/朝向编码，`duration` 为两字节时长；u/v 是尚未逐类命名的附加 word。

| command | command 后的字段 | 总宽度 | 当前 headless 解析差异 |
| --- | --- | ---: | --- |
| 0 / 5 / 17 | x,y,vx,vy,fh,state,duration | 14 | 长度对应；字段命名和消费者仍把 vx/vy 当 `lastx/lasty`。 |
| 15 | x,y,vx,vy,fh,u,state,duration | 16 | `MovementParser` 跳过原版 fh 后将 u 存为 fh；两个 word 的身份需要保留并按生产者核定。 |
| 1 / 2 / 6 / 12 / 13 / 16 / 18 / 19 / 20 / 22 | vx,vy,state,duration | 8 | 1/2/6/12/13/16 的长度对应，但存入 `xpos/ypos`；18/19/20/22 无分支。原版解码继承前一端点位置，同时把载荷写入速度槽 `+6/+8`（`0x68A403–0x68A42A`）。 |
| 3 / 4 / 7 / 8 / 9 / 11 | x,y,fh,state,duration | 10 | 仅 11 消费对应长度；3/4/7/8/9 当前只消费 command。 |
| 14 | vx,vy,u,state,duration | 10 | 当前只消费 command。原版分支 `0x68A494–0x68A4CA` 继承位置，读取两个速度和 u。 |
| 10 | 一个附加字节 | 2 | 当前只消费 command；原版 `0x68A4CF` / `0x68A733` 读写此字节。 |
| 21 | state,duration | 4 | 当前无分支；原版直接走公共尾部 `0x68A42E` / `0x68A6D9`。 |

这张表确认的是此原件的片段字节布局。尚未出现于既有动态样本的 command，其业务名称和触发条件仍未知。未知 command 的默认分支会进入 state/duration 公共尾部，但不能据此给未来版本定义通用容错格式。

### 时长、合并与发送门控

- 【观测·静态】`0x68AB85` 将本次时长加入路径对象 `+0x5C`，并将片段时长存入节点 `+0x10`。普通/下跳/特殊绝对 command `0/15/17` 会尝试合并：command、附着标识（节点 `+0x0C/+0x0E`）、state 相同，且 x/y 速度各自符号未跨正/负/零边界时，更新原节点端点/速度并累加 duration；否则通常新建节点；上一节点为零时长 command 0 时，存在直接复用并覆盖节点的分支（`0x68AC94–0x68ACB4`）。完整记录过程见 `0x68AC0F–0x68ACF9`。合并不要求速度数值恒定。
- 【观测·静态】发送 gate `0x68A828` 先要求队列非空；模式字段 `path+0x40 !=0` 时，累计时长门槛为 **500**，否则为 **1000**。达到门槛后，mode 非零或调用实参非零即可受理；两者均零时还要求队列中存在节点 `+0x0C >0`。本地调用方 `0x9CB9AD` 传入 0。该 mode 的完整枚举含义、各实体初始化值仍需沿生产者确认。
- 【观测·动态 + 推导】既有窗口的每包时长 510ms、17 项方向样本，与 30ms 步累计达到 500ms 门槛相符；墙钟发包间隔约 498–519ms。不能把这个窗口外推成所有状态固定每 500ms 发包。
- 【观测·静态】`0x68A88D` 序列化后更新路径起点、清理/交接已提交队列，并比较端点状态；调用方可以在返回值非零时抑制实际发送。原版在同起点、同端点 x/y/vx/vy/fh/state，且无额外记录等条件下存在抑制分支（`0x68A91A–0x68A966`）；因此“达到周期一定发一包”并不成立。换图、瞬移、受击等强制刷新入口尚未逐一追完。

无私密的复核例子：既有右行包两个 command 0 片段的 duration 为 `300+210=510ms`；起点 `(1859,1935)`，后一端点 `(1880,1935)`、速度 `(125,0)`。向左包起点 `(2000,1935)`、端点 `(1936,1935)`、速度 `(-125,0)`、duration 510，尾部是 `(1936,1935,2000,1935)`。这两个样本同时反证“lastx 是上一坐标”和“末尾最后一对必为当前坐标”。

### 远端推进与 MoveMob

- 【观测·静态】远端路径通过 `0x68A33C` 解码，`0x68B371` 将新路径接入已有队列。`0x68ADCC` 按 `path+0x78` 增加播放时间（重置 `0x68AB60` 的缺省为 30，末态由 `0x9B178F` 消费），按节点 duration 循环跨过已完成片段，更新位置、速度、fh 和 state；未完成片段通过 `0x68B108` 生成以端点位置和速度为约束的三次插值系数。其常量 `0xAF0E10=0.001` 将毫秒转秒，`0xAF8580=33.333333333333336` 将 30ms 位移差转换为速度。
- 【观测·静态】接入路径时 `0x68B41A–0x68B480` 根据缓冲时长选择每步推进量：阈值为 `(mode!=0 ? 500 : 1000)×1.1`，缓冲低于阈值用 30，否则用 33；缓冲大于“阈值+5000”时清理队列并加入 command 3 快照（`0x68B49C–0x68B4DD`）。这是远端播放追赶，与本地物理固定 30ms 的规则分开理解。
- 【推导】`0x68B108` 对经过时间 t、片段总长 D 使用 `u=t/D`，位置权重为 `2u³−3u²+1` 和 `−2u³+3u²`，速度权重含 `t/1000`。这解释 duration 的毫秒单位；完整特殊 command 的播放分支、零时长片段与到包延迟处理的动态效果仍须专项核验，不能将这条普通插值路径当所有远端运动的唯一公式。
- 【观测·静态】MoveMob 的原版出站路径 `0x66BBEA` 也用 `0x68A828` 门控，`0x66BC67` 构造 opcode **0xBC**，`0x66BD9C` 调用同一个批量提交函数。其前缀为 `oid:i32 / sequence:i16 / flags:u8 / action:u8 / skillData:4 / flags:u8 / aux:i32×3`，共 25 字节后接共享路径。`0x66BC95–0x66BCC2` 将序号加 1 写回并发送；最后两个 aux 在相应条件未命中时写 `0x00FFDDCC`（`0x66BD24–0x66BD56`）。各标志/aux 的完整业务含义和异常刷新仍未知。

### headless 差异与后续调整记录

| 差异 | 当前实现位置 | 后续需要处理的结果 |
| --- | --- | --- |
| 每次变化发单元素；普通运动提交 30ms、legacy 8ms，presentation 也尝试发送；无原版路径批量/合并/抑制 | `Character/Player.cpp::send_movement_if_changed`、`advance_local_motion`、`update_presentation`；`Net/Packets/GameplayPackets.h::MovePlayerPacket` | 将物理步、记录片段、批量发送分开；按已确认 gate 和合并规则设计 wire 改动前，补齐 mode 初始化与强制 flush 场景。 |
| `lastx/lasty=PhysicsObject` 前次坐标，duration 固定 1；前缀起点全零，无方向记录和包围盒 | `Gameplay/Movement.h::Movement`、`Net/Packets/MovementPacket.h::writemovement` | 明确内部结构中的位置/速度/时长/附着字段；按 V17 证据调整编码，避免将前次坐标换名后继续使用。 |
| 解析器对多个已证实 command 消费长度不足，15 的两个附着 word 丢失区分 | `Net/Handlers/Helpers/MovementParser.cpp::parse_movements` | **已按本文表格完成布局修正**（详见下方“已落地调整”）；仍保留 legacy 消费语义直到路径回放消费者落地。 |
| 远程角色仅保留每包最后一片段，固定延迟计数，逐帧直接到端点；未消费 duration/vx/vy | `Character/OtherChar.cpp::send_movement` / `update` | 按实际观察消费者恢复有时长的路径队列与端点插值；先核实到包调度及特例，不用固定延迟冒充物理时间。 |
| 非控制怪物只存入 movements 并设首片段 state/fh；常规 update 未按其 duration 播放 | `Gameplay/MapleMap/Mob.cpp::send_movement` / `update` | 与远端角色共用已证实的路径语义，分别保留怪物控制权和物理/展示消费者边界。 |
| MoveMob sequence 固定 1、skill 字节全 0、13 字节零 padding，单元素格式 | `Gameplay/MapleMap/Mob.cpp::update_movement`、`Net/Packets/GameplayPackets.h::MoveMobPacket` | 核定 sequence 与标志/aux；复用共享路径编码，按真实受控怪物场景验证服务端接受情况。 |

### 已落地调整（2026-11-17）

- **入站路径解析**：`MovementParser` 按本节表格修正全部已确认 command 的宽度与字段身份：0/5/17 读 x,y,vx,vy,fh,state,duration（vx/vy 同时写入 `Movement.vx/vy` 与 legacy `lastx/lasty`）；15 读 x,y,vx,vy,fh,u,state,duration 并保留未知附加 word 到 `Movement.extra`；1/2/6/12/13/16/18/19/20/22 读 vx,vy,state,duration（legacy 消费者仍把 vx/vy 放在 `xpos/ypos`，回放消费者将改用 `vx/vy`）；3/4/7/8/9/11 读 x,y,fh,state,duration；14 读 vx,vy,u,state,duration；10 消费附加字节；21 读 state,duration。未知 command 仍只消费 command 字节，不猜布局。
- **合同**：新增 `movement_parser_contract.cpp`，用构造字节覆盖上述 command 的宽度/字段与“整包恰好消费完”，离线测试通过。真实双端效果需要第二客户端/远端移动包场景，尚未执行。
- **路径回放**：新增 `Gameplay/MovementReplay.{h,cpp}`：把入站片段转换为带时长/端点位置/端点速度的段，未完成段按 §10 的三次 Hermite（h00/h10/h01/h11，速度项乘 duration/1000）求位置；缓冲高于 `1000*1.1`ms 时每步用 33ms，否则 30ms（mode!=0 的 500ms 阈值变体未实现，mode 生产者未知）。非受控怪物（`Mob::update`）改为消费该回放而不是继续本地 Journey 物理；控制权切回本地时清空回放。缓冲超过阈值+5000ms 的 command 3 快照重建尚未实现（保留 TODO 证据边界）。
- **合同**：新增 `movement_replay_contract.cpp`（线性绝对段、速度约束 Hermite、30/33 追赶、零时长段跳过）与 `movement_parser_contract.cpp`；离线全套 529 tests 通过。
- **双客户端真机验收（2026-11-17）**：常驻服 CID6 GUI 控制器 + CID7 headless 观察端同图 `102010000`；headless 先入图、GUI 后入图后观察端 35 只怪物全部 `controlled=false`（确认走回放路径）。12 秒 10Hz 采样中双端怪物均持续运动（各约 1.2 万 px 总位移），同一时间点位置中位差 **1.0px**、p90 5.1px，35/35 静止时刻位置完全相等；无解析错位/冻结。证据在所属环境 `tmp/263-two-client/`。
- **控制权观察**：`scene.monsters[].controlled` 由 headless 本地控制标记给出 true/false；GUI 桥无已验证读取路径，保持未知并在 `not_covered` 声明 `monster_controlled`（`docs/LUA_TICK_API.md` 同步）。
- **MoveMob 出站序号**：`Mob::update_movement` 不再固定写 `1`，改为按 §4/§10 的静态事实每包递增 U16 序号（`Mob.movementSequence`，对应原版 `mob+0x13C` 加 1 写回）；包内其余 2×U8/U32/U8/3×U32 语义与两个 `0x00FFDDCC` 哨兵仍未闭环，保持现状并记录缺口。
  - **真机验收（2026-11-17）**：常驻服 CID6 GUI（观察端）+ CID7 headless（控制器，`controlled=true` 35/35）同图 `102010000`；12 秒 10Hz 采样中 GUI 端持续回放 headless 的 MoveMob，按每只怪物最佳相位对齐后中位残差 7.0px、35/35 静止时刻位置全等，GUI 怪物总位移约 7.2k px，无断开/冻结/回拉；GUI 回放相对控制器约有 0.4–1.4s 批次延迟。无逐字节抓包，序号递增由“服务器接受 + 原版观察端持续回放”间接验证。证据在所属环境 `tmp/259-movemob-seq/`。
- 未变：出站 `writemovement` 仍是 legacy 单元素格式；MoveMob 标志/哨兵、路径批量/gate、远端角色回放仍在后续项。

【未知】既有证据没有构成所有 command 的动态触发覆盖，也未证明服务器依赖哪些历史宽容行为。本轮保留 headless 全部现值；后续 wire 调整仍需对应提交的字节级合同、服务器无拉回、换图/重登和另一客户端观察证据。原版发包与入站包布局分别核对，不能直接把出站尾部附加记录套到服务器广播包。

取证复现入口：对上述 SHA256 的原件执行 `objdump -d -Mintel --start-address=0x68A33C --stop-address=0x68AAB2` 可复核解码、编码、门控和批量提交；`0x68AB85–0x68ACFB` 复核合并，`0x68ADCC–0x68B4DF` 复核推进、插值与缓冲追赶，`0x9CB992–0x9CBB9F` 复核本地调用方，`0x66BBAC–0x66BDB0` 复核 MoveMob。临时证据索引为 `tmp/250-motion-rules/wire-evidence/`，只读解码产物 `captured-move-summary.json` 仅包含运动包。

<a id="runtime-evidence"></a>

## 11. 本轮实测与验收边界

### GUI攀爬、松键与顶底退出

【观测·动态】2026-11-16在常驻服的专用测试账号既有角色上，以本端CLI和工作台用户tick Lua采样；地图`10000`无怪，绳梯`index=1,x=975,top=127,bottom=363,l=1,uf=1`。有效SPEED/JUMP=100；运行配置`climbSpeedAuto=false,climbSpeed=1.0`。本轮未调整经验、职业或地图，也未创建额外角色；这组数据只证明该条件下的攀爬行为。

- GUI镜像来源为`7ee21cdfad4a71f7451f4013a6918298abfa88f6`，镜像ID `sha256:5efc1f2feac89ee04b96d7ced583c47618ab85579fcba796b03bb858176e776c`。
- Windows桥来自该提交的[成功构建43870420110](https://github.com/Diluka/beidou-pilot/actions/runs/43870420110)，`ijl15.dll` SHA256 `059aeb4f509643e2d463fff59a321b5db8110f2c89ecd0b9bd415da9e50b4880`。本轮运行未改桥或原版文件。
- 原始记录留在测试工作台所属实例的`runtime/bridge/script-events.jsonl`，前缀`TEST250 CLIMB`与`TEST250 CLIMB_DOWN`；脚本受理、终态和版本记录留在该工作台。本机汇总为`tmp/250-motion-rules/gui-climb-summary.json`及`gui-climb-down-summary.json`。采样按真实`physics.update_id`去重，步差只在相邻更新号间计算。

| 场景 | 本轮可复核结果 | 判断 |
| --- | --- | --- |
| 上攀内部区间 | 75个样本、74对连续步，x=975；y从354到132，每步−3；`step_ms=30` | 与原件3px/30ms及当前桥缺省一致，等价位移速率−100px/s |
| 下攀内部区间 | 75个样本、73对同阶段连续步，每步+3；`step_ms=30` | 与原件规则一致，等价位移速率+100px/s |
| 绳梯中段松方向 | 16个样本、15对连续步，y一直为190 | 该场景松键保持位置 |
| 顶端退出 | 观测到物理y=122，即top−5；下一步y=122.9、vy=60，随后落到上层平台y=125 | 覆盖带顶端退出标志的这一种几何；标志为0的顶端钳位未实测 |
| 底端退出 | 观测到y=361→364（bottom+1），随后落到下层平台y=365 | 与该绳梯的底端解绑及后续重力一致 |
| GUI攀爬速度字段 | 上述上/下攀内部样本均为`physics.velocity.y=0`，实际位置每步变化3px | 已确认当前字段不能表示攀爬位移对应的瞬时速度；后续须修观察语义，不能以零值通过速度对账 |
| 输入与实例终态 | 两个采样会话均completed，`control_released=true`；所属GUI容器正常退出、exit_code=0 | 放键和所属实例关闭已核对；不代表headless攀爬已对齐 |

### 其余证据与后续工作

- 攀爬之外的新增规则来自只读静态原件及当前源码对照；wire另复用#237的11个真实包并完整重解码。各节保留已知与未知，不把静态公式当成全部场景验收。
- 本轮没有改headless、GUI桥、Lua Runtime、构建或CI配置，未运行新的Python测试或headless构建；文档按格式、链接、来源和差异核验，纯文档交付不需要重跑客户端回归。
- #251仍需修攀爬观察、时钟与边界后双端比较；#252～#259继续按各节的具体调整表推进。死亡/复活、Rush完整规则、动态平台、完整竖向输入和资源生产链等缺口仍开放。
- 后续物理对账须按实体和模式选择真正可比较的状态/步长；普通运动的1px、1px/s、1个30ms步阈值不能直接套到不同参考点的Drop或怪物路径生成态。wire还需真实服务器无拉回、入站路径和另一客户端观察证据。
