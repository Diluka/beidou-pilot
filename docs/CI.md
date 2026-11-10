# CI 与合并验收

[CI 工作流](../.github/workflows/ci.yml) 在 PR 创建、重新打开或更新提交时运行，也在提交进入 `main` 后运行。每次运行包含两项独立检查：

| 检查名称 | 执行内容 |
| --- | --- |
| `Python offline tests` | Ubuntu 24.04、Python 3.14，运行现有 CLI 离线合同测试 |
| `Headless image build` | Ubuntu 24.04，使用 `docker/headless/Dockerfile` 构建无头镜像 |

两个任务都从当前提交检出源码并递归初始化固定版本子模块。Python 测试只使用标准库，无需安装 pip 依赖；其中 Lua 任务合同使用 runner 自带的 `gcc/g++` 编译真实共享 Runtime 和固定 Lua 源码，适配器只模拟原生输入与释放边界。无头镜像的编译器和系统库由 `docker/headless/Dockerfile` 的 builder 安装。

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

安装并启动 Docker 后构建无头镜像：

```bash
docker build --file docker/headless/Dockerfile --tag local/beidou-pilot:ci .
```

构建只使用源码与固定依赖，不需要游戏素材、账号、profile 或游戏服务器访问，不推送镜像。网络需能下载子模块、基础镜像及 Debian 构建包。

## 查看结果与合并

在 PR 的 Checks 页面查看对应提交的两项检查，也可从仓库 [Actions](https://github.com/Diluka/beidou-pilot/actions/workflows/ci.yml) 页面查看日志。命令行入口为：

```bash
gh pr checks PR编号 --repo Diluka/beidou-pilot
```

PR 当前提交的 `Python offline tests` 和 `Headless image build` 都必须成功才满足 CI 验收。失败、缺失、未运行或跳过的必需检查都保留为待验收；本地成功不能代替远端 CI 结果。PR 后续更新影响已验证结论时，按新提交重新检查。

主分支的 `default` 规则已将这两项 GitHub Actions 检查设为必需检查，并要求分支与基线保持同步；原有禁止删除和非快进更新规则继续保留，没有设置绕过者。

CI 的镜像检查覆盖无头镜像；GUI Wine/VirtualGL 镜像需按改动在本地构建验证，Windows DLL 由独立工作流构建。CI 不连接真实游戏或证明实际游戏效果。CI 通过后，按[验收约定](../AGENTS.md#验收方式)使用改动涉及的真实客户端进入游戏试用；纯文档、CI 等不改变客户端运行行为的改动，可以在 PR 说明游戏试用不适用及理由。
