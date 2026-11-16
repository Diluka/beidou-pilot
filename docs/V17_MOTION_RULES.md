# V17 原版普通运动规则（GUI 基准）

本文整理原版 V17 GUI 客户端（`BeiDou.exe`，SHA256 `1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df`）的**普通地面/普通跳跃/普通空中运动**规则，供 [#239](https://github.com/Diluka/beidou-pilot/issues/239) 的 headless 运动对齐与 [#243](https://github.com/Diluka/beidou-pilot/issues/243) 的 C++ 普通运动预测器共同使用。它是规则依据文档，不定义公共 API；实际实现以对应任务的代码为准。

- 来源任务：[#236](https://github.com/Diluka/beidou-pilot/issues/236)（对齐总任务）、[#237](https://github.com/Diluka/beidou-pilot/issues/237)（参数/规则证据）、[#238](https://github.com/Diluka/beidou-pilot/issues/238)（同步物理末态与真机基线）；上层用户故事 [#176](https://github.com/Diluka/beidou-pilot/issues/176)，算法总任务 [#242](https://github.com/Diluka/beidou-pilot/issues/242)。
- 基线：仓库 `main=639c700`；规则来自 2026-11-16 的静态逆向与 GUI 运行期只读探针。
- 数据版本：真机基线来自 [#238](https://github.com/Diluka/beidou-pilot/issues/238) 分支提交链 `f239e5e`（物理末态/桥工件）→ `1b4d905`（校准脚本跳跃/空中阶段回归修复）；规则动态核验来自 #237 临时只读探针（`tmp/237-native-probe`，基于 #238 提交，不合并），场景为常驻服已有角色 CID 7（有效 SPEED/JUMP=100）、地图 `102000000` 勇士部落水平 foothold。
- 证据分级（全文逐条标注）：
  - **【观测·静态】** 原件反汇编可直接确认（地址为原件 VA，image base `0x400000`，file offset = VA − 0x400000）；
  - **【观测·动态】** 原版客户端运行期只读探针或真机测量确认；
  - **【推导】** 由已确认事实按原版公式计算/手算；
  - **【推断】** 有依据但未直接验证，或只代表观测条件；
  - **【未知】** 未闭环，见第 6 节。

---

## 1. 范围、时钟与单位

### 1.1 适用条件

本文规则适用于：

- 普通地面移动（角色附着在 foothold 上，且 foothold 不是墙）；
- 普通起跳与普通空中下落（无 foothold、非特殊状态）；
- 正常倍率：普通城镇的场地/角色/foothold 材质倍率取构造缺省（第 3 节，已在普通城镇动态确认）；
- 不涉及特殊技能、受击、rush、传送、移动平台、水下/飞行/攀爬。

不适用（见第 6 节）：坡度/滑面与材质特例、下跳 drop-through、特殊跳跃（翻跳/二段跳类）分支、飞行/漂浮/游泳、`0x7046AC` 区域倍率、跳跃标志瞬时改写分支、移动平台。

### 1.2 三种时钟，不能混用

| 时钟 | 周期/行为 | 说明 |
| --- | --- | --- |
| 原版物理逻辑步 | **固定 30ms** | 原版主循环按 30ms 追赶逻辑时间（`0x9F84D0`）；物理位置/速度只在这一步变化。 |
| 宿主/渲染帧 | GUI 约 60Hz；headless 当前世界循环 8ms | 宿主帧只是采样/发布时机，可能读到**同一个物理样本**；不能把宿主帧当物理步。 |
| tick Lua 决策 | 默认 30Hz，gear 1/2/3/4 = 10/20/30Hz/每个宿主更新 | 决策频率独立于物理；不得用 Lua 回调间隔积分，见 [TICK_FREQUENCY](TICK_FREQUENCY.md)。 |

**观测事实**：

- 【观测·动态】每个真实角色物理更新对应唯一 `physics.update_id`，`step_ms` 恒为 30；静止跳 `vy` 序列首样本 −495，之后每新增一个 `update_id` 严格 +60（连续 17 步）。约 40% 的宿主采样与上一帧 `update_id` 相同、物理位姿不变（`tmp/236-validation/gui-baseline2/NOTES.md` 第 1、2 条）。
- 【观测·动态】`character.physics` 是未插值、未圆整的物理末态；`character.x/y` 是显示缓存（整数插值），`character.velocity` 是区间均速，均不能当物理量。例：空中样本 `physics.y=1219.25` 而显示 y=1226（同上第 3 条）。

### 1.3 单位与符号

- 位置：地图像素 px，`x` 向右、`y` 向下；速度 px/s；加速度 px/s²；时间秒。
- 普通物理步 `dt = 0.030` 秒；这是积分时间，不是宿主发布间隔。
- 符号：
  - `B[off]`：原版物理系数表（`B = *(P+8)`，`P = *(0xBEBFA0)`）中字节偏移 `off` 的 double；数组下标 = `off/8`（第 2 节）。
  - `C` / `FA` / `FM`：角色属性对象 `V+0x1A8` / 场地属性对象 `V+0x1A0` / 附着 foothold 的材质对象 `foothold+0x28`（第 3 节）。`V` 为 VecCtrl 基址（`*(CUser+0x11A4) − 0xC`）。
  - `sin`/`cos`：foothold 单位方向向量的 y/x 分量（`foothold+0x38 = dy/len`、`foothold+0x30 = dx/len`）。普通平地 `sin=0, cos=1`。
  - `Vmax`、`F_walk`、`F_brake`、`a_brake` 等见第 4 节。

---

## 2. 物理参数表（Physics.img → 系数表）

### 2.1 加载入口

- 【观测·静态】原版：`P = *(0xBEBFA0)` 是物理管理器单例，`B = *(P+8)` 是 19 个 double 的系数表；管理器构造/装载函数 `0xA43433`（外层类构造 `0x4B3C18` 在 `0x4B3C4E` 调用，P 是外层对象 `+0x10` 的内嵌对象），用 UTF-16 `"Map/Physics.img"`（VA `0xB4034C`）打开 IMG，逐键写入 B 的固定偏移。
- 【观测·动态】运行期只读探针确认：19/19 键值与 `Data/Map/Physics.img` 的 sourceOrder 完全一致（`tmp/237-params/dynamic-evidence.md` 第 1 条）。
- 本仓库 headless 侧要求：参数只来自**本端**只读资源 `nl::nx::Map["Physics.img"]`（`Util/ImgFiles.cpp` 注册，`headless/src/ImgResourceFile.cpp` 保留 real 节点），按同一资源、同一顺序建表；不读取 GUI 进程内存、不调用原版管理器、不写死校准 JSON（#239）。
- 缺键/非法值：当前资源 19 键全部为 real；原版 loader 每键在栈上带一个默认 double `0.0` 的实参，但节点缺失/类型不符时的回退路径未逐指令闭环（第 6 节 G6）。headless 实现按“必需键缺失或非有限值 = 资源错误”处理，不假设“缺键 = 1.0/0.0”。

### 2.2 19 键完整映射

`B` 偏移、实测值与单位如下（值同时来自资源只读解析与运行期探针，二者一致）：

| # | Physics.img 键 | B 偏移 | 实测值 | 单位 | 普通 profile 用途 |
| ---: | --- | ---: | ---: | --- | --- |
| 1 | walkForce | +0x00 | 140000 | mass·px/s² | 行走力（/mass → 1400px/s²） |
| 2 | walkSpeed | +0x08 | 125 | px/s | 平地最大速度基值 |
| 3 | walkDrag | +0x10 | 80000 | mass·px/s² | 松向制动/摩擦（/mass → 800px/s²） |
| 4 | slipForce | +0x18 | 60000 | mass·px/s² | 特例：滑面/坡度 |
| 5 | slipSpeed | +0x20 | 120 | px/s | 特例：滑面/坡度 |
| 6 | floatDrag1 | +0x28 | 100000 | mass·px/s² | 特例：漂浮 |
| 7 | floatDrag2 | +0x30 | 10000 | mass·px/s² | 普通空中横向力/阻力（必需） |
| 8 | floatCoefficient | +0x38 | 0.01 | 无量纲 | 普通空中松向阻力系数（必需） |
| 9 | swimForce | +0x40 | 120000 | mass·px/s² | 特例：游泳 |
| 10 | swimSpeed | +0x48 | 140 | px/s | 特例：游泳 |
| 11 | flyForce | +0x50 | 120000 | mass·px/s² | 特例：飞行 |
| 12 | flySpeed | +0x58 | 200 | px/s | 特例：飞行 |
| 13 | gravityAcc | +0x60 | 2000 | px/s² | 普通重力加速度 |
| 14 | fallSpeed | +0x68 | 670 | px/s | 下落终速（乘场地重力倍率） |
| 15 | jumpSpeed | +0x70 | 555 | px/s | 起跳速度基值（乘 JUMP 比例 / 场地倍率） |
| 16 | maxFriction | +0x78 | 2 | 无量纲 | 摩擦倍率上限 |
| 17 | minFriction | +0x80 | 0.05 | 无量纲 | 摩擦倍率下限 |
| 18 | swimSpeedDec | +0x88 | 0.9 | 无量纲 | 特例：游泳/特殊状态 |
| 19 | flyJumpDec | +0x90 | 0.35 | 无量纲 | 特例：飞行跳跃 |

- 普通 profile 最小必需集：walkForce、walkSpeed、walkDrag、gravityAcc、fallSpeed、jumpSpeed、minFriction、maxFriction，以及 **floatDrag2、floatCoefficient**（普通空中横向控制与松向阻力）。其余 9 项为特例，只加载校验、不因存在就启用特例分支。
- 【观测·静态】各键的读取/写入指令地址见 `tmp/237-params/raw/key-to-table-offset.txt`；已锚定项 walkSpeed→+8、gravityAcc→+0x60、fallSpeed→+0x68、jumpSpeed→+0x70 与双端交叉证据一致。

---

## 3. 属性对象与缺省倍率

普通运动除全局系数表外，还读取三个倍率对象。**地图 IMG 数据没有物理键，缺省发生在原生构造函数里**（第 3.3 节），不能把“资源里缺某键”当缺省来源。

### 3.1 角色属性对象 C = V+0x1A8

- 【观测·静态】对象为 0x90 字节、带 vtable 与引用计数，11 个 `TSecType<double>` 字段从 `+0x0C` 起每 0x0C 一个；构造 `0x4FE802`，CUser 在 `0x948C27` 构造一份并更新（`0x94D3D9`）。
- 【观测·动态】`*(CUser+0x2B64) == V+0x1A8` 在全部样本成立；运行期解密值与构造缺省一致（`tmp/237-params/dynamic-evidence.md` 第 3 条）。

| 偏移 | 构造缺省 | 含义 | 普通运动用法 |
| --- | ---: | --- | --- |
| +0x0C | 100.0 | mass | `F/mass·dt` 的分母；普通重力中约掉 |
| +0x18 | 1.0 | 行走力角色倍率 | 仅当 `FM[+0x18]==1.0 && FM[+0x24]==0.0` 时使用，否则用 1.0 |
| +0x24 | 1.0 | SPEED 有效倍率 | `= 生效 SPEED/100`（更新函数 `0x94D3D9` 以 `int×0.01` 写入） |
| +0x30 | 1.0 | 摩擦/制动倍率 | 乘入 walkDrag |
| +0x3C | 0.9 | 未在普通 profile 使用 | 特殊/坡度分支 |
| +0x48 | 1.0 | JUMP 有效倍率 | `= 生效 JUMP/100`；起跳冲量与空中跳跃分支 |
| +0x54 | 1.0 | — | 特例分支 |
| +0x60 | 1.0 | — | 更新函数内由 +0x6C 拷贝 |
| +0x6C | 1.0 | 特殊跳跃倍率 | 特例分支（`0x7046AC!=0`） |
| +0x78 | 0.0 | 特殊空中谓词标志 | `>0` 时禁用普通空中物理（见 4.4 谓词） |
| +0x84 | 0.0 | 特殊下跳/落地倍率 | 特例分支 |

- 更新来源：【观测·静态】`0x94D3D9` 恒定写 `+0x18=1.0`、`+0x30=1.0`；`+0x6C = int×0.01`；`+0x60 ← +0x6C`；`+0x24 ← +0x60`（SPEED）；`+0x48 = int×0.01`（JUMP）；其余字段另有状态来源。mass 在普通运动中按构造值 100。
- 历史未闭环项 G2 现已由动态探针闭环；仅“其他地图/特殊状态下该对象数值是否仍为缺省”未覆盖。

### 3.2 场地属性对象 FA = V+0x1A0

- 【观测·静态】`V+0x1A0 = *( *(0xBEBFA0) + 0xAC )`；VecCtrl 构造清 0，初始化/状态设置路径（`0x9B1506`/`0x9B1511`、`0x9B197E`/`0x9B198F`）重新赋值为该指针。
- 【观测·动态】`*(*(0xBEBFA0)+0xAC) == V+0x1A0` 全部样本成立；普通城镇 `FA[+0x0C]=FA[+0x18]=FA[+0x24]=1.0`（`tmp/237-params/dynamic-evidence.md` 第 2 条）。`FA[+0x00]` 无法离线直读，但实测行走加速度 `140000×1×1/100=1400px/s²` 反证其为 1.0。
- 消费偏移：

| 偏移 | 含义 | 普通 profile 用法 |
| --- | --- | --- |
| +0x00 | 行走力场地倍率 | 乘入 `F_walk`（城镇动态反证=1.0） |
| +0x0C | 通用倍率 | 同时乘入行走力与摩擦制动（城镇=1.0） |
| +0x18 | 特殊空中分支的 sin 参数 | 普通 profile 不使用 |
| +0x24 | 场地跳跃/重力倍率 | 起跳 vy 的除数、重力加速度乘数、下落终速乘数（城镇=1.0） |

- 【未知】`FA` 对象的构造点与 `P+0xAC` 写入点仍未静态定位（原 G1）；普通城镇之外的场地倍率未覆盖。文档不再把 1.0 当“推断缺省”，而是“**普通城镇已动态确认 1.0，其他地图未覆盖**”。

### 3.3 foothold 材质对象 FM = foothold+0x28

- 【观测·静态】对象 0x3C 字节、vtable `0xB40374`、引用计数；构造 `0xA45200`，缺省 `FM[+0x0C]=1.0`（速度/力倍率）、`FM[+0x18]=1.0`（条件标志兼摩擦倍率）、`FM[+0x24]=0.0`（条件标志；非 0 进入坡度方向力调整分支）。
- 【观测·静态】生产者：foothold 构建代码 `0xA446CA` 分配 + `0xA446E9` 构造材质对象，允许以整数×0.01 覆盖 `+0x18/+0x24`；随后 `0xA4534A` 构造 foothold 本体（`+0x28` 存材质并 AddRef；`+0x30=dx/len`、`+0x38=dy/len`、`+0x40=长度`）。
- 【观测·动态】落地样本 `foothold+0x28` 非空，`FM[+0x0C]=1.0`、`FM[+0x18]=1.0`、`FM[+0x24]=0.0`，与构造缺省一致；普通城镇平地不进入坡度/滑面分支。
- 【观测·动态】地图数据无物理键：只读解析 `Data/Map/Map/Map1/102000000.img`，`info` 只有 bgm/cloud/fieldLimit/forcedReturn/hideMinimap/mapMark/mobRate/onUserEnter/returnMap/swim/town/version；每个 foothold 只有 `x1,y1,x2,y2,prev,next`；`MapHelper.img` 顶层只有 AvatarMegaphone/mark/minimap/portal/weather/worldMap。**缺省发生在 `0xA45200` 构造层**；覆盖源（构建器里的两个整数）静态未定位。
- 普通 profile 基线：`FM = { +0x0C:1, +0x18:1, +0x24:0 }`。

### 3.4 实现要求

参数与倍率必须集中一处（#239 规划中的 `V17PhysicsParameters` 与本端运动状态组装），不能在算法里散落 1400/800/125 等常量。场地/材质倍率在普通城镇取已确认的 1.0；其他地图未核验前只阻止该地图的对齐断言，不伪造倍率。

---

## 4. 普通运动规则（符号化公式 + 伪代码）

### 4.1 公共定义

```text
# 原版力/速度积分 helper（0x9B2BCB）：
Helper(v, F, mass, limit, dt):
    if limit < 0: return v
    if F > 0:
        if v >= limit: return v
        v += F/mass*dt
        return min(v, limit)
    else:                                   # F <= 0
        if v <= -limit: return v
        v += F/mass*dt
        return max(v, -limit)

# 向零衰减，越零归零：
DecayToZero(v, a, dt):
    if v > 0: return max(0.0, v - a*dt)
    if v < 0: return min(0.0, v + a*dt)
    return 0.0

# 脱地位置转换（0xA634A7 CRT 浮点→整数）：
RoundMode(x): 见 4.3 脱地说明；实测支持 floor(y-1)。
```

- 【观测·静态】`Helper` 语义即原版 `0x9B2BCB`：limit<0 直接返回；正力夹 `+limit`、负力夹 `-limit`；对已超限初值不强行拉回。
- 【观测·静态】位置积分一律 `pos += (v_old + v_new)/2 · dt`：地面分支在 foothold 局部坐标积分后再投影世界坐标（`0x9B23F2` 末段 + `0x9B1646`），空中分支直接在世界 x/y 上积分（`0x9B2C3C` 末段）。

普通 profile 的倍率默认值（普通城镇，已动态确认）：`mass=100`、`C[+0x18]=1`、`C[+0x24]=生效 SPEED/100`、`C[+0x30]=1`、`C[+0x48]=生效 JUMP/100`、`FA[+0]=FA[+0x0C]=FA[+0x24]=1`、`FM[+0x0C]=1`、`FM[+0x18]=1`、`FM[+0x24]=0`。

派生量（使用前两个公共公式）：

```text
Vmax(foothold, dirAdj) = B[+0x08] * FM[+0x0C] * C[+0x24] * (1 + sin² * dirAdj)
    # 地面动力学调用 dirAdj = 0 → ±125·S/100
    # 起跳 boost 调用 dirAdj = (input*sin < 0) ? -1 : +1
F_walk  = B[+0x00] * FM[+0x0C] * forceRatio * FA[+0x00] * input
    # forceRatio = (FM[+0x18]==1.0 && FM[+0x24]==0.0) ? C[+0x18] : 1.0
k_brake = clamp(FA[+0x0C] * C[+0x30] * FM[+0x18], B[+0x80], B[+0x78])
    # k_brake < 1.0 时再 ×0.5；k_brake==0 时回退 B[+0x10]*0.2
F_brake = k_brake * B[+0x10]；a_brake = F_brake / mass
```

平地（默认倍率）：`F_walk/mass = 1400px/s²`、`a_brake = 800px/s²`、`Vmax = 125·S/100`。

### 4.2 地面分支（原版 `0x9B23F2` 平地路径）

```text
StepGround(state, input, dt):
    sin, cos = 当前 foothold 单位方向向量（平地 sin=0, cos=1）
    v_t_old = state.vx*cos + state.vy*sin    # 本步起始切向速度
    v_t = v_t_old

    if input == 0:
        # 松向：按 a_brake 向 0 递减，越零归零
        v_t = DecayToZero(v_t, a_brake, dt)
    else:
        # 有方向输入：按方向施加行走力（同向与反向相同，反向不是制动）
        F = B[+0x00]*FM[+0x0C]*forceRatio*FA[+0x00]*input
        v_t = Helper(v_t, F, mass, Vmax, dt)     # 限幅到 ±Vmax，不做越零归零

    # 原版在 foothold 局部坐标里积分位置，再投影成世界坐标（0x9B1646）：
    local_pos += (v_t_old + v_t) * 0.5 * dt              # 梯形积分（局部坐标）
    world_pos = foothold.origin + local_pos * (cos, sin)  # (x1,y1) + 局部位置×方向
    world_v   = v_t * (cos, sin)                          # 切向速度 → 世界速度
    # 完整段碰撞扫掠（墙/边缘/贴地/离地）后提交；见 4.5
```

> 实现提示（给 #239/#243）：原版在局部坐标积分、投影时才产生世界坐标；直线 foothold 上可以等价地用世界坐标 + 单位切向投影实现，但 foothold 连接/边缘仍需按碰撞扫掠处理。预测器应保留同一“局部→世界”投影语义，避免把显示坐标当物理坐标。

**关键行为与真机一致**：

- 【观测·动态】从静止持续方向：`vx = 0 → 42 → 84 → 125`（第 3 步被限幅），之后稳态 125。
- 【观测·动态】**反向 = 方向行走力，而非制动**：从 +125 按反方向输入，序列 `125 → 83 → 41 → −1 → −43 → −85 → −125`，每步 −42（=1400×0.03），最后被 −125 限幅。
- 【观测·动态】松向才使用制动：`125 → 101 → 77 → 53 → 29 → 5 → 0`，每步 −24（=800×0.03），第 6 步越过 0 归零。
- 【观测·静态】分支位置：`0x9B29B9` 读取方向输入；`input != 0` 走 `0x9B2A1E` 一带以 `F_walk`（已含输入符号）调用 `Helper` 的路径；`input == 0` 走 `0x9B289B` 的向零递减路径。静态与真机一致。
- 修正说明：本仓库 #237 早期内部稿与 #239 设计稿曾把“逆输入”也写成制动分支；以真机数据（每步 −42 而非 −24）和本次重读汇编为准，**反向输入按方向行走力处理**。
- 坡度：`sin != 0` 时的方向力调整、`slipForce/slipSpeed` 分支不在本文范围（第 6 节）。
- 【观测·静态】原版地面分支还包含 `0x7046AC` 谓词为真时对行走力再乘 `B[+0x88]`；普通城镇未见生效（第 6 节 G4），普通 profile 按不生效处理。

### 4.3 普通起跳

顺序与原版一致：**脱地 → 设垂直冲量 → 横向 boost → 截顶 → 本步按空中分支积分**。

```text
StepJump(state, input, dt):
    fh = 当前 foothold
    # 1) 脱地（0x9B44C3 固定顺序）
    state = DetachFoothold(state)
    # 2) 垂直冲量
    state.vy = -B[+0x70] * C[+0x48] / FA[+0x24]
    #    special 状态为真时 vy *= 0.7（0xAFE7F8）；普通 profile 假定 special 为假，不实现
    # 3) 横向 boost + 截顶（顺序固定）
    if input != 0:
        dirAdj = (input*sin < 0) ? -1 : +1
        Vmax = B[+0x08]*FM[+0x0C]*C[+0x24]*(1 + sin²*dirAdj)
        if input*state.vx < 0.8*Vmax:
            state.vx += input*0.8*Vmax           # 阈值与增量都是 0.8·Vmax
        if input*state.vx > Vmax:
            state.vx = input*Vmax                # 截顶
    # 4) 同一物理步进入空中积分（重力在起跳步即生效）
    return StepAir(state, input, dt)
```

**脱地顺序（`0x9B44C3`，静态+动态）**：

1. 把 foothold **局部位置**（原版 `V+0xE0`，切向坐标）夹到 `[0, foothold+0x40 长度]`，再由原版 `0x9B1646` 把局部位置/局部速度投影为世界 `x/y/vx/vy`（`world = foothold(x1,y1) + local×(cos,sin)`、`world_v = v_local×(cos,sin)`）；
2. 世界 X 夹到 foothold 的水平范围 `[x1, x2]`；
3. `y = RoundMode(y - 1.0)`；
4. **最后**清空附着 foothold（进入空中）。

**真机锚点**：

- 【观测·动态】起跳垂直初速 `−555 px/s`（JUMP100）；同一步末首个空中样本 `vy=−495`（起跳步已加 +60），之后每步 +60。
- 【观测·动态】满速（125）方向跳：`input·vx = 125 ≥ 0.8·Vmax = 100`，不 boost，截顶后仍 125。
- 【推导】静止+方向同 tick：`vx = 0 + 0.8·125 = 100`（#236 旧 GUI 样本首个离地样本 vx=100；本轮未重采，见第 6 节）。
- 【推导】已有同向 20：`20 < 100` → `vx = 120`（加 boost，不是“设最低值”）；已有同向 110：不 boost、不截顶 → 110；已有 130：不 boost，截顶到 125。
- 【观测·动态】脱地 `y−1`：起跳前物理 y=1236.7，步末 y=1219.25；`floor(1236.7−1)=1235`，减去本步梯形位移 15.75 得 1219.25。**真机数据支持向下取整/截断**（正 y 下 floor 与 trunc 等价）。`0xA634A7` 的精确 FPU 舍入模式仍未逐指令闭环（第 6 节 G7）；实现按 `floor(y−1)` 对齐实测。

### 4.4 普通空中

普通空中分支只在下列谓词全部成立时使用（否则是特殊/飞行/漂浮分支，不在本文范围）：

```text
普通空中谓词（0x96C1D3）：
    V+0x110 == 0（无 foothold）
    && 0x7046AC(V) == 0
    && vtable[+8](V) == 0
    && C[+0x78] <= 0
```

```text
StepAir(state, input, dt):
    vx_old, vy_old = state.vx, state.vy
    limit = B[+0x68] * FA[+0x24]                    # 下落终速，平地 670

    # 1) 重力：force = mass·B[+0x60]·FA[+0x24]；Helper 内 v += F/mass·dt 并夹到 ±limit
    vy = Helper(vy_old, mass*B[+0x60]*FA[+0x24], mass, limit, dt)

    # 2) 横向控制
    drag2 = FA[+0x0C] * B[+0x30]                    # 平地 10000
    if input != 0:
        F = input * 2.0 * drag2                     # 平地 ±20000 → ±200px/s²
        limit2 = (B[+0x08]/B[+0x00]) * drag2        # 平地 ≈ 8.93px/s
        vx = Helper(vx_old, F, mass, limit2, dt)    # 不越零归零：反向穿过 0 后停在 ∓limit2
    else:
        if vy < limit:
            F = FA[+0x0C] * B[+0x30] * B[+0x38]     # 平地 100 → 1px/s²
            vx = DecayToZero(vx_old, F/mass, dt)
        else:
            F = FA[+0x0C] * B[+0x30]                # 平地 10000 → 100px/s²（终速后的截断分支）
            vx = DecayToZero(vx_old, F/mass, dt)

    # 3) 梯形位移
    pos += ((vx_old, vy_old) + (vx, vy)) * 0.5 * dt
    # 4) 空中完整段扫掠：墙 → 落地 → 平台连接；落地在同一步提交（4.5）
```

**真机锚点**：

- 【观测·动态】重力每步 `Δvy = +60`（2000×0.03），静止跳全程 17 步连续 +60。
- 【观测·动态】**空中松向**：松方向后 vx 每步仅减约 0.03（125→124.97→124.94…），即约 1px/s²，不是保持、也不是 200px/s²。
- 【观测·动态】**空中反向**：每步 vx 减 6（125→119→113→…→47），即 200px/s²；不越零归零，穿过 0 后最多到 ∓8.93（限幅）。
- 【观测·动态】起跳步首样本 `vy=−495`，与“起跳步先设 −555 再加一步重力”一致。
- 【观测·动态】静态公式中的跳跃标志瞬时改写分支（`vy>0 && V+0x17C!=0 → vy = V+0x184·jumpSpeed·0.001`）在静止方向跳全程 `V+0x17C=0`，未命中；普通跳跃下落按常规重力（第 6 节 G3）。

### 4.5 落地/附着与位置提交

- 【观测·静态】`CVecCtrl::Update（0x9B19D0）`：先按有无 foothold 分派地面/空中分支，动力学写回位置/速度后，用本步新位置做碰撞/foothold 查找，把新 foothold 交给状态设置（最终写 `V+0x110`）。因此**位置与落地/离地在同一个 30ms 步内提交**，不存在“下一步才确认落地”的旧相位。
- 【观测·动态】`physics.update_id` 每次真实物理更新 +1；起跳/落地的首个样本与该步末态一致（首离地样本 vy=−495 已含本步重力），同 `update_id` 的重复宿主帧物理位姿不变。
- 空中落地：扫掠判定接触后，vy 归零并按着陆平台切线投影/截断速度，同一提交内切换站立/行走状态；地面走出边缘则同一步转为空中。

### 4.6 静态推导与真机动态修正对照（重要）

本仓库 #237 早期内部稿基于静态反汇编做过若干推断，真机只读数据修正如下；实现与预测器以“动态确认”列为准：

| 项目 | 静态推导/早期表述 | 真机动态确认 | 结论 |
| --- | --- | --- | --- |
| 地面反向输入 | 早期内部稿把“逆输入”也写成向零制动（800px/s²） | 每步 −42px/s（=1400×0.03），从 +125 到 −125 对称加速（`tmp/237-params/dynamic-evidence.md` 第 7 条） | **反向 = 方向行走力**；只有 input==0 才制动 |
| 脱地 `y` 取整 | 早期推断 `round_mode` 典型四舍五入 | y=1236.7 → 步末 1219.25，与 `floor(y−1)` 减梯形位移一致（`gui-baseline2/NOTES.md` 第 8 条） | 按 **floor(y−1)** 实现；精确 FPU 舍入模式仍列为 G7 未闭环 |
| 空中松向 | 静态公式给出阻力 `FA[+0x0C]·B[+0x30]·B[+0x38]/mass` | vx 每步 −0.03，即 ≈1px/s²（同上第 9 条） | 静态公式与真机一致 |
| 空中反向 | 静态公式给出 200px/s²、限幅 ≈∓8.93 | 每步 −6（=200×0.03），不越零归零，限幅 ∓8.93（同上第 10 条） | 静态公式与真机一致 |
| 出站 MOVE_PLAYER | 静态未定位构造点/语义（G5） | opcode 0x0029，约 500ms 批量一包，末尾 4 字节=当前 x,y（`tmp/237-params/dynamic-evidence.md` 出站移动包一节） | 不改 wire 值；只把位置包节奏收拢到 30ms 提交（第 6 节 G5） |

---

## 5. 真机测量锚点（GUI 基准）

数据来源：`tmp/236-validation/gui-baseline2/NOTES.md` + `summary.json`（本地证据，不随仓库分发）；#237 动态只读探针：`tmp/237-params/dynamic-evidence.md`、`tmp/237-probe/evidence/native-probe.jsonl`、`tmp/237-probe/analyze.py`。场景：常驻服授权已有角色 CID 7 XiaobeiAI（10 级新手，有效 SPEED/JUMP=100），地图 `102000000` 勇士部落城镇，水平 foothold `x=2106..2191,y=1239`（`2191..2279` 有 4px 微坡，比较时剔除）。

| 场景 | 真机观测值 | 对应规则 |
| --- | --- | --- |
| 平地行走加速 | vx：0 → 42 → 84 → 125（第 3 步限幅），之后 125 | 4.2，1400px/s² + Vmax |
| 松向制动 | 每 30ms −24（125,101,77,53,29,5,…），越零归零 | 4.2，800px/s² |
| 地面反向 | 每 30ms −42（125,83,41,−1,−43,−85,−125） | 4.2，方向行走力 1400px/s² |
| 普通起跳 | launch −555；首个空中样本 −495；之后每步 +60（连续 17 步） | 4.3/4.4 |
| 满速方向跳 | 保持 125（`input·vx=125 ≥ 0.8·Vmax`，不 boost） | 4.3，boost 阈值/截顶 |
| 脱地 y−1 | 起跳前物理 y=1236.7 → 步末 1219.25；`floor(y−1)=1235` 减梯形 15.75 | 4.3，脱地顺序 |
| 空中松向 | 每步 −0.03（≈1px/s²） | 4.4，松向阻力 |
| 空中反向 | 每步 −6（200px/s²），不归零，限幅 ∓8.93 | 4.4，横向力/限幅 |
| 物理更新与时钟 | `update_id` 与 30ms 物理步 1:1，`step_ms`=30；约 40% 宿主采样为重复 `update_id` | 1.2 |
| 显示与物理 | `character.x/y` 为显示缓存、`character.velocity` 为区间均速；`physics.*` 才是同步物理事实 | 1.2 |

数据版本与限制：

- 【观测·动态】上述基线在 #238 分支提交 `f239e5e`（GUI 镜像含同提交 Windows 桥工件）；校准脚本在 `1b4d905` 修复“`on_ground=false` 被吞成 nil 导致跳跃/空中场景 timeout”的回归后复跑通过。
- 本轮未重采：静止+方向同 tick 的 boost=100 场景（用 #236 旧日志）、长落体终速 670、坡度/材质、移动平台、下跳、游泳/飞行。

---

## 6. 未覆盖/需要其他任务继续取证

供 [#243](https://github.com/Diluka/beidou-pilot/issues/243) 判断预测器覆盖面：以下项目**不得**先按假设实现或对外承诺；需要时先补证据。

| 项目 | 现状 | 对预测器/#239 的影响 | 需要 |
| --- | --- | --- | --- |
| 场地倍率（普通城镇之外） | 普通城镇 `FA[+0]=[+0x0C]=[+0x24]=1.0` 已动态确认；对象构造/`P+0xAC` 写入点仍静态未定位（G1） | 预测器只在已确认地图上宣称正常倍率；其他地图可能不同 | 多地图（城镇/野外/水域/飞行区）动态只读 `*(P+0xAC)` 各字段 |
| 跳跃标志瞬时改写（G3） | 静止方向跳未见 `V+0x17C!=0`；改写分支 `vy>0 && V+0x17C!=0 → vy = V+0x184·jumpSpeed·0.001` 的触发场景与 `V+0x184` 写入者未知 | 普通跳跃下落不受影响；特殊状态可能偏离 | 更多状态组合的只读采样；先按不命中的普通 profile 承诺 |
| `0x7046AC` 语义（G4） | 未还原；普通城镇未见额外倍率生效（松向阻力与默认公式一致） | 特殊地图/区域可能改变行走力/空中分支 | 还原该谓词（场地对象 `+0x30/+0x3C` 容器/点判定）并动态核对 |
| 出站 MOVE_PLAYER（G5） | 动态：opcode 0x0029，约每 500ms 批量一包（size 44–100，末尾 4 字节=当前 x,y s16）；候选 fh/stance/duration 字段未逐字节闭环，duration 候选 8–510ms；另有 8 字节非移动包 0x00C5 ~33Hz | **不改 wire 值**：duration 继续 1、lastx/lasty 继续投影语义；#239 只把位置包发出时机从 8ms 收拢到 30ms 提交，验收以真机无拉回为准 | 若未来要改成批量编码，先做逐字节解码（元素边界、duration 单位/来源、flush 触发） |
| 坡度/滑面与材质特例 | 静态有 `slipForce/slipSpeed`、`FM[+0x24]!=0` 分支；普通城镇未进入 | 斜坡、滑面地图的加减速/限速可能不同 | 特例地图动态采样 + 逐分支公式确认 |
| 游泳/飞行/漂浮 | 只加载参数；普通空中谓词不成立时进入特殊分支 | 水域/飞行区完全不适用本文公式 | 单独取证，不并入普通 profile |
| 特殊跳跃（含 0.7 倍、`C+0x6C/+0x78/+0x84`） | 静态分支存在，普通条件不触发 | 预测器不得把普通公式用于特殊技能 | 专门任务 |
| 移动平台、下跳 drop-through | 静态机制未闭环（原生坑位/忽略平台状态未定位） | 平台携带速度、下跳落点不可预测 | 动态探针 + 实现设计 |
| 长落体终速 670 实测 | 未在真机重采（公式/参数已确认） | 预测器可用公式，但缺端到端实测对账 | 有界高空下落场景 |
| 脱地取整模式（G7） | 真机数值支持 `floor(y−1)`；极端小数、负 y 未验证；`0xA634A7` 精确 FPU 舍入模式未逐指令闭环 | 1px 内相位差异；合同容差内可接受，原则上按 floor | 读 FPU 控制字或在更多小数/负坐标下采样 |
| Physics.img 缺键回退（G6） | 当前资源 19 键全 real；原版失败路径未逐指令解码 | 实现按“必需键缺失=资源错误”，无回退 | 无需运行时；实现时显式报错 |
| 静止+方向同 tick boost | 公式与旧样本支持 `vx=100`；本轮未重采 | #239 双端验收时补齐即可 | 重采该场景 |

---

## 7. 证据来源

### 7.1 原件与地址约定

- 原件：`private/client-assets/client/BeiDou-Client/BeiDou.exe`（SHA256 `1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df`），PE i386，静态 image base `0x400000`；本文地址均为原件 VA，file offset = VA − `0x400000`。
- 关键函数地址：

| 用途 | 地址 |
| --- | --- |
| 物理管理器构造 + Physics.img 装载（19 键 → B） | `0xA43433`（外层类 `0x4B3C18`，调用点 `0x4B3C4E`；`[0xBEBFA0]=P` 于 `0xA43456`） |
| 角色属性对象构造 / CUser 侧构造点 / 更新 | `0x4FE802` / `0x948C27` / `0x94D3D9` |
| 角色属性对象引用取回 | `0x94D311`（vtable 槽，vtable `0xB3D1F4`） |
| foothold 材质对象构造 / 构建调用 / foothold 本体构造 | `0xA45200` / `0xA446CA`、`0xA446E9` / `0xA4534A` |
| VecCtrl 构造 / 初始化（`V+0x1A0` 写 `[P+0xAC]`） | `0x9B0F71` / `0x9B12A8`（写入 `0x9B1506`/`0x9B1511`；`0x9B195F` 处 `0x9B197E`/`0x9B198F`） |
| 地面动力学 / 平地限速 | `0x9B23F2` / `0x9B2187` |
| 普通起跳入口 / 正常 foothold 分支 / 脱地 | `0x9B1D3D` / `0x9B1E43` / `0x9B44C3` |
| 空中动力学（普通分支） / 普通空中谓词 | `0x9B2C3C`（普通分支 `0x9B2CCF`） / `0x96C1D3` |
| 力/速度积分 helper | `0x9B2BCB` |
| 原版主循环 30ms 追赶 | `0x9F84D0` |
| 原版发包入口 | `0x49637B`（既有 GUI 桥 hook 引用） |

- 关键常量（只读 .rdata）：`0.001`=`0xAF0E10`、`0.01`=`0xAF14F0`、`0.8`=`0xAF0D40`、`0.7`=`0xAFE7F8`、`0.5`=`0xAF0D48`、`0.2`=`0xAF1628`、`0.3`=`0xAFE800`、`1.3`=`0xAFE898`。
- `RoundMode` 转换函数 `0xA634A7`；`sqrt` `0xA622D4`；`fabs` 辅助（按实现）`0xA6203F`。

### 7.2 证据文件（`tmp/` 为本地调查证据，不随仓库分发）

- 静态规则与完整参数映射：`tmp/237-params/static-evidence.md`、`tmp/237-params/raw/`（`asm-physics-loader-0xA43433.txt`、`key-to-table-offset.txt`、`physics-img-keys.txt`、`consumer-offsets.txt`、`asm-ground-dynamics-0x9B23F2.txt`、`asm-ground-vmax-0x9B2187.txt`、`asm-jump-*.txt`、`asm-air-normal-0x9B2CCF.txt`、`asm-force-helper-0x9B2BCB.txt`、`asm-detach-0x9B44C3.txt`、`asm-foothold-*.txt` 等）。
- 既有原件证据：`tmp/tick-motion-gui/`（`motion-source-report.md`、`decompile-*.c`、`*-assembly.txt`、`ground-speed-formula-assembly.txt`、`normal-jump-assembly.txt`、`normal-air-gravity-assembly.txt` 等）。
- 动态只读核验：#237 探针结果 `tmp/237-params/dynamic-evidence.md`、原始 `tmp/237-probe/evidence/native-probe.jsonl`、分析脚本 `tmp/237-probe/analyze.py`。
- 真机物理基线：#238 结果 `tmp/236-validation/gui-baseline2/`（`NOTES.md`、`summary.json`、`*.events.jsonl`、`*.compare-self.json`）、`tmp/236-validation/gui-238/`。
- #239 设计（调度/碰撞/接口规划）：`tmp/239-design/design.md`。

### 7.3 相关 issue

- 对齐总任务：[#236](https://github.com/Diluka/beidou-pilot/issues/236)；上层用户故事：[#176](https://github.com/Diluka/beidou-pilot/issues/176)。
- 本规则依据：[#237](https://github.com/Diluka/beidou-pilot/issues/237)（静态+动态参数/规则/包契约证据）；同步物理末态与真机基线：[#238](https://github.com/Diluka/beidou-pilot/issues/238)。
- 消费方：[#239](https://github.com/Diluka/beidou-pilot/issues/239)（headless 30ms 普通运动对齐）、[#243](https://github.com/Diluka/beidou-pilot/issues/243)（C++ 普通运动预测，父任务 [#242](https://github.com/Diluka/beidou-pilot/issues/242)）。

---

## 8. headless 实现映射

### 8.1 当前 main（仅作对照，不是对齐依据）

- 【观测·静态】基线 `main=639c700` 的 headless 仍是 Journey/HeavenClient 的 8ms 模型：`third_party/maplestory-client/Gameplay/Physics/Physics.cpp` 的每步递推（`.8V+20` → 稳态 100px/s）、`Character/Player.cpp` 的 8ms 步位移；旧参考模型 `max_speed=100 / max_jump_height=74.58` 仍在。
- 因此 `TICK_FREQUENCY.md` 里 headless 的 100px/s / 74.58 只是现状，不是本文规则；实现新模型前不得用 headless 轨迹校验预测器。

### 8.2 #238 已提供的同步物理末态

- #238 已合入 main（PR #241，merge commit `d8f4d84`，最终提交 `1b4d905`；本文件初稿基线仍按 `639c700` 阅读，与 #238 相关的契约以合入后 main 为准）提供 `character.physics` 同步末态契约：字段为 `update_id / step_ms / x / y / velocity{x,y} / on_ground`，x/y 是**未圆整物理脚点**、velocity 是**同一步世界瞬时速度**（未知保持未知，不补零），旧 `character.x/y`（显示缓存）与 `character.velocity`（区间均速）语义保留。
- 该契约是本文规则与真机测量之间的比较基准：#243 预测器与 #239 实现都应按 `update_id` 对齐、只用 `character.physics` 做物理比较（`tmp/236-validation/plan.md` 的观察规则）。

### 8.3 #239 实现状态（进行中）

- 工作树 `feat/239-normal-motion` 正在实现。截至本文初版，已提交参数表接入（`2ae63a7`：新增 `V17PhysicsParameters.{h,cpp}`、`headless/src/main.cpp` 装载接线与参数合同；缺失/非 real/非有限值报带键名的资源错误，不回退旧 Journey 常量）；`V17NormalMotion` 与 `FootholdTree::SweepLocalMotion` 仍在进行。
- 入口目标是：`V17PhysicsParameters`（本端 `Physics.img` 只读参数与校验）、`V17NormalMotion`（普通模式规范状态与本文分支/积分/投影）、`FootholdTree::SweepLocalMotion`（起点 + 完整 30ms 位移的碰撞扫掠），并把 `physics.update_id` 绑定到真实运动提交号、把本地位移包发出时机收拢到 30ms 提交。
- 设计依据见 `tmp/239-design/design.md` §2（模块边界）与 §3（算法）、§4（碰撞）、§6（采样/输入/出包）。
- **实际文件/类/接口指针待 #239 落地后由 lead 在本节补充**；本文不写未实现的函数签名，其他任务不要按假设签名编码。

### 8.4 对 #243 预测器的约束

- 预测器必须复用同一规则和参数来源：本端只读 `Physics.img` + 有效角色/场地/foothold 倍率；不自带硬编码 125/555/2000，不复制 Lua/Python 积分器。
- 30ms 是唯一物理步长；不得按 Lua tick 或宿主帧积分。
- 状态输入必须显式包含：位置/瞬时速度/落地与附着（foothold 或空中）/影响下一步的输入保持与边沿、能力（SPEED/JUMP 等有效值）与适用环境（普通/特例）；不得把 SPEED/JUMP=100 或“普通城镇倍率=1”当任意角色的永真常量。
- 首批覆盖面与缺口按第 6 节声明：普通地面直线/反向/制动、普通起跳/空中/落地可承诺；特殊技能、坡度特例、游泳/飞行、移动平台、下跳等未取证前不得宣称可预测。
- 与真实 GUI 的对账使用 `character.physics` 的 `update_id` 序列，不按 CLI 请求时刻或 Lua 回调数。

---

## 9. 维护

- 本文初版：2026-11-16，撰写基线 `main=639c700`，同日 #238 合并入 main（`d8f4d84`）、最终提交 `1b4d905`；原件 SHA256 上述；#237 动态探针分支 `tmp/237-native-probe`。
- 需要同步更新的时机：#239 落地（补 8.3 实际指针）、#238 合入 main 且契约若有调整、第 6 节任一缺口闭环、原版客户端版本变化（SHA256 变化即作废重取证）。
- 本文只记录已验证事实与明确未闭环项；新增规则请同时更新证据来源与“观测/推导/推断/未知”标注。
