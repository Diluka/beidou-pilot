# Docker 部署与外部调用

本参考供管理镜像、生命周期或从宿主排障时使用。客户端实例内部直接执行 `beidou-pilot`，无需再次调用 Docker。harness 镜像以对应客户端镜像为基础，提供 Codex 与本技能；镜像布局与启动配置以仓库 [README](../../../../README.md)、[CLI](../../../../docs/CLI.md) 和 [harness 说明](../../../../docs/HARNESS.md)为准。

## 镜像和资源边界

headless 与 GUI 两个客户端镜像安装同一份 CLI、辅助引擎和内置 Lua，分别提供无头原生环境与 Wine/GUI 环境。新实例默认使用 `main` 的已提交版本，已有实例保持启动时的代码；从 `status` 核对实际源码与镜像版本。客户端运行时不挂载宿主开发源码。

原版客户端目录只读挂载到 `/client`，原版 `Data/**/*.img` 只读挂载到 `/data`。无头资源入口和 Python 静态查询共用原生 IMG 解析器，不需要预先生成 NX、XML 或 PKG4 中间文件；GUI 客户端仍从 `/client` 读取其运行资源。账号、用户 Lua、桥通信目录和运行数据由生命周期入口装配，不进入镜像。用户 Lua 是运行输入，修改它无需重建客户端镜像。

## 从宿主查询或调用

先核对容器归属，再将 `CONTAINER` 替换为所属容器：

```bash
docker exec CONTAINER beidou-pilot --help
docker exec CONTAINER beidou-pilot --json status
docker exec CONTAINER beidou-pilot --json script status
docker exec CONTAINER beidou-pilot --json snapshot
```

账号和 Lua 文件参数按容器内路径解释。CLI 的 `--root/--backend/--instance` 核对本容器身份，不能用来切换连接。容器创建、服务器镜像与网络核验、正常关闭均由仓库生命周期入口负责，具体用法见 [CLI](../../../../docs/CLI.md)。容器内 `close` 返回 `host_lifecycle_required`，不能据此宣称已经下线。

## LLM 接入与任务生命周期

LLM 是可选旁路，与客户端进程和原生脚本独立。暂停、停止或退出 LLM 接入不执行 `docker stop`，不终止原生脚本，也不清理执行任务的 shell。重新接入先读取 `status`、`script status` 和 `snapshot`，核对已有任务的身份，不重复启动或接管。关闭客户端容器属于明确的客户端生命周期操作，不能由 LLM 会话结束隐式触发。

## 信号与取消

`script start` 成功后由原生客户端独立执行；停止宿主终端、模型回合或事件监听不会取消 Lua。使用 `script cancel --session SCRIPT_ID` 显式取消，并核对原生身份、终态和 `held_keys=[]`。

`script run` 同步等待结果，`run/start` 等待期间收到 Ctrl+C/SIGINT/SIGTERM 只结束 CLI 等待，已发布的原生任务继续执行。宿主入口转发信号也沿用这一语义，不隐式取消任务。等待超时、陈旧观察或 `docker exec` 调用结束都不能证明任务未受理或已经停止；先查询 `script status`，核对已有任务，不重放 `start`。长期任务使用原生 `script start`，主动取消始终明确执行 `script cancel --session SCRIPT_ID` 并确认终态和放键。客户端下线另走明确的关闭操作，并确认所属容器退出。
