# 命令使用

根入口为 `./cli/beidou-pilot`，支持任意当前目录；精确参数以当前 `--help` 和子命令 `--help` 为准。默认后端是 `beidou`，自动化调用应显式选端和使用 `--json`。

## 实例与输出

公共选项可以放在命令前后：`--backend beidou|headless`、`--instance NAME`、`--root PATH`、`--json`、`--debug`。`--root` 指定运行目录，不改变当前加载的代码与内置 Lua 来源。

命名实例只支持无头端，省略为 `default`；名字为1至48位小写字母、数字、下划线或连字符，首位为字母或数字。GUI只使用默认单实例。每个无头实例独立持有容器、登记、日志和桥目录，同一目标同一角色只能由一个实例接管。

普通成功结果为单个 JSON，包含 `ok/command/backend/instance/data`。失败对象包含 `error.code/message/details`；显式 `--json` 时错误也写 stdout，否则写 stderr。已识别的失败退出码为2，中断为130，正常返回为0。独立 `watch` 输出 JSONL；原版 `snapshot` 无 `--json` 时为简洁文本，无头 `snapshot` 仍为 JSON。

## 启动、观察与关闭

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json open \
  --target /external/target.json --profile /private/account.private.json
./cli/beidou-pilot --backend headless --instance worker-a --json snapshot
./cli/beidou-pilot --backend headless --instance worker-a --json close
```

无头新实例必须显式给出 target 与权限0600的 profile；已有匹配实例可 `open` 复用。target 格式见 [target.example.json](../cli/config/target.example.json)，当前按 Docker Compose 项目/服务、精确应用镜像和 internal 网络核验，不自动启动游戏服务端。

profile 需 `username/password/character_id`，可选 `world/channel` 为0基索引。角色必须已经存在，不自动创建。账号文件外置，密码不写到参数中。无头选角与频道来自 profile，不接受 GUI 的 `--character/--character-index/--channel` 选项；旧 `max_seconds` 进程期限字段明确拒绝。`--timeout`只限制启动等待。

GUI `open` 使用普通登录、选频道和选角，可按 `--channel`、`--character` 或 `--character-index` 选择已有角色。它需要已准备的 GUI 运行环境，默认目标配置不代表已获准操作任意服务。

| 命令 | 行为 |
| --- | --- |
| `status`、`doctor` | 读取阶段或检查环境，不启动客户端 |
| `instances` | 列出当前根目录已登记的无头实例 |
| `capabilities` | 在线读取实际原生动作能力；离线 `native_actions=null`，仍列静态观察域 |
| `open`、`close` | 创建/复用实例；正常停止、核验退出并回收实例 |
| `snapshot [-i] [--all]` | 当前角色、场景、领域摘要及引用；`-i`省略怪物行，`--all`包含画外实体 |
| `inspect KIND [ID]` | 领域读数或静态资源，KIND见帮助 |
| `watch --seconds N --interval N` | 持续只读状态，独立调用为JSONL |
| `bridge status`、`script status` | 原生桥、动作或脚本状态，只读 |

容器在命令结束后常驻。短脚本返回或取消不会关闭客户端；无头 `close` 可关闭正在执行 Lua 的实例。关闭使用独立生命周期锁；同一实例正在启停时为 `lifecycle_busy`，活动脚本期间其他动作是 `input_busy`。退出状态保留 `run_dir/exit_code/stop_reason`。失败后先读取原因和实际状态，再决定重开。

## 动作与 Lua

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json walk right --seconds 0.2
./cli/beidou-pilot --backend headless --instance worker-a --json script run /path/control.lua --seconds 20
./cli/beidou-pilot --backend headless --instance worker-a --json script run /path/control.lua --continuous
```

| 命令 | 支持与结果边界 |
| --- | --- |
| `walk DIR --seconds N`、`face DIR`、`jump` | 有界方向移动、朝向、跳跃尝试 |
| `attack`、`pickup`、`use_item ID` | 原生尝试；`use_item`不等于消耗和恢复已确认 |
| `move X`、`climb X --to-y Y`、`portal NAME` | Lua执行同层对齐、单根绳梯或单个门户；不是通用寻路 |
| `fight MOB` | 同层基础Lua策略，支持预算、停级、安全范围、撤退锚点及近距拾取尝试 |
| `use ITEM --count N`、`--until-hp N`、`--until-mp N` | 核对库存消耗与恢复；计数范围和组合以帮助/实际分类为准 |
| `script run FILE` | 装载受信UTF-8 Lua；默认限时，持续模式须明确声明 |
| `stop`、`bridge stop` | 无其他活动动作控制者时清理遗留控制 |
| `key KEYS --seconds N`、`skill ID` | 原版专属Lua扩展；无头明确拒绝 |

移动和战斗参数只对当前场景有效。门户和部分规划依赖可选静态 WZ XML，资料不足时明确拒绝；换层、身份变化、低HP或未确认到达会停止后续动作。基础 `fight` 受转职节点限制，特殊任务、材料或职业技能策略应自行写Lua，没有未实现的占位选项。

无头 `use` 只接受数字ID和普通200类HP/MP药剂。按次数使用可不依赖XML，带HP/MP目标时需要资料已知恢复类型。原版已绑定恢复品走Lua，未绑定物品可走GUI；203类传送卷仅支持单次使用，不接受HP/MP目标。

`skill`返回 `native_result`：0为本地拒绝，非零不能证明命中或服务器确认。对活动脚本发送原CLI的Ctrl+C/SIGTERM取消并等待放键；不要用第二个动作命令抢占。脚本能力及效果判断见 [CONTROL](CONTROL.md)。

## 原版 GUI

以下操作不由无头端提供，CLI会明确报不支持：

| 命令组 | 用途 |
| --- | --- |
| `talk TARGET`、`dialog`、`click REF` | 打开NPC对话、按当前正文选择、操作当前引用 |
| `ui read/open/close/focus` | 已识别窗口和输入焦点；`ui close all`同时处理普通商店 |
| `equip ITEM`、`stats`、`skills` | 正常GUI装备/AP/SP操作，并核对结果 |
| `hotkeys`、`bind`、`press` | 读取、拖放绑定和按已有物品/技能快捷键 |
| `shop read/buy/sell/close` | 普通商店读取与指定买卖；数量框和关店按实际UI收尾 |
| `revive` | 已识别死亡确认，核对同角色恢复；存活时跳过 |
| `screenshot [NAME]`、`record NAME` | 当前窗口截图或有界逐帧记录，不发游戏输入 |

引用来自本次快照，换图、对话翻页、重登或目标变化后重新读取。任务/奖励、消费、加点和交易不能因派发成功就重放；以当前完整正文和实际变化判断。GUI输入只允许一名明确操作者。

## 有限批次

`batch [--file PATH]` 接受非空JSON参数数组，先解析全部CLI参数，再顺序执行。禁止嵌套batch，不能切换root、backend或instance。进度写stderr，最终仍是单个JSON；批内watch收为最终状态。

某一步抛错时立即停止，错误详情含从0开始的 `index`、此前 `completed` 和原始 `cause`，不回滚已发生效果。子命令正常返回预算停止或取消状态不会自动终止批次；只批量编排无需中途决策的有限步骤，持续控制写Lua。
