# 账号输入与首次登录边界

本参考只描述仓库当前的客户端能力。命令针对已经启动且归属确认的客户端容器；`CONTAINER` 和 `ACCOUNT_PATH` 分别替换为容器及容器内已有的账号文件。精确参数见[CLI](../../../../docs/CLI.md)，观察与输入约定见[操作指引](../../../../docs/PLAY_GUIDE.md)。

## 已有角色登录

容器内的 `open` 完成或确认当前客户端的登录，不创建容器，也不切换到另一角色或服务器。

```bash
docker exec CONTAINER beidou-pilot --json open --account ACCOUNT_PATH
docker exec CONTAINER beidou-pilot --json status
docker exec CONTAINER beidou-pilot --json inspect stage
```

账号文件的合法输入：

- 权限为 `0600` 的 UTF-8 JSON，必填非空 `username`、`password` 和真实已有角色的 `character_id`；凭据不含控制字符。
- `character_id` 是正 32 位有符号整数。`world/channel` 为 0 基非负整数，格式允许 0 至 255，省略时各为 0；实际范围由后端和服务提供的选项决定。
- GUI 自动登录目前仅支持世界 0 和第 1 至 20 频道，按 CID 选择已有角色。第 1 频道在文件中写 `channel=0`。
- 不用 0、占位值、其他账号的 CID 或旧版选角参数绕过校验；密码不放进命令参数、截图说明或日志。

成功需用新鲜观察确认 `ready=true` 且角色 CID 与请求一致，再核对可用的名称、世界、频道、地图与位置，以及同一原生 `instance_id/run_id`；未提供的事实保持未知，不以配置值冒充实时观察。容器运行、账号认证成功或角色列表出现，都不能单独证明已经入图。角色或频道不符时报告实际结果，不把 `open` 当作自动切换操作。

## 缺少账号或角色

当前 CLI 没有 `register`、`create-character` 或按名称创建角色后登录的命令。`open` 要求真实已有 CID，不能仅靠它完成全新账号从注册到建角的全过程。

账号注册不属于本仓库客户端能力。若用户另指定工具及授权，按该工具的独立能力处理；注册成功与已有角色、取得真实 CID、客户端入图分别确认。

没有真实 CID 且没有可接续 GUI 会话时，明确说明缺少无角色引导路径。不要编造启动参数、借用其他角色 CID，或反复延长 `open --timeout` 来掩盖能力缺口。

## 已有 GUI 会话的首次界面

若已有属于授权账号的 GUI 会话，可由一名明确操作者观察并接续正常界面。同一角色不并发控制。

```bash
docker exec CONTAINER beidou-pilot --json inspect stage
docker exec CONTAINER beidou-pilot --json screenshot
```

| 实际界面或结果 | 当前可用处理与确认 |
| --- | --- |
| 首次声明 | 看当次截图，正文滚到底部后再判断确认按钮；是否接受沿用用户已明确的选择 |
| 性别选择 | 按已明确的选择操作，再重新观察结果 |
| 空角色列表 | 当前没有自动建角命令；仅可依据真实 GUI 的正常建角界面，按已明确的角色选择使用现有输入原语 |
| `character_not_unique` | 从实际名单核对账号、世界和 CID；该错误不等于一定没有角色 |
| GUI 建角成功 | 从新鲜角色列表取得 CID 并核对名称；后续入图再核对角色、频道、地图、位置与原生身份 |

GUI 已提供截图、点击、对话和键盘等必要原语。点击依据当前截图或有效引用，不能重放历史坐标。声明页需要滚轮时，仓库已有 `beidou_pilot.engines.desktop` 的 `scroll` 原语；先定位当前滚动控件，具体调用见[操作指引](../../../../docs/PLAY_GUIDE.md)中的 `desktop scroll`。不要虚构顶层 `scroll` 子命令或把原语可用写成完整首次登录自动化。

每轮核对实际界面进展。首次声明、性别选择和空角色列表不会因延长等待而自动完成。建号、首次界面、建角、已有角色登录和实际入图分别报告；未执行的步骤保持未验证。
