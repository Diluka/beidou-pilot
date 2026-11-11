# 第三方依赖管理

直接管理的第三方源码统一放根 `third_party/`，集成适配器放 `beidou-ijl15/`。准确仓库URL及派生来源/许可元数据见 [UPSTREAM.json](../third_party/UPSTREAM.json)，Git检出的子模块URL由 `.gitmodules` 声明，版本由父仓库gitlink锁定。文档不重复维护提交号或文件哈希。

| 组件 | 管理方式 |
| --- | --- |
| JSON、Lua、Detours | 固定官方提交的子模块，保持上游源码原样 |
| MapleStory-Client | 保留含HEADLESS、Linux及北斗接线的派生源码 |
| NoLifeWzToNx | 保留metadata-only等资源转换适配 |
| BeiDou-ijl15 | 本仓库直接维护的DLL工程及共享控制Runtime |

## 初始化和更新

```bash
git submodule update --init --recursive
```

新检出也可使用 `git clone --recurse-submodules`。不使用 `git submodule update --remote`自动追踪分支。更新依赖先核对消费路径和接口，执行受影响构建，再提交新的gitlink。需要修改依赖时可以改用维护fork；不能将已适配引擎直接替换成未经适配的官方提交。

子模块内部保持干净，自有说明放在项目文档或统一来源清单中，不另建版本迁移资料目录。根构建入口按选定父提交的 gitlink 取依赖源码，不改变子模块当前检出或自动追踪上游分支。

## 构建接线

- JSON使用官方 `single_include/nlohmann/json.hpp`。
- Lua官方Git源码在仓库根，Runtime通过 `extern "C"` 引入C标准头；解释器、测试及聚合源不编入运行体。避免恢复发布归档的 `src/` 或 `lua.hpp` 假设。
- Detours固定与本项目头接口匹配的官方快照，不用近似tag替换。Windows桥构建将对应源码复制到忽略的 `beidou-ijl15/out/detours/`，生成其中的 `lib.X86/`，不改写子模块；版本依据统一来源清单。
- 引擎内自带的NoLifeNx、GLFW和LZ4头保留上游树结构，随派生引擎维护，不拆成重复副本。无头构建阶段安装 `liblz4-dev`，Bookworm 运行层通过 apt 安装 `libstdc++6` 与 `liblz4-1`，由发行版处理 glibc/libgcc 和加载器；系统库二进制不进入源码。生产 GBK 转换使用 glibc 的 iconv/gconv，不手工复制模块或组装根文件系统。

客户端镜像统一由[工作台入口](../private/workbenches/workbench) 的 `build` 或新实例 `open` 准备，按选定提交调用两份 Dockerfile。无头原生编译由 [Dockerfile](../docker/headless/Dockerfile) 内部调用 [Makefile](../headless/Makefile)；GUI 完整镜像使用 [GUI Dockerfile](../docker/gui/Dockerfile)，桥工件由 Windows/MSVC 工作流构建，统一入口默认经 `gh` 下载所选提交成功的 CI 工件；开发时可在工作目录配置中指定原生输入匹配的工件目录。Makefile 与 MSVC 保留为镜像交付链内部的编译工具，客户端构建与启动使用统一入口。基础环境和 VirtualGL 版本由 Docker 定义固定，运行资源与镜像职责见 [ARCHITECTURE](ARCHITECTURE.md)。

游戏 AI 镜像使用官方 Node Bookworm slim 与标准 npm 安装固定 Codex，完整保留 npm 平台包；缺失的 Codex 根许可从同版发行 tag 补齐，安装说明见[容器说明](https://github.com/Diluka/beidou-pilot/blob/main/docker/harness/README.md)。GUI 继续安装上游发布的 VirtualGL deb，使用可读的 Wine 镜像日期 tag。三类镜像保留清楚的版本/tag 与许可，采用包管理器默认校验，不再另写镜像 digest、下载或许可 hash 检查。

连接已有 SSH Codex 会话的独立 `harness/game-events` 另用 `websockets==15.0.1`，由 [requirements-events.txt](../harness/requirements-events.txt) 固定并通过 pip 安装，保留发行包中的 BSD-3-Clause 许可与包元数据；上游为 [python-websockets/websockets](https://github.com/python-websockets/websockets)。它不编入游戏镜像或 CLI，也不改变既有 `game-ai` 的标准库依赖边界。安装和使用见 [HARNESS.md](HARNESS.md#向已有-ssh-codex-会话投递客户端事件)。

## 许可与外部资产

项目级 [LICENSE](../LICENSE) 为AGPL-3.0-only；第三方保留各自版权与授权，汇总见 [NOTICE](../NOTICE)，其中包含Lua版权和MIT全文。分发构建需要携带适用许可。

无头运行层沿用 Debian 的系统版权与公共许可目录，另保留项目及编入客户端的第三方声明；GUI 与 harness 镜像也携带项目和实际分发组件的适用许可。运行镜像不通过反查 dpkg 归属再复制一套系统许可。

北斗原始客户端、7z、EXE/DLL、IMG/WZ、转换NX、账号和运行状态继续外部提供，不作为代码子模块引入。
