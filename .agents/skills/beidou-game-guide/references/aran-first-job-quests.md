# 战神一转职业任务攻略

本文依据北斗 V17 固定版本资源和脚本整理，尚未逐项试玩。

## 战神：修炼与情报搜集

一转后从利琳接“新的开始”（21700），分配完全部AP，再到里恩村左侧入口找普奥交付。脚本给的是矛 `1442000`；普奥直接开启下一项。21701～21703依次击杀修炼用绿水灵 `9300341`、花蘑菇 `9300342`、猪猪 `9300343` 各30只；最后一轮脚本解锁连击技能上限。再按任务栏做21704，13级后继续情报线。

| 等级／任务段 | 做法 |
| --- | --- |
| 13级，21705～21712 | 去金银岛找明珠港特鲁，再找特奥；21707收集绿、蓝、红蜗牛壳各10个。到射手村找布鲁斯，依次交花蘑菇角30个、猪尾巴50个；21711击杀玩世不恭的花蘑菇 `9300274` 50只并取得人偶 `4032315` 1个，回报结束第一次情报搜集。21766／21767是木箱调查分支 |
| 18级，21713～21716 | 找魔法密林妖精罗雯：21714击杀绝望绿蘑菇 `1110130` 25只并取得人偶 `4032316`；21715调查会说话的树，再完成报告。21717、21718是19、20级的罗雯支线，各击杀指定绿蘑菇 `9101000` 100只并分别取得人偶 `4032317`、`4032318` |
| 22～25级，21719～21725 | 接21719会立即完成并传送，继续21720；23级起找勇士部落布吉调查。21722的条件是古木妖 `9101002` **100只**，叙述写200只；21723到 `101030101` 打遗迹取得人偶 `4032319` 5个。完成21724；21725为布吉支线 |
| 28～29级，21726～21732 | 找林中之城日吉：21727击杀僵尸蘑菇 `9101001` **300只**并取得人偶 `4032321`；21728调查火独眼兽洞穴入口，再回报。进行21729时找奇怪的石像，21730交火独眼兽尾100个。21731的人偶师目标为 `9300344` 1只与文件 `4032322` 1份；21732带文件 `4032341` 回利琳 |

人偶师入口暗号为 **弗朗西斯是天才傀儡师！**，包含全角叹号。入口检查的击杀 ID 与任务要求不同，相关刷怪地图与入口地图的衔接尚未实测；卡住时记录任务状态、当前地图和提示，不能假定可直接重入或已完成。

## 来源与核验范围

- 北斗 V17 静态资料，固定参考 [BeiDou-Server `00422c2`](https://github.com/BeiDouMS/BeiDou-Server/tree/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server)：[基础任务条件](https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz/Quest.wz/Check.img.xml)、[基础任务奖励](https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz/Quest.wz/Act.img.xml)、[中文任务名称和叙述](https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz-zh-CN/Quest.wz/QuestInfo.img.xml)、[中文怪物名称](https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz-zh-CN/String.wz/Mob.img.xml)。
- 战神线另对照[中文任务条件](https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz-zh-CN/Quest.wz/Check.img.xml)、[中文任务奖励](https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/wz-zh-CN/Quest.wz/Act.img.xml)、[21700脚本](https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/quest/21700.js)、[21703脚本](https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/quest/21703.js)和[暗号入口](https://github.com/BeiDouMS/BeiDou-Server/blob/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc/PupeteerPassword.js)。
