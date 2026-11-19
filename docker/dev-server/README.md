# 隔离开发服：发行装配与管理 CLI

从仓库根目录用 `workbenches/workbench server dev up|status|stop|cli` 管理开发服。[工作台指南](../../workbenches/README.md)说明分区与角色工作台的配置。这里的账号、密钥和部署方式**仅适用于独立开发网络**，不得用于公网或正式服。

## 准备发行工件与凭据

- [Compose](compose.yaml) 固定 `ghcr.io/beidoums/beidou-server-all:v1.12` 与 MySQL 8.4.0 的 digest。游戏镜像内的 `/opt/server_backup` 自带原版 `BeiDou.jar`、JRE 21、WZ 和脚本；它没有独立的管理 CLI。
- 使用[官方 beidou-cli 源码 v1.0.5](https://github.com/BeiDouMS/beidou-cli/tree/eaffe8849a5d0f57f986ba95c92b108e3d7b625d)的已核验 JAR。本机安装记录的构建命令是 `mvn -B -DbeidouVersion=1.0.5 -DskipTests package`，工件 SHA256 为 `15cd8eabc3b72790856cc39a80368c615035336141560532e4e1e3490eab9ffd`。这里只读挂载该 JAR；[启动脚本](start.sh)在运行前核验字节。重新构建不保证得到相同摘要，不能用改写校验值代替验证来源。
- 将[环境模板](../../workbenches/examples/dev-server.env.example)复制到主检出的 `private/workbenches/config/dev-server.env`，权限 `0600`。为四个密钥各执行一次 `openssl rand -hex 32` 生成不同值并写入私密文件，保留供重启使用；`BEIDOU_DEV_CLI_JAR` 填工件的绝对路径。容器不挂载宿主 CLI 家目录、连接配置、账号目录或 Docker socket。

## 干净初始化与持久化

游戏客户端只加入项目的 internal `game` 网络；游戏进程向客户端报告自己在该网络上的地址。MySQL 只加入独立的 internal `backend` 网络。两服务均不发布宿主端口。

MySQL 使用 Compose 的 `workbench-db` 命名卷（`${project}_workbench-db`），卷和两个服务均带 `beidou.workbench.environment=dev` 归属标签。新环境从空卷初始化；共享名、无标记卷及正式服数据均不得作为输入。MySQL 在该卷上创建游戏库和应用用户；[初始化授权](init-user.sql)另外允许 v1.12 首启检查连接 `mysql` catalog、允许内置 Flyway 读取其迁移使用的会话变量。应用不使用数据库 root。游戏启动前的数据库检查和 Spring 共用一份从发行模板生成的私密配置。Flyway 执行 JAR 自带的 99 个迁移；其中自带一个管理账号和一个角色，属于发行种子，并非来自旧服。开发回调只替换与上游默认值完全匹配的 seed 管理密码。实际 CLI 的连接和登录缓存位于容器私有 tmpfs，始终指向本容器的 `127.0.0.1:8686`。

`stop` 正常停止两个服务并保留卷，再 `up` 恢复。首次装配实测：99/99 个发行迁移成功；通过官方 CLI 注册了两个新账号（均返回业务码 `20000`），正常 stop/up 后卷身份不变、数据库无需重跑迁移；再次查询时两账号及各自账号 ID 一致。账号 ID 不等于角色 CID。管理 CLI 报告版本 `1.0.5`，服务端版本查询返回 `1.12`，在线状态为 `true`，游戏登录和三个频道均监听。这些属于服务准备证据；角色建成、入图和实际玩法由客户端另行验证。

开发分支验收期间，Compose 的脚本配置从该 worktree 只读挂载。合并后、移除 worktree 前，应在客户端已退出的窗口从主检出运行 `workbenches/workbench server dev up`，核对新容器配置挂载的宿主来源已指向主检出，并用 `server dev cli --help` 验证当前包装器；更换源码位置不需要迁移或删除数据库卷。此次从旧试运行卷切换归属标签时，只在两服务正常停止后，将本轮新建的开发卷只读复制到全新带标签卷，逐文件比对，保留源卷。日常 `up` 不执行这样的迁移。

## 支持的管理调用

用 `workbenches/workbench server dev cli --help` 查看[开发服入口](cli.sh)。它把命令原样交给官方 JAR（`call`、`batch`、`login`、`config`、`update` 等全部可用，敏感 API 需 `--force`），不执行操作者提供的 shell 或 SQL；容器身份与 `user.home` 固定，连接指向本容器 `127.0.0.1:8686`。`apis` 显示上游静态接口清单，实际能力以运行版本为准。

```bash
workbenches/workbench server dev cli version
workbenches/workbench server dev cli call GET /server/v1/version
workbenches/workbench server dev cli call GET /server/v1/online
workbenches/workbench server dev cli call GET /server/v1/world/list
```

注册时从授权的开发角色私密文件送入单行 JSON（权限 `0600`），再用客户端完成首次登录与建角。关闭 shell 跟踪，不把密码放到命令行：

```bash
jq -c '{name:.username, password, language:3}' "$DEV_ACCOUNT_FILE" |
  workbenches/workbench server dev cli register
```

`register` 固定调用官方 `call --force POST /account/v1`，是本入口的密码安全别名。开发服实测覆盖该官方接口的账号写入与重启保留；另用发行 JRE 21、同一 JAR 和隔离回环夹具验证了包装器的 stdin 传参。`register`/`give` 只返回业务码，`20000` 才算成功；其余官方命令原样输出完整响应。非零退出或结果不明时先核对现状，不重复注册或发放物品。接口不创建玩家角色，也不返回 CID。

角色入图并核对世界和正 CID 后，`give WORLD CID` 支持四类定向准备。以下为语法，示例变量须替换为已授权目标，按实际需要选一项：

```bash
workbenches/workbench server dev cli give "$WORLD" "$CID" item "$ITEM_ID" "$COUNT"
workbenches/workbench server dev cli give "$WORLD" "$CID" map "$MAP_ID"
workbenches/workbench server dev cli give "$WORLD" "$CID" exp "$POINTS"
workbenches/workbench server dev cli give "$WORLD" "$CID" mesos "$AMOUNT"
```

v1.12 的 `GiveService` 对在线角色按 `worldId` 和 `playerId` 定位；`give` 便捷别名固定调用 `/give/v1/resource`，使用 `type=5/13/4/3` 分别发物品、换图、加经验、加金币。角色 ID `0` 在上游表示广播，本入口拒绝。发经验不是直接设置等级。发行包中有游戏内 GM 职业、等级、技能和传送命令，但 HTTP 管理端没有执行任意游戏内命令的入口；管理 CLI 也不能直接设职业、精确等级或技能，需要时用完整透传的 `call` 核对运行版本实际提供的接口。实际道具、地图或等级均须由客户端核对，业务成功码不能代替游戏效果证据。

入口完全透传官方 CLI；只有 `register` 与 `give` 两个便捷别名会投影业务码。原始 `batch`、任意 API 路径、配置与安装管理都可用，但仍受官方 CLI 的 `--force` 与运行版本限制；本入口不提供容器 shell 或 SQL。[离线合同测试](test_cli.py)使用假 Java 进程验证透传参数、定向参数与私密输入输出，可用 `python3 docker/dev-server/test_cli.py` 运行。
