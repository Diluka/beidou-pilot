# 客户端能力边界与缺口索引

本页说明哪些现有边界会增加AI使用CLI和Lua的成本，并索引已入池的独立用户结果。命令、字段、错误和能力声明仍以[CLI](CLI.md)、[Lua API](LUA_API.md)和[架构](ARCHITECTURE.md)为准；Issue记录最新范围和状态。本次入池不自动启动全部功能开发，也不把所有缺口作为简单玩法或外部游戏AI接入的前置。

## 当前使用边界

- **领域读取与交互动作分别支持。** Lua 已通过按需 `game.observe(domain)` 读取 CLI 已有原生领域，`game.state()` 保持轻量。无头通用交互已采用当前页面与原生控件引用；窗口、商店等覆盖仍按后端能力声明。无头任务合并完整角色包和正常增量，原始进度与关联语义不推断。
- **静态资料与现场事实分别核对。** 名称、恢复属性、NPC范围与地图地形共用配置的原版 IMG 和原生解析库；缺项和未支持值仍明确报告。GUI `talk`使用可核实的图形范围定位，无头交互使用当前原生引用。静态资料可辅助查询、定位与规划，不能替代本端实时对象和结果。
- **基础操作与完成目标不同。** 移动、跳跃、普攻、拾取和按键主要表达原生尝试；派发、释放、收束及游戏效果分别判断。现有`move/climb/portal`已有局部到达检查，`use`等也有部分结果确认；它们尚未覆盖完整跨层旅行、目标回收及战斗效果。
- **后端实现范围不同。** 无头支持普通装备槽位操作、死亡观察、明确请求的普通复活及首批战士1001004/1001005原生技能。通用交互覆盖普通服务端脚本页及由客户端资料、当前状态形成的本地任务页；未支持条件和复杂选择不提供确认控件，商店、加点和其他技能仍按各自声明。移动与攻击可同窗持有意图，动画与物理继续沿原生规则。补齐能力不复制无消费者的图形键盘/快捷栏。
- **热改策略与更新原生组件成本不同。** Lua源码和活动任务已支持在线追加/替换；原生DLL或二进制变化仍需要构建并按生命周期重新加载。现有Docker、工件清单、指纹核验和实例复用继续使用，准备成本改进不承诺安全DLL热卸载或零重启。

## 需求索引

| 用户需要的结果 | 当前成本或边界 | 跟踪 |
| --- | --- | --- |
| Lua直接消费已有领域事实 | `game.observe(domain)` 已接入原生领域；保留各端支持、来源及非实时限制 | [#40](https://github.com/Diluka/beidou-pilot/issues/40) |
| 同会话连续完成GUI交互与养成 | GUI Lua 已接入普通唯一槽位穿戴、AP/SP及三种必要窗口；NPC/商店仍按各自范围，batch不承担动态判断 | [#41](https://github.com/Diluka/beidou-pilot/issues/41) |
| 可靠打开可见近距NPC | GUI仍需可核实图形范围与有效目标；无头使用当前原生引用 | [#42](https://github.com/Diluka/beidou-pilot/issues/42) |
| 知道箱子等对象当前是否存在及已知状态 | 原生内部实现不等于公开结构化观察 | [#43](https://github.com/Diluka/beidou-pilot/issues/43) |
| 沿已知路线跨层、进入相邻地图并确认到达 | 旅行函数库可组合有界路段；首条示例固定50000东上层到1000000西入口及返回，其他路线仍需明确地形事实与真实验收 | [#44](https://github.com/Diluka/beidou-pilot/issues/44) |
| 读取真实动作前提、收束和移动能力 | ready不等落地，GUI部分状态未知 | [#45](https://github.com/Diluka/beidou-pilot/issues/45) |
| 回收指定物品或金币并确认收益 | 普通pickup只尝试；物品看入包、金币看余额 | [#46](https://github.com/Diluka/beidou-pilot/issues/46) |
| 知道战斗有何原生可核实进展 | 无头提供已收到的服务端目标HP百分比；GUI未知，动作归因仍未知 | [#47](https://github.com/Diluka/beidou-pilot/issues/47) |
| 无头正常对话与接交任务 | 原生通用页面/控件激活；本地任务页来源明确，接交结果仍以当前原生任务和收益验证 | [#48](https://github.com/Diluka/beidou-pilot/issues/48) |
| 无头普通商店买卖补给 | 不能在同一无头实例内完成商店流程 | [#49](https://github.com/Diluka/beidou-pilot/issues/49) |
| 无头按明确计划分配AP/SP | Lua/CLI 原生逐点双确认；SP 仅冒险家普通职业点数池，真实效果按对应提交验收 | [#50](https://github.com/Diluka/beidou-pilot/issues/50) |
| 无头正常更换装备 | `game.equip/unequip` 与 CLI 明确槽位操作，按正常库存更新确认；不自动重试未知结果 | [#51](https://github.com/Diluka/beidou-pilot/issues/51) |
| 无头实时观察任务变化 | 完整角色包与正常任务增量共同维护；原始进度与关联语义不猜测 | [#52](https://github.com/Diluka/beidou-pilot/issues/52) |
| 无头施放已学职业技能 | 首批1001004/1001005走原生技能链；其他类型明确不支持 | [#53](https://github.com/Diluka/beidou-pilot/issues/53) |
| 无头按请求安全复活 | 原生死亡事实与单次正常复活已接入；服务端许可及真实覆盖见任务记录 | [#54](https://github.com/Diluka/beidou-pilot/issues/54) |
| 一次资源准备供查询与规划直接消费 | Catalog 直接查询只读原版 IMG，报告实际来源、指纹和未知版本 | [#55](https://github.com/Diluka/beidou-pilot/issues/55) |
| 指定方式和目标后连续狩猎 | `hunt`在单场景内自主找怪与跨平台，支持移动攻击同窗；复杂或无进展地形停止 | [#86](https://github.com/Diluka/beidou-pilot/issues/86) |
| 减少原生试用准备与版本核对成本 | 现有构建已交付，指定版本复用/装配/核对仍需组织 | [#56](https://github.com/Diluka/beidou-pilot/issues/56) |

现有动作摆脱键位配置依赖沿用[#36](https://github.com/Diluka/beidou-pilot/issues/36)，普通药品的首个实施增量由[#39](https://github.com/Diluka/beidou-pilot/issues/39)跟踪。它们不代替各端技能支持声明或结果确认。特定台阶对照继续由[#32](https://github.com/Diluka/beidou-pilot/issues/32)跟踪；已验证的正常路径可继续使用，未确认差异不被写成Native缺陷。

同图其他玩家尚缺公开结构化观察，也已入池[#57](https://github.com/Diluka/beidou-pilot/issues/57)；它支持既有旁观/协作消费，不要求无头提供画面。

## 已有结果与后续验证

在线源码执行与活动任务协作/替换已经交付（#9、#10、#29）；GUI NPC同步输入导致的Lua调度和释放问题已修复（#33 / PR #35）。本页不将这些历史问题继续列为缺失能力。

后续按独立用户结果选择交付；AI决策、长期角色路线与记忆保持在客户端外部，持续控制由Lua和原生执行。各端仅报告本端真实事实，未知/过期/未支持不当作空、零或成功，也不从服务端或另一后端补齐。角色不可逆分配沿已核实计划执行，死亡/复活试验只使用另有明确授权的合适角色。

调试、正式验收和证据复用遵循[开发约定](../AGENTS.md#验收方式)。按实际影响补验对应后端和消费者；不为文档、未变组件或每个PR强制重新升级、重登或重跑整套流程。
