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

`open` 要求真实已有 CID。首次登录由宿主工作台启动所选后端，账号文件可以暂不包含 CID。声明同意与账号性别须经用户明确授权：

```bash
private/workbenches/workbench /external/workbench login --accept-terms --gender female
private/workbenches/workbench /external/workbench login
private/workbenches/workbench /external/workbench character create --name NAME --gender female --job JOB --face FACE --hair HAIR --hair-color COLOR --skin SKIN --top TOP --bottom BOTTOM --shoes SHOES --weapon WEAPON
private/workbenches/workbench /external/workbench character result REQUEST_ID --instance-id INSTANCE_ID --run-id RUN_ID
```

各项角色数值按用户实际选择填写；`--hair` 是基础发型，`--hair-color` 是独立必填项，不能省略或并入 `--hair`。宿主 `login` 的选项仅用于新启动，运行中只观察、不重放选项；容器内 `beidou-pilot --json login --timeout N` 不带授权选项时只观察。GUI 容器内可显式传 `--gender male|female` 发起登录动作，需要同意声明时另加 `--accept-terms`；GUI 动作必须指定性别，由原生桥在游戏线程调用原版客户端内部入口完成；无头容器内不接受这些选项。建角是独立的单次请求，不自动入图。

保留返回的请求与运行身份：`completed` 给出真实 CID，`rejected` 表示拒绝；`accepted`、`unknown` 不是完成，不重发，使用 `character result` 查询。宿主 `character result` 要求原容器仍运行；原实例退出或身份变化时未终结结果可能无法恢复。容器停止后保留已有结果和身份等证据，人工核验，不保证可通过宿主命令查询。宿主仅在账号文件权限正确、与运行快照一致且 CID 无冲突时绑定；`binding` 失败后依据结果及实际名单人工核对恢复，不重发建角。绑定后账号模式进程不支持同进程选角：先以工作台 `close` 并核对所属容器退出，再 `open` 并确认入图。

已有角色账号若仍未设置性别，安全收紧后不再依据 CID 隐式选择性别；CID 不能代替选择授权。经用户确认后关闭所属实例并核对退出，以宿主 `login --gender male|female` 新启动完成选择并核对名单，再关闭该实例、核对退出，最后用真实已有 CID `open`。此迁移路径尚未真实游戏实测。需要接受声明时也须明确授权。

常驻 v1.12 已实测登录注册机制：登录前只读确认账号不存在，短 ASCII 用户名登录成功后只读确认账号已创建。另一次 15 字符 ASCII 用户名尝试后，服务日志记录 name 列过长，账号仍不存在；10 字符成功。建议用户名不超过 10 个 ASCII 字符；JAR 迁移中的 `VARCHAR(13)` 不足以证明现网完整上限。注册、建角、CID 绑定和入图分别确认，不借用其他角色 CID。

## 已有 GUI 会话的首次界面

若已有属于授权账号的 GUI 会话，可由一名明确操作者观察并接续正常界面。同一角色不并发控制。

```bash
beidou-pilot --json inspect stage
beidou-pilot --json screenshot
```

| 实际界面或结果 | 当前可用处理与确认 |
| --- | --- |
| 首次声明 | 是否接受沿用用户已明确的选择；GUI 原生动作直接调用协议页确认入口 |
| 性别选择 | 按已明确的选择发起原生性别请求，再重新观察结果 |
| 空角色列表 | 可按上述限制显式请求建角；先核对授权、身份与角色参数，结果不明不重发 |
| `character_not_unique` | 从实际名单核对账号、世界和 CID；角色归属以名单核对结果为准 |
| GUI 建角成功 | 从新鲜角色列表取得 CID 并核对名称；后续入图再核对角色、频道、地图、位置与原生身份 |

GUI 登录与建角步骤不再使用桌面坐标键鼠：协议、性别、账号、世界、频道、姓名核查与建角动作由原生桥调用原版客户端内部入口，Python 只核对页面与身份并做一次性去重。截图、对话与引用仍用于观察和人工处理其他界面。动作被拒绝、页面不明或超时时保留现场与身份，先观察或查询，不重放。

每轮核对实际界面进展。首次声明、性别选择和空角色列表不会因延长等待而自动完成。建号、首次界面、建角、已有角色登录和实际入图分别报告；未执行的步骤保持未验证。
