# 第三方依赖管理

直接管理的第三方源码统一放根 `third_party/`，集成适配器放 `beidou-ijl15/`。准确仓库URL及派生来源/许可元数据见 [UPSTREAM.json](../third_party/UPSTREAM.json)，Git检出的子模块URL由 `.gitmodules` 声明，版本由父仓库gitlink锁定。文档不重复维护提交号或文件哈希。

| 组件 | 管理方式 |
| --- | --- |
| JSON、Lua、Detours | 固定官方提交的子模块，保持上游源码原样 |
| MapleStory-Client | 保留含HEADLESS、Linux及北斗接线的派生源码 |
| NoLifeWzToNx 派生 IMG 解码核心 | 仅保留原版 IMG 元数据与引用解析；移除 NX 写出、WZ 容器转换及转换器 CLI |
| BeiDou-ijl15 | 本仓库直接维护的DLL工程及共享控制Runtime |

## 初始化和更新

```bash
git submodule update --init --recursive
```

新检出也可使用 `git clone --recurse-submodules`。不使用 `git submodule update --remote`自动追踪分支。更新依赖先核对消费路径和接口，执行受影响构建，再提交新的gitlink。需要修改依赖时可以改用维护fork；已适配引擎替换为官方提交前需完成适配与验收。

子模块内部保持干净，自有说明放在项目文档或统一来源清单中。根构建入口按选定父提交的 gitlink 取依赖源码，子模块检出状态保持不变。

## 构建接线

- JSON使用官方 `single_include/nlohmann/json.hpp`。
- Lua官方Git源码在仓库根，Runtime通过 `extern "C"` 引入C标准头；解释器、测试及聚合源保留在源码树中，运行体只引入需要的部分。
- Detours固定与本项目头接口匹配的官方快照。Windows桥构建将对应源码复制到忽略的 `beidou-ijl15/out/detours/`，生成其中的 `lib.X86/`，不改写子模块；版本依据统一来源清单。
- 引擎内自带的NoLifeNx、GLFW和LZ4头保留上游树结构，随派生引擎维护。无头构建阶段安装 `liblz4-dev`，Bookworm 运行层通过 apt 安装 `libstdc++6` 与 `liblz4-1`，由发行版处理 glibc/libgcc 和加载器；系统库二进制不进入源码。生产 GBK 转换直接使用 glibc 的 iconv/gconv。

客户端镜像统一由[工作台入口](../private/workbenches/workbench) 的 `build` 或新实例 `open` 准备，按选定提交调用两份 Dockerfile。无头原生编译由 [Dockerfile](../docker/headless/Dockerfile) 内部调用 [Makefile](../headless/Makefile)；GUI 完整镜像使用 [GUI Dockerfile](../docker/gui/Dockerfile)，桥工件由 Windows/MSVC 工作流构建，统一入口默认经 `gh` 下载所选提交成功的 CI 工件；开发时可在工作目录配置中指定原生输入匹配的工件目录。Makefile 与 MSVC 保留为镜像交付链内部的编译工具，客户端构建与启动使用统一入口。基础环境和 VirtualGL 版本由 Docker 定义固定，运行资源与镜像职责见 [ARCHITECTURE](ARCHITECTURE.md)。

游戏 AI 镜像继承明确指定的 headless 或 GUI 客户端 base，从固定官方 Node Bookworm slim 构建阶段取得 Node 和标准 npm 安装的 Codex，完整保留 npm 平台包；缺失的 Codex 根许可从同版发行 tag 补齐。Python harness、专用客户端技能和必要公共文档随派生镜像打包，保留父镜像客户端入口；安装与许可说明见[容器说明](../docker/harness/README.md)。GUI 继续安装上游发布的 VirtualGL deb，使用可读的 Wine 镜像日期 tag。客户端 base 与 harness 衍生镜像保留清楚的版本/tag 与许可，采用包管理器默认校验，版本以标签固定。

连接已有 SSH Codex 会话的独立 `harness/game-events` 另用 `websockets==15.0.1`，由 [requirements-events.txt](../harness/requirements-events.txt) 固定并通过 pip 安装，保留发行包中的 BSD-3-Clause 许可与包元数据；上游为 [python-websockets/websockets](https://github.com/python-websockets/websockets)。它独立安装，与游戏镜像和 CLI 解耦；`game-ai` 继续使用标准库。安装和使用见 [HARNESS.md](HARNESS.md#向已有-ssh-codex-会话投递客户端事件)。

### GUI 构建下载排障

GUI Dockerfile 从 [VirtualGL 官方 3.1.5 发布](https://github.com/VirtualGL/virtualgl/releases/tag/3.1.5)下载 `virtualgl_3.1.5_amd64.deb` 和 `virtualgl32_3.1.5_amd64.deb`。构建失败先保留 `build` 的 JSON 阶段结果及标准错误，确认失败的是包下载、Windows 桥工件还是其他步骤。

可对两份包分别做有界连接检查；下面只验证下载，不启动客户端：

```bash
for package in virtualgl virtualgl32; do
    curl --fail --location --connect-timeout 10 --max-time 45 --output /dev/null \
        "https://github.com/VirtualGL/virtualgl/releases/download/3.1.5/${package}_3.1.5_amd64.deb"
done
```

`curl` 退出码 28、HTTP 000 表示本次未取得有效 HTTP 响应，需结合连接日志检查网络出口；发布资产存在与下载成功分别核对。若直接连接超时而已有 HTTP 代理下载成功，可将 Docker 构建阶段可达的代理地址传给统一入口（将占位地址和工作目录替换为实际配置）：

```bash
HTTP_PROXY=http://PROXY_HOST:PORT HTTPS_PROXY=http://PROXY_HOST:PORT \
    NO_PROXY=localhost,127.0.0.1 private/workbenches/workbench DIR build
```

入口已将 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 传给 Docker 构建。构建容器内的 `127.0.0.1` 指向容器自身，代理地址需使用容器可达的地址。该设置用于构建下载，运行时模型代理仍由 `workbench.json.model_proxy` 单独配置。保留固定版本和官方来源；恢复下载后继续核对完整镜像构建、客户端启动和已有角色接续，各项分别记录结果。

## 许可与外部资产

项目级 [LICENSE](../LICENSE) 为AGPL-3.0-only；第三方保留各自版权与授权，汇总见 [NOTICE](../NOTICE)，其中包含Lua版权和MIT全文。分发构建需要携带适用许可。

无头运行层沿用 Debian 的系统版权与公共许可目录，另保留项目及编入客户端的第三方声明；GUI 与 harness 镜像也携带项目和实际分发组件的适用许可。运行镜像沿用系统许可目录。

北斗原始客户端、7z、EXE/DLL、IMG/WZ、账号和运行状态继续外部提供；运行时直接读取只读 IMG。
