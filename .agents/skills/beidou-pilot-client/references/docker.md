# Docker 部署与外部调用

本参考供管理镜像、生命周期或从宿主排障时使用。客户端实例内部直接执行 `beidou-pilot`，无需再次调用 Docker。镜像布局与启动配置见仓库 [README](../../../../README.md) 和 [CLI](../../../../docs/CLI.md)。

## 镜像和资源边界

GUI 客户端镜像安装 CLI、辅助引擎、内置 Lua 和 Wine/GUI 环境。客户端镜像按角色 `ref`（默认 `main`）构建，GUI Compose 来自当前宿主启动器，已有实例保持启动时的代码；从 `status` 核对实际源码与镜像版本。客户端运行时不挂载宿主开发源码。

原版客户端目录只读挂载到 `/client`，原版 `Data/**/*.img` 只读挂载到 `/data`。GUI 运行时和 Python 静态查询共用原生 IMG 解析器，不需要预先生成 NX、XML 或 PKG4 中间文件；客户端从 `/client` 读取其运行资源。账号、用户 Lua、桥通信目录和运行数据由生命周期入口装配，不进入镜像。用户 Lua 是运行输入，修改它无需重建客户端镜像。

## 从宿主查询或调用

宿主优先用 `workbenches/workbench dev/NAME status` 或 `workbenches/workbench live/NAME status`。分区配置、开发服生命周期和角色目录见[工作台指南](../../../../workbenches/README.md)。需要只读排障时，先核对容器归属，再将 `CONTAINER` 替换为所属容器：

```bash
docker exec CONTAINER beidou-pilot --help
docker exec CONTAINER beidou-pilot --json status
docker exec CONTAINER beidou-pilot --json script status
docker exec CONTAINER beidou-pilot --json snapshot
```

账号文件使用容器路径；脚本相对路径从当前角色的 `/work/scripts` 解析，绝对路径指容器内文件或目录包。CLI 的 `--root/--backend/--instance` 核对本容器身份，连接保持原状。容器创建、服务器镜像与网络核验、正常关闭均由仓库生命周期入口负责，具体用法见 [CLI](../../../../docs/CLI.md)。容器内 `close` 返回 `host_lifecycle_required`，下线状态以宿主入口的退出核对为准。

## 信号与取消

`script start` 成功后由原生客户端独立执行。使用 `script cancel --session SCRIPT_ID` 显式取消，并核对原生身份、终态和该会话的 `control_released`。

`script run` 同步等待结果，`run/start` 等待期间收到 Ctrl+C/SIGINT/SIGTERM 只结束 CLI 等待，已发布的原生任务继续执行。宿主入口转发信号也沿用这一语义，不隐式取消任务。等待超时、陈旧观察或 `docker exec` 调用结束时，任务受理与停止状态以 `script status` 为准；先查询 `script status`，核对已有任务，不重放 `start`。长期任务使用原生 `script start`，主动取消始终明确执行 `script cancel --session SCRIPT_ID` 并确认终态和放键。客户端下线另走明确的关闭操作，并确认所属容器退出。
