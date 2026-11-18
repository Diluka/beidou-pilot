# CI 与合并验收

[CI 工作流](../.github/workflows/ci.yml) 在 PR 创建、重新打开或更新提交时运行，也在提交进入 `main` 后运行。每次运行包含以下独立检查：

| 检查名称 | 执行内容 |
| --- | --- |
| `Python offline tests` | Ubuntu 24.04、Python 3.14，运行现有 CLI 离线合同测试 |
| `Headless image build` | Ubuntu 24.04，使用 `docker/headless/Dockerfile` 构建包含共享 CLI、Lua 与原生客户端的无头镜像 |

客户端测试与无头构建从当前提交检出源码并递归初始化固定版本子模块。Python 测试只使用标准库；其中 tick Lua 合同使用 runner 自带的 `gcc/g++` 编译真实共享 tick Runtime 和固定 Lua 源码，适配器只模拟原生输入与释放边界。无头镜像的编译器只放在 builder，运行层由 Bookworm 包管理器安装 Python 和原生运行依赖。两个客户端镜像安装同一份 CLI 与内置 Lua，离线测试与 CI 内部镜像构建使用当前检出的提交，构建输入固定为当前检出。

[Windows 桥工作流](../.github/workflows/agent-bridge.yml) 另在 PR、`main` 推送和手动触发时执行 `Windows bridge build`。它在 Windows 2022 / VS2022 中从固定 Detours 源码构建 x86 库及桥 DLL，并上传含来源清单、日志和许可证的 `maple-agent-bridge-win32` 工件。构建与下载说明见[桥构建文档](../beidou-ijl15/docs/agent-bridge-build.md)。

## 本地复现

从仓库根执行，先初始化依赖：

```bash
git submodule update --init --recursive
```

准备 Python 3.14、`gcc/g++` 后，先构建当前检出目录的共享 IMG 解析库，再运行与 CI 相同的离线测试入口：

```bash
make -C headless build/libbeidou-img.so
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli -v
```

解析库是本地构建产物，新的 worktree 不会继承其他检出的产物；缺少它时，依赖地图、物品等静态资料的测试会返回 `img_parser_unavailable`，不能仅凭这些错误判定客户端逻辑回归。

在已准备的 `dev/NAME` 角色目录里将 `workbench.json.ref` 设为待测提交，后端选 `headless`。从仓库根运行以下命令，检查该提交的镜像和容器内 CLI（用实际角色名替换 `NAME`）：

```bash
mkdir -p tmp/ci-reproduction
workbenches/workbench dev/NAME build > tmp/ci-reproduction/build.json
image=$(jq -er .data.image tmp/ci-reproduction/build.json)
docker run --rm --entrypoint beidou-pilot "$image" --help
```

镜像构建不连接游戏服。CI job 内部直接使用 `docker/headless/Dockerfile`；工作台通过 `build` 使用选定的 Git 提交。打包检查显式选择 `beidou-pilot` 帮助入口。

再次执行同一条 `build` 并保存另一份结果，可比较 `data.preparation` 中各阶段的 `outcome/duration_ms` 与实际镜像 ID。GUI 报告复用已有桥 manifest。`data.current_instance` 用于核对所属实例与准备镜像的关系；准备不改变运行中的客户端。失败时结合 `error.stage`、已完成阶段及 stderr 定位问题，本次产物以实际构建结果为准。

网络需能下载子模块、基础镜像及 Debian 构建包。确认网络权限并按项目网络规则选择代理后，可在启动构建前导出 `HTTP_PROXY`、`HTTPS_PROXY` 和 `NO_PROXY`；统一入口按 Docker标准build args 透传这些变量。代理地址须能从构建网络访问，文档不固定本机地址。

GUI 角色在 `workbench.json` 选择 `backend="beidou"` 和客户端 `ref`，然后执行 `workbenches/workbench dev/GUI_NAME build`。默认由 `gh` 获取所选提交成功的 Windows 桥 CI 工件；`bridge_artifact` 可指定原生输入匹配的本地工件。运行时使用当前启动器配套的 GUI Compose，挂载原客户端、只读 `Data/` 和所选角色目录。GUI 与无头打包检查均须确认容器内 CLI 可执行。

## 查看结果与合并

在 PR 的 Checks 页面查看对应提交的检查，也可从仓库 [Actions](https://github.com/Diluka/beidou-pilot/actions/workflows/ci.yml) 页面查看日志。命令行入口为：

```bash
gh pr checks PR编号 --repo Diluka/beidou-pilot
```

代码或构建改动按惯例在 PR 当前提交的 `Python offline tests` 和 `Headless image build` 均通过后合并。失败、缺失、未运行或跳过的检查如实记录并处理；远端 CI 结果作为 CI 通过的依据。探索调试可先做本地检查和有界客户端试验；正式验收使用对应提交的检查结果。

纯文档修改按 [AGENTS.md](../AGENTS.md#开发与交付流程) 的简易流程直接提交并推送 `main`，以内容核对与差异检查为准。推送触发的自动检查仍保留，结果按实际状态记录。

CI 验收是日常协作约定，不配置为远端强制检查门禁。主分支的 `default` 规则仅保留禁止删除和非快进更新保护。

CI 的镜像检查覆盖无头镜像；完整 GUI 镜像需按改动在本地构建验证，Windows DLL 由独立工作流构建。CI 保持离线，实际游戏效果另行验证。正式验收、回归范围和证据复用统一按[验收约定](../AGENTS.md#验收方式)执行，只补实际受影响的路径；未改变组件的有效证据可引用复用。纯文档、CI 等不改变客户端运行行为的改动，可以在 PR 说明游戏试用不适用及理由。

## 版本与实例隔离验收

客户端验收使用与需求匹配的真实角色和场景。可在 `dev` 独立准备条件，再用所选提交的 GUI 或 headless 客户端执行并观察结果，作为正式证据。记录分区、版本、场景和实际结果；服务端设置或离线合同不替代游戏内验证。不得为准备样本操作常驻数据。

涉及两个实例时，在开发服选两个独立角色：A 以提交 X 启动，B 以提交 Y 启动，核对各自的 `source_revision/image/run_id`。A 的观察、最小动作、取消放键和关闭仍使用 X；B 使用 Y，A 关闭不影响 B 或开发服。统一入口路由与容器内真实结果分别记录；两端受影响的路径分别验证。

正式证据以 PR 提交及实际运行组件为准。由主提交导出的镜像对应已提交源码，GUI 工件需包含本次原生输入。已有实例保持启动时的版本，升级以正常关闭后新建实例完成。
