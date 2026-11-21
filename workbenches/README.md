# 工作台：连接常驻服，或在开发服准备测试角色

在仓库根执行 `workbenches/workbench`。宿主入口负责选服、镜像和容器；客户端观察与游戏动作仍由容器内 `beidou-pilot` 和 tick Lua 完成。无论从哪个 Git worktree 调用，账号和环境配置都取自主检出。

```text
workbenches/                         # 入库：入口、本说明、无私密模板
  workbench
  examples/
docker/dev-server/                   # 开发服装配；不包含游戏数据、服务端源码或私有配置
private/workbenches/                 # 整体忽略，不进镜像
  config/
    resources.json                   # 只读原版客户端和 Data 路径
    live.server.json                 # 常驻服的项目和游戏服务
    dev.server.json                  # 开发服的项目和游戏服务
    dev-server.env                   # 仅开发服的本机参数与密钥，0600
  live/warrior/                      # 已授权的常驻服账号角色，不是测试夹具
    account.json                     # 0600，凭据及角色绑定
    workbench.json                   # 可选，客户端选项；不能覆盖服务器
    README.md                        # 用途、接手须知
    PLAN.md                          # 养成计划
    HANDOFF.md                       # 有需要时才写
    scripts/                         # 此角色自己的 Lua 文件/目录包
    runtime/                         # 运行时生成，不手工填写
    cache/                           # 可重建
  dev/movement-probe/                # 可重建的测试角色；同样使用 account.json 等文件
    README.md                        # 角色用途、配对工作台、常用操作
    STATE.md                         # 职业、等级、关键技能、所在地图、最后核对时间及来源
    scripts/
  dev/observer/                      # 双端验收时的第二个独立角色，例如 GUI 观察端
```

## 首次准备及选服

1. 在主检出的 `private/workbenches/` 下建立 `config/`、`live/` 和 `dev/`。从 [examples](examples/) 复制对应样例，去掉文件名的 `.example`；按本机实际安装填写 `resources.json` 的 `gui_client` 和 `game_data`。相对资源路径以该配置文件所在目录为基准。
2. 每个环境各自填写服务器 Compose 项目和游戏服务。开发服客户端加入默认 Compose 网络，用服务名访问；常驻服客户端通过 host-gateway 访问宿主发布端口。开发游戏服务与其数据库由[开发服 Compose](../docker/dev-server/compose.yaml)装配，使用独立容器数据，不发布宿主端口。分区配置缺失时停止，不跨区回退。
3. 一个角色一个实际目录，放在对应分区内。已有角色的 `account.json` 使用 `username/password/character_id`，权限 `0600`；新号先不填 CID，走 [首次登录和建角](../.agents/skills/beidou-pilot-client/references/first-login.md)。`workbench.json` 默认 headless、main；GUI 设 `backend=beidou`，开发版本或工件见 [CLI](../docs/CLI.md)。不要把密码、连接凭据、DB 文件或验收原始记录提交 Git。

```bash
workbenches/workbench list                  # 或 list live / list dev
workbenches/workbench dev/movement-probe notes
workbenches/workbench dev/movement-probe plan   # 核对目标，不启动客户端
workbenches/workbench dev/movement-probe open
workbenches/workbench dev/movement-probe snapshot
workbenches/workbench dev/movement-probe script describe observe.lua
workbenches/workbench dev/movement-probe script run observe.lua --seconds 10
workbenches/workbench dev/movement-probe close   # 只关闭所属客户端
```

角色目录挂载到 `/work`。`script describe/run/start` 的相对名都从该角色的 `/work/scripts/` 解析，目录包从自身 `main.lua` 加载；不存在就报错，不回退到其他角色或镜像同名示例。镜像里的示例须显式指定容器绝对路径。`open` 不会自动运行脚本。

## 半常驻开发服

先按开发服样例准备 `config/dev-server.env`（`0600`），只使用开发专用凭据。开发服从发行镜像的初始数据和新的独立数据库开始，不复制常驻服数据库、账号或运行目录。开发服和角色工作台的生命周期独立：

```bash
workbenches/workbench server dev up
workbenches/workbench server dev status
workbenches/workbench server dev cli --help
workbenches/workbench server dev cli call GET /server/v1/version
workbenches/workbench server dev stop           # 不删除数据卷、账号或工作台
```

`server dev cli` 调用实际服务端管理 CLI，不是容器 shell 或 SQL。先核对该版本帮助与实际支持的命令，再准备场景；不要把“服务端设置成功”记成客户端已经发生该动作。账号创建的私密输入经标准输入送入 CLI，不要把密码拼到命令行或日志。开发角色说明可从 [STATE 模板](examples/dev-role-state.example.md) 开始；常驻服不接受本入口的管理命令。

**重置与清理**：普通 `stop` 持久保留数据。清空 `dev/` 或重置开发库由操作者另行安排，先关所属开发客户端并保存仍需留存的证据；`config/`、`live/` 不在清理范围。只重置其中一侧后，重新核对账号和角色绑定。

## 从旧目录迁移

先清点角色目录、实际容器和认领状态。旧实例以工作目录绝对路径标识，运行中不能移动；先用旧入口正常关闭，并确认没有其他使用者。旧工作台按所属环境迁到 `live/NAME` 或 `dev/NAME`；账号、脚本、计划和运行历史随目录保留。将共享资源配置移到 `config/resources.json`，相对路径要随位置重新解析；目标定义只放对应的分区服务器配置。移除或离线保存旧 `workbench.json` 中当前入口不支持的设置，不要改写历史运行快照。最后用 `list` 和 `plan` 复核，确认后才 `open`。
