# 账号输入与首次登录边界

本参考只描述仓库当前的客户端能力。命令针对已经启动且归属确认的客户端实例；`ACCOUNT_PATH` 替换为当前运行环境已提供的账号文件路径。精确参数见[CLI](../../../../docs/CLI.md)，观察与输入约定见[操作指引](../../../../docs/PLAY_GUIDE.md)。

## 已有角色登录

重新接入时先执行 `status`、`script status` 和 `snapshot`。正确角色已经入图或已有任务时，沿用现有状态与脚本身份，不重复登录或启动任务；LLM 暂停、退出和再次接入不取消原生脚本或关闭客户端。

确实需要完成登录时，`open` 完成或确认当前客户端的登录，不切换到另一角色或服务器。

```bash
beidou-pilot --json open --account ACCOUNT_PATH
beidou-pilot --json status
beidou-pilot --json inspect stage
```

账号文件的合法输入：

- 权限为 `0600` 的 UTF-8 JSON，必填非空 `username`、`password` 和真实已有角色的 `character_id`；凭据不含控制字符。
- `character_id` 是正 32 位有符号整数。`world/channel` 为 0 基非负整数，格式允许 0 至 255，省略时各为 0；实际范围由后端和服务提供的选项决定。
- GUI 自动登录目前仅支持世界 0 和第 1 至 20 频道，按 CID 选择已有角色。第 1 频道在文件中写 `channel=0`。
- 不用 0、占位值、其他账号的 CID 或旧版选角参数绕过校验；密码不放进命令参数、截图说明或日志。

成功需用新鲜观察确认 `ready=true` 且角色 CID 与请求一致，再核对可用的名称、世界、频道、地图与位置，以及同一原生 `instance_id/run_id`；未提供的事实保持未知，不以配置值冒充实时观察。客户端进程运行、账号认证成功和角色列表出现是前置事实，入图以新鲜观察的完整核对为准。角色或频道不符时报告实际结果，不把 `open` 当作自动切换操作。

## 缺少账号或角色

`open` 要求真实已有 CID。无头首次登录由宿主工作台启动，账号文件可以暂不包含 CID。声明同意与账号性别须经用户明确授权：

```bash
private/workbenches/workbench /external/workbench login --accept-terms --gender female
private/workbenches/workbench /external/workbench login
private/workbenches/workbench /external/workbench character create --name NAME --gender female --job JOB --face FACE --hair HAIR --hair-color COLOR --skin SKIN --top TOP --bottom BOTTOM --shoes SHOES --weapon WEAPON
private/workbenches/workbench /external/workbench character result REQUEST_ID --instance-id INSTANCE_ID --run-id RUN_ID
```

各项角色数值按用户实际选择填写；`--hair` 是基础发型，`--hair-color` 是独立必填项，不能省略或并入 `--hair`。宿主 `login` 的选项仅用于新启动，运行中只观察、不重放选项；容器内 `beidou-pilot --json login --timeout N` 只观察，不接收启动选项。建角是独立的单次请求，不自动入图。

保留返回的请求与运行身份：`completed` 给出真实 CID，`rejected` 表示拒绝；`accepted`、`unknown` 不是完成，不重发，使用 `character result` 查询。宿主 `character result` 要求原容器仍运行；原实例退出或身份变化时未终结结果可能无法恢复。容器停止后保留已有结果和身份等证据，人工核验，不保证可通过宿主命令查询。宿主仅在账号文件权限正确、与运行快照一致且 CID 无冲突时绑定；`binding` 失败后依据结果及实际名单人工核对恢复，不重发建角。绑定后账号模式进程不支持同进程选角：先以工作台 `close` 并核对所属容器退出，再 `open` 并确认入图。

已有角色账号若仍未设置性别，安全收紧后不再依据 CID 隐式选择性别；CID 不能代替选择授权。经用户确认后关闭所属实例并核对退出，以宿主 `login --gender male|female` 新启动完成选择并核对名单，再关闭该实例、核对退出，最后用真实已有 CID `open`。此迁移路径尚未真实游戏实测。需要接受声明时也须明确授权。GUI 自动首次登录与建角不支持。

据用户说明，常驻服使用不存在的用户名登录时会自动创建账号；这是服务端机制，本流程尚待实测。注册、建角、CID 绑定和入图分别确认，不借用其他角色 CID。

## 已有 GUI 会话的首次界面

若已有属于授权账号的 GUI 会话，可由一名明确操作者观察并接续正常界面。同一角色不并发控制。

```bash
beidou-pilot --json inspect stage
beidou-pilot --json screenshot
```

| 实际界面或结果 | 当前可用处理与确认 |
| --- | --- |
| 首次声明 | 看当次截图，正文滚到底部后再判断确认按钮；是否接受沿用用户已明确的选择 |
| 性别选择 | 按已明确的选择操作，再重新观察结果 |
| 空角色列表 | GUI 自动建角不支持；仅可依据真实 GUI 的正常建角界面，按已明确的角色选择使用现有输入原语 |
| `character_not_unique` | 从实际名单核对账号、世界和 CID；角色归属以名单核对结果为准 |
| GUI 建角成功 | 从新鲜角色列表取得 CID 并核对名称；后续入图再核对角色、频道、地图、位置与原生身份 |

GUI 已提供截图、点击、对话和键盘等必要原语。点击依据当前截图或有效引用，历史坐标按历史记录保留。声明页需要滚轮时，仓库已有 `beidou_pilot.engines.desktop` 的 `scroll` 原语；先定位当前滚动控件，具体调用见[操作指引](../../../../docs/PLAY_GUIDE.md)中的 `desktop scroll`。滚动使用该原语，首次登录的其他步骤按实际界面逐步完成。

每轮核对实际界面进展。首次声明、性别选择和空角色列表不会因延长等待而自动完成。建号、首次界面、建角、已有角色登录和实际入图分别报告；未执行的步骤保持未验证。
