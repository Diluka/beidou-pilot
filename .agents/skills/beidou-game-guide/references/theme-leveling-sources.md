# 主题地图任务推荐：来源与核验范围

[返回任务推荐](theme-leveling.md)。本页只供查证，玩家选路线看推荐正文即可。


整理日期：**2026-11-12**。本地北斗 V17 `Quest.nx` 与公开 [BeiDou-Server `00422c2`][source] 对照；任务名称、等级、前置与资源奖励按基础资源加中文覆盖读取。先对照了蘑菇王城39项任务，再扩大核对到推荐涉及的341项任务：`Check`、`Act` 全部一致，任务名称一致；`QuestInfo` 有一项非推荐任务3905的接取前叙述不同（服务器中文XML为空，本地NX为“3”），其条件与奖励一致。未做游戏实测、计时或到账统计。

任务记录可从 [名称与叙述][questinfo]、[接取与完成条件][check]、[资源奖励][act] 按下表任务号查阅。名称见[中文名称资源][strings]，NPC位置与通路见[地图资源][maps]；脚本发奖或解锁行为要与资源合读，不能把任务说明当作最后结论。

| 地区 | 关键任务号／额外来源 |
| --- | --- |
| 蘑菇王城 | 2300～2310、2312～2338；[引导与传送][mush-intro]、[Boss入口][mush-boss]、[2337长线击杀条件][check]；手套属性在[装备资源][glove] |
| 废都广场 | 2270～2293；[检票口][subway]；自由灵魂之戒在[耳饰资源][earring] |
| 阿里安特 | 3900、3909、3921～3941 |
| 童话村 | 3601～3640，尤其3619～3621、3610～3611 |
| 玛加提亚 | 3300～3359，尤其3329～3330、3347～3349 |
| 武陵／百草堂 | 3800～3844；[鹤的航路][hak] |
| 新加坡／马来西亚 | 4510～4513、4541～4560、4576；[妮妮的旅行目的地][tour]、[奥黛丽的交通][malaysia] |
| 时间神殿 | 3500～3539；[神木村变龙航路][dragon] |
| 新叶城／黄金海滩／上海 | 4913～4915、2058～2061、2157～2161、4100～4109；[新叶城车票][nlc]、[海滩入口][beach] |
| 艾琳森林 | 1206、21749～21753；[毒雾森林入口][ellin]、[活动准入脚本][ellin-event]。任务资源写45～55级，活动默认44～55级、4～6人冒险家；配置可放宽人数和等级，职业限制仍存在。未把职业专属剧情算作通用主题任务 |

尚待确认：当前服务器与资料版本的差异、蘑菇城39级后的地图行为、各Boss实际难度、活动配置对组队准入的覆盖，以及每条线的真实耗时。本文的“优先／顺路”是按任务集中度、前置和标称收益作出的建议，尚非实测效率排行。

[source]: https://github.com/BeiDouMS/BeiDou-Server/tree/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server
[questinfo]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz-zh-CN/Quest.wz/QuestInfo.img.xml
[check]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz-zh-CN/Quest.wz/Check.img.xml
[act]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz-zh-CN/Quest.wz/Act.img.xml
[strings]: https://github.com/BeiDouMS/BeiDou-Server/tree/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz-zh-CN/String.wz
[maps]: https://github.com/BeiDouMS/BeiDou-Server/tree/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz/Map.wz/Map
[mush-intro]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/quest/2300.js
[mush-boss]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/1300013.js
[glove]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz/Character.wz/Glove/01082254.img.xml
[earring]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz/Character.wz/Accessory/01032075.img.xml
[subway]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/1052007.js
[hak]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/2090005.js
[tour]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/9000020.js
[malaysia]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/9201135.js
[dragon]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/2082003.js
[nlc]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/9201057.js
[beach]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/1002002.js
[ellin]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/2133000.js

[ellin-event]: https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/event/EllinPQ.js
