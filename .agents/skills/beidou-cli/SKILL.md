---
name: beidou-cli
description: 查询北斗隔离开发服的在线状态、版本和世界列表，注册开发账号，或给已入图的开发角色发物品、加经验、加金币、传送地图以准备测试场景。使用宿主工作台的服务端 CLI；角色登录、建角、运行 Lua 和游戏内验证由客户端技能负责。
---

# 北斗开发服 CLI

在仓库根目录运行 `workbenches/workbench server dev cli`。工作台会核验开发服身份，并在对应游戏容器内调用官方 `beidou-cli`。本技能沿用服务器工作区的 `beidou-cli` 操作约定，入口和可用命令以本项目的[开发服指南](../../../docker/dev-server/README.md#支持的管理调用)为准。授权仅限 `dev` 分区；未启动或配置不符时，不切换到 `live`，也不借用宿主的管理凭据。

## 查询开发服

```bash
workbenches/workbench server dev status
workbenches/workbench server dev cli --help
workbenches/workbench server dev cli call GET /server/v1/online
workbenches/workbench server dev cli call GET /server/v1/version
workbenches/workbench server dev cli call GET /server/v1/world/list
```

`cli version` 显示管理工具版本，`/server/v1/version` 返回运行中的游戏服务版本。`apis` 展示上游静态接口，不是本工作台允许执行的命令清单；以 `cli --help` 为准。查询要检查业务 `code=20000` **以及所需的 `data`**：确认在线还要看到 `data=true`。本入口不接受任意 API 路径或原始 `batch`。

## 准备开发角色

1. **已有角色优先确认身份。** 用 `workbenches/workbench list dev` 选择角色，再用 `workbenches/workbench dev/NAME snapshot` 确认已入图、角色 ID 与目标相符。`give` 使用角色的世界编号（从 0 开始）和实际正 CID；账号 ID、频道号都不能代替它们。
2. **需要新账号时才注册。** 从主检出该开发工作台权限为 `0600` 的 `account.json` 读取输入。下面的 `DEV_ACCOUNT_FILE` 指向这份文件；关闭 shell 跟踪，不打印文件或将密码写入命令参数。

   ```bash
   jq -c '{name:.username, password, language:3}' "${DEV_ACCOUNT_FILE:?请指定开发角色账号文件}" |
     workbenches/workbench server dev cli register
   ```

   注册成功不等于已建角。首次登录、建角、绑定 CID 和入图按[客户端技能](../beidou-pilot-client/SKILL.md)执行。

3. **按测试所需选择一项定向操作。** 先观察原状态，只操作已核对的在线开发角色。`CID=0` 在上游表示广播，工作台拒绝该值。

   | 需要准备的条件 | `workbenches/workbench server dev cli` 后的参数 | 客户端复核 |
   | --- | --- | --- |
   | 物品 | `give WORLD CID item ITEM_ID COUNT` | 背包中对应物品及数量 |
   | 经验 | `give WORLD CID exp POINTS` | 经验、等级是否按预期变化 |
   | 金币 | `give WORLD CID mesos AMOUNT` | 金币前后差值 |
   | 地图 | `give WORLD CID map MAP_ID` | 实际地图 ID 和位置 |

写操作返回 `code=20000` 只确认服务端成功。响应丢失、角色断线或客户端结果不明时，先重新观察，必要时重登入图核对，**不要重复发放**。将已核对的条件、来源和时间记入该开发角色的 `STATE.md`。发经验不是精确设级；当前入口不支持直接指定职业或技能。若要验证位移技能，传送只用于准备起点，实际位移仍由客户端施放并观察。
