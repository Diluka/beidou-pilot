# Issue 分类与筛选

用 GitHub 原生类型区分 Issue：`Feature` 记录希望新增或恢复的能力，`Bug` 记录已观察到的行为偏差，`Task` 记录可以单独领取和验收的交付。类型不表示开发已获授权。需求写法见[需求共创技能](../.agents/skills/beidou-pilot-requirements/SKILL.md)；排期汇总单和依赖图见[规划技能](../.agents/skills/beidou-pilot-issue-planning/SKILL.md)。

## 领域标签

Feature 和 Bug 各选一个领域标签，按使用者最终得到的结果选，而不是按实现语言选。范围实质变化时可以重新判断，关闭时保留分类。子 Task 默认不重复加父单的领域标签；需独立按领域筛选的交付可单独标注。

| 领域 | 按什么区分 |
|---|---|
| `动作能力` | 调用一个动作并产生实际效果，例如请求正常复活。 |
| `状态观察` | 读取可信事实，例如脚本能否识别角色已死亡。 |
| `对象交互` | 面向 NPC、箱子或门户等对象发起交互并核对结果。只读取对象列表归「状态观察」。 |
| `游戏AI` | 用客户端组合玩法或策略，例如完成社交、养成或账号起步流程。 |
| `验收场景` | 交付真实游戏场景的证据和结论，不承诺新的客户端行为。 |

讨论优先级时，先看客户端能力和验收场景，再看扩展玩法；实际顺序由维护者在汇总单中决定。新增领域标签前，先在上表写出它与相邻领域的判据。

## 汇总单标签

`汇总单` 标记维护者看依赖图、手动选下一张执行单的入口。单个需求拆分后，原 Feature 或 Bug 保留类型和领域标签，补齐子 Task、依赖图和当前可选项，再加此标签。跨需求的批次汇总也用同一个标签。直接执行的原单不加；仅有子项也不足以成为选单入口。这个标签不表示已开工。

## 常用筛选

- [开放汇总单](https://github.com/Diluka/beidou-pilot/issues?q=is%3Aissue%20is%3Aopen%20label%3A%E6%B1%87%E6%80%BB%E5%8D%95)：`is:issue is:open label:汇总单`。

- [开放功能需求](https://github.com/Diluka/beidou-pilot/issues?q=is%3Aissue%20is%3Aopen%20type%3AFeature)：`is:issue is:open type:Feature`。
- [开放缺陷](https://github.com/Diluka/beidou-pilot/issues?q=is%3Aissue%20is%3Aopen%20type%3ABug)：`is:issue is:open type:Bug`。
- 查看某领域时追加 `label:动作能力` 等条件。维护者可直接指定未拆分的需求，从批次选单时看汇总单；筛选结果不自动派工。
