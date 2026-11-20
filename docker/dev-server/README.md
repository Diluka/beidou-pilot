# 隔离开发服

从仓库根用 `workbenches/workbench server dev up|status|stop|cli` 管理开发服。账号、数据和部署只属于本机开发环境。

## 准备

- [Compose](compose.yaml) 使用 `ghcr.io/beidoums/beidou-server-all:v1.12` 与 MySQL 8.4.0。游戏镜像自带 `BeiDou.jar`、JRE 21、WZ 和脚本；管理 CLI 单独挂载。
- 使用[官方 beidou-cli v1.0.5](https://github.com/BeiDouMS/beidou-cli/tree/eaffe8849a5d0f57f986ba95c92b108e3d7b625d) JAR。本机把 JAR 绝对路径写入 `private/workbenches/config/dev-server.env` 的 `BEIDOU_DEV_CLI_JAR`。
- `dev-server.env` 权限保持 `0600`，只放本机开发参数；不提交、不复制到公开记录。

## 网络与数据

- 两个服务使用 Compose 默认网络和 Docker DNS：客户端通过服务名 `beidou-server-all` 访问游戏，数据库通过 `beidou-db` 访问。
- 不发布宿主端口。游戏镜像不包含管理 CLI；CLI 从本机只读挂载。
- MySQL 数据在容器内，不使用命名卷。`server dev stop` / `up` 保留现有容器和数据；`docker compose down` 或删除容器会清空开发数据。
- [application.yml](application.yml) 是开发服固定模板：数据库 root、JWT 和 seed admin 密码写死，仅用于本机隔离环境。[start.sh](start.sh) 解析 `beidou-server-all` 的地址并写入运行配置，再把 `BEIDOU_DEV_ADMIN_PASSWORD` 应用到 seed admin。

## 管理调用

用 `workbenches/workbench server dev cli --help` 查看[入口](cli.sh)。它把参数交给官方 JAR，不执行操作者提供的 shell 或 SQL；容器身份和 `user.home` 固定，连接指向容器内 `127.0.0.1:8686`。

```bash
workbenches/workbench server dev cli version
workbenches/workbench server dev cli call GET /server/v1/version
workbenches/workbench server dev cli call GET /server/v1/online
workbenches/workbench server dev cli call GET /server/v1/world/list
```

注册时从私密文件送入单行 JSON，再用客户端完成首次登录与建角；密码不放到命令行：

```bash
jq -c '{name:.username, password, language:3}' "$DEV_ACCOUNT_FILE" |
  workbenches/workbench server dev cli register
```

`register` 调用官方 `call --force POST /account/v1`。`register`/`give` 只返回业务码，`20000` 为成功；结果不明时先核对现状，不重复注册或发放物品。接口不创建玩家角色，也不返回 CID。

角色入图并核对世界和正 CID 后，`give WORLD CID` 支持物品、换图、经验、金币：

```bash
workbenches/workbench server dev cli give "$WORLD" "$CID" item "$ITEM_ID" "$COUNT"
workbenches/workbench server dev cli give "$WORLD" "$CID" map "$MAP_ID"
workbenches/workbench server dev cli give "$WORLD" "$CID" exp "$POINTS"
workbenches/workbench server dev cli give "$WORLD" "$CID" mesos "$AMOUNT"
```

发经验不是直接设置等级；实际道具、地图或等级由客户端核对。入口不提供容器 shell 或 SQL。离线合同测试用假 Java 进程验证透传参数：

```bash
python3 docker/dev-server/test_cli.py
```
