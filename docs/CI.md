# CI 与合并验收

[CI 工作流](../.github/workflows/ci.yml) 在 PR 创建、重新打开或更新提交时运行，也在提交进入 `main` 后运行。每次运行包含以下独立检查：

| 检查名称 | 执行内容 |
| --- | --- |
| `Python offline tests` | Ubuntu 24.04、Python 3.14，运行现有 CLI 离线合同测试 |
| `Headless image build` | Ubuntu 24.04，使用 `docker/headless/Dockerfile` 构建包含共享 CLI、Lua 与原生客户端的无头镜像 |
| `Game AI harness contract` | 构建标准 npm 安装的固定 Codex 镜像，运行无认证的 harness 合同，含真实 app-server、Code Mode 游戏工具分派与开发询问往返 |

客户端测试与无头构建从当前提交检出源码并递归初始化固定版本子模块。Python 测试只使用标准库，无需安装 pip 依赖；其中 Lua 任务合同使用 runner 自带的 `gcc/g++` 编译真实共享 Runtime 和固定 Lua 源码，适配器只模拟原生输入与释放边界。无头镜像的编译器只放在 builder，运行层由 Bookworm 包管理器安装 Python 和原生运行依赖。两个客户端镜像安装同一份 CLI 与内置 Lua，离线测试与 CI 内部镜像构建使用当前检出的提交，不经默认 main 启动路径替换代码。harness 合同不访问真实模型或游戏，不需要认证。

[Windows 桥工作流](../.github/workflows/agent-bridge.yml) 另在 PR、`main` 推送和手动触发时执行 `Windows bridge build`。它在 Windows 2022 / VS2022 中从固定 Detours 源码构建 x86 库及桥 DLL，并上传含来源清单、日志和许可证的 `maple-agent-bridge-win32` 工件。构建与下载说明见[桥构建文档](../beidou-ijl15/docs/agent-bridge-build.md)。

## 本地复现

从仓库根执行，先初始化依赖：

```bash
git submodule update --init --recursive
```

准备 Python 3.14、`gcc/g++` 后，运行与 CI 相同的离线测试入口：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli -v
```

安装并启动 Docker 后，通过统一入口构建当前提交的无头镜像并检查容器内 CLI：

```bash
mkdir -p tmp/ci-reproduction/workbench
image=$(./beidou-pilot --workbench "$PWD/tmp/ci-reproduction/workbench" \
  --backend headless --ref "$(git rev-parse HEAD)" --json build | jq -er .data.image)
docker run --rm --entrypoint beidou-pilot "$image" --help
```

无头构建只使用源码与固定依赖，不需要游戏素材、账号配置或游戏服务器访问，不推送镜像。CI job 内部直接调用同一份 `docker/headless/Dockerfile`，用户构建统一经根入口。容器入口默认需要运行配置；打包检查显式选择 `beidou-pilot` 帮助入口，不启动游戏。

网络需能下载子模块、基础镜像及 Debian 构建包。确认网络权限并按项目网络规则选择代理后，可在启动构建前导出 `HTTP_PROXY`、`HTTPS_PROXY` 和 `NO_PROXY`；根入口按 Docker 标准 build args 透传这些变量。代理地址须能从构建网络访问，文档不固定本机地址。

GUI 完整镜像的本地构建通过工作台入口，例如 `./beidou-pilot --workbench /external/gui-workbench --backend beidou --ref COMMIT build`。默认由 `gh` 获取所选提交成功的 Windows 桥 CI 工件；开发时可加 `--bridge-artifact DIR` 显式复用原生输入匹配的现成工件，省去 `gh` 依赖。镜像安装该工件，原始游戏客户端、NX 与工作台仍只在运行时挂载。GUI 装配仅使用 `docker/compose.yaml`；账号、服务器配置和用户 Lua 随整个工作台进入 `/work`，不再分别挂载。GUI 与无头的打包检查都应确认容器内 CLI 可执行，不能用宿主 Python 的帮助输出代替。

## 查看结果与合并

在 PR 的 Checks 页面查看对应提交的两项检查，也可从仓库 [Actions](https://github.com/Diluka/beidou-pilot/actions/workflows/ci.yml) 页面查看日志。命令行入口为：

```bash
gh pr checks PR编号 --repo Diluka/beidou-pilot
```

代码或构建改动按惯例在 PR 当前提交的 `Python offline tests` 和 `Headless image build` 均通过后合并。失败、缺失、未运行或跳过的检查如实记录并处理；本地成功不能代替远端 CI 结果。探索调试可先做本地检查和有界客户端试验，不以远端 CI 完成为前提；正式验收使用对应提交的检查结果。

纯文档修改按 [AGENTS.md](../AGENTS.md#开发与交付流程) 的简易流程直接提交并推送 `main`，不要求创建 PR 或等待 CI。推送触发的自动检查仍保留，结果按实际状态记录。

CI 验收是日常协作约定，不配置为远端强制检查门禁。主分支的 `default` 规则仅保留禁止删除和非快进更新保护。

CI 的镜像检查覆盖无头镜像；完整 GUI 镜像需按改动在本地构建验证，Windows DLL 由独立工作流构建。CI 不连接真实游戏或证明实际游戏效果。正式验收、回归范围和证据复用统一按[验收约定](../AGENTS.md#验收方式)执行，只补实际受影响的路径；未改变组件的有效证据可引用复用。纯文档、CI 等不改变客户端运行行为的改动，可以在 PR 说明游戏试用不适用及理由。

## 版本与实例隔离验收

涉及交付或生命周期时，在授权的不同角色和隔离目标中验证：实例 A 使用提交 X 启动，主代码更新至 Y 后再启动实例 B；核对双方的 `source_revision/image/run_id`。A 的观察、最小动作、取消放键和正常关闭仍使用 X，B 使用 Y 且不受 A 关闭影响。宿主的构建、启动、`docker exec` 路由与容器内实际结果分别记录；GUI 和无头受影响的路径分别验证。

正式证据以 PR 提交及实际运行组件为准。由主提交导出的镜像不能标记成尚未提交的源码，GUI 也不能以旧桥代替包含新原生输入的工件。已有实例不会自动跟随 main，升级以正常关闭后新建实例完成。
