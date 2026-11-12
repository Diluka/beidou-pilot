# Issue 分类标签

本仓库的 Issue 使用两个维度的标签：`需求池` 与领域标签。领域标签用于按能力面筛选和安排优先顺序，不表示排期、授权或开发进度。

## 为什么不用进度标签

`待开发` / `开发中` / `待验收` 一类状态标签需要每次推进时手动同步。实际执行中没人会可靠地回头更新，一段时间后标签会比没有更误导。Issue 的实际进度以 sub-issue 状态、PR 与正文中记录的事实为准，不靠标签表达。

## 领域标签

每个 `需求池` Issue 建单时指定**一个**领域标签，按 Issue 正文的主体判断。领域在建单时固定，之后不随进度变更；若需求范围发生实质变化，重新判断一次。

### 主轴：客户端能力

这四类标签回答的是「AI 干活时会在哪里卡住」，优先安排这些内容的排期。

| 标签 | 含义 | 典型判据 | 当前归属 |
|---|---|---|---|
| `动作能力` | Lua 语义动作怎么真正执行：原生化、键位依赖、准入与真实效果 | 交付物是让某个调用走对执行路径；**动作本身能否执行** | [#36](https://github.com/Diluka/beidou-pilot/issues/36) |
| `状态观察` | 脚本能读到什么事实：动作状态、阻塞原因、移动能力、掉落与背包收益 | 交付物是让脚本读到**可信事实**，而非发起动作 | [#45](https://github.com/Diluka/beidou-pilot/issues/45)、[#46](https://github.com/Diluka/beidou-pilot/issues/46) |
| `对象交互` | 对场景对象发起交互并核对结果：NPC、箱子、商店、门户 | 交付物是「发现对象 → 指向目标 → 交互 → 核对」的统一流程 | [#41](https://github.com/Diluka/beidou-pilot/issues/41) |
| `验收场景` | 主体是取得真实游戏结果，不开发新能力 | 交付物是真实客户端的运行结果、证据与计划推进 | [#8](https://github.com/Diluka/beidou-pilot/issues/8)、[#13](https://github.com/Diluka/beidou-pilot/issues/13)、[#16](https://github.com/Diluka/beidou-pilot/issues/16)、[#22](https://github.com/Diluka/beidou-pilot/issues/22)、[#27](https://github.com/Diluka/beidou-pilot/issues/27)、[#32](https://github.com/Diluka/beidou-pilot/issues/32) |

### 扩展：`游戏AI`

harness、协作、社交、策略消费等扩展方向，以及低频的账号起步流程。这类内容粗粒度维护即可，不急着细分。

当前归属：[#37](https://github.com/Diluka/beidou-pilot/issues/37)、[#60](https://github.com/Diluka/beidou-pilot/issues/60)、[#65](https://github.com/Diluka/beidou-pilot/issues/65)、[#72](https://github.com/Diluka/beidou-pilot/issues/72)、[#73](https://github.com/Diluka/beidou-pilot/issues/73)、[#92](https://github.com/Diluka/beidou-pilot/issues/92)、[#94](https://github.com/Diluka/beidou-pilot/issues/94)、[#149](https://github.com/Diluka/beidou-pilot/issues/149)、[#150](https://github.com/Diluka/beidou-pilot/issues/150)。

## 边界判断

### `动作能力` 与 `状态观察`

按交付物主体判断，而非按代码位置：

- 主体是**让调用走对路径**（如 `game.jump` 不再依赖快捷键绑定）→ `动作能力`。
- 主体是**让脚本读到可信事实**（如读取当前是否在空中、拾取后是否真的入包）→ `状态观察`。

两者在实施时经常互相牵连。例如拾取闭环既涉及执行路径，也涉及入包确认；此时按 Issue 正文承诺的用户结果归类，另一面作为依赖记录在正文中，不另建平行标签。

### `对象交互` 与 `状态观察`

`对象交互` 覆盖「发现对象 → 指向目标 → 交互 → 核对」的完整流程；若只交付「看到对象列表」而不含交互与结果核对，则属于 `状态观察`。

### `验收场景`

判断依据是**有没有新的客户端行为承诺**。取得真实游戏结果、收敛证据与计划推进的父需求归入此类；其下需要新写代码的子任务按子任务自身性质归入其他领域标签，但 sub-issue 默认不加领域标签（见下节）。

## sub-issue 的标签

开发任务是父需求的拆解，默认**不添加**领域标签，继承父需求的分类即可。这样筛选 `label:动作能力` 时得到的是需求清单，不会被大量子任务淹没。

若某个开发任务独立到需要单独按领域筛选（例如跨多个父需求的技术交付），再补加。

## 常用筛选

```text
# 全部待处理需求
is:issue is:open label:需求池

# 需要安排排期的主轴能力
is:issue is:open label:动作能力,状态观察,对象交互,验收场景

# 扩展方向
is:issue is:open label:游戏AI
```

## 维护

- 领域标签在建单时确定，不在开发过程中切换。
- Issue 关闭时保留原标签，便于回溯历史分类。
- 新增领域标签需要先更新本文档并说明判断标准，避免标签膨胀。
