# 第三方依赖管理

直接管理的第三方源码统一放根 `third_party/`，集成适配器放 `beidou-ijl15/`。准确仓库URL及派生来源/许可元数据见 [UPSTREAM.json](../third_party/UPSTREAM.json)，Git检出的子模块URL由 `.gitmodules` 声明，版本由父仓库gitlink锁定。文档不重复维护提交号或文件哈希。

| 组件 | 管理方式 |
| --- | --- |
| JSON、Lua、Detours | 固定官方提交的子模块，保持上游源码原样 |
| NoLifeWzToNx 派生 IMG 解码逻辑 | 已并入资源适配器内部，不再维护独立转换器目录；来源与许可保留于 NOTICE，密钥数据单独存放于 ImgKeys.cpp |
| BeiDou-ijl15 | 本仓库直接维护的DLL工程及共享 tick Lua Runtime |

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

客户端镜像统一由[工作台入口](../workbenches/workbench) 的 `build` 或新实例 `open` 准备，按选定提交调用 [GUI Dockerfile](../docker/gui/Dockerfile)。共享 IMG 解析库由 [shared/img/Makefile](../shared/img/Makefile) 在本地离线构建，镜像构建时直接编译同一份源码。桥工件由 Windows/MSVC 工作流构建，统一入口默认经 `gh` 下载所选提交成功的 CI 工件；开发时可在工作目录配置中指定原生输入匹配的工件目录。MSVC 保留为镜像交付链内部的编译工具，客户端构建与启动使用统一入口。基础环境和 VirtualGL 版本由 Docker 定义固定，运行资源与镜像职责见 [ARCHITECTURE](ARCHITECTURE.md)。

GUI 使用带日期标签的 Wine 镜像，并安装上游发布的 VirtualGL deb。客户端镜像保留组件版本、标签及适用许可，使用包管理器的默认校验。

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
    NO_PROXY=localhost,127.0.0.1 workbenches/workbench dev/NAME build
```

入口已将 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 传给 Docker 构建。构建容器内的 `127.0.0.1` 指向容器自身，代理地址需使用构建容器可达的地址。保留固定版本和官方来源；恢复下载后继续核对完整镜像构建、客户端启动和已有角色接续，各项分别记录结果。

## 许可与外部资产

项目级 [LICENSE](../LICENSE) 为AGPL-3.0-only；第三方保留各自版权与授权，汇总见 [NOTICE](../NOTICE)，其中包含Lua版权和MIT全文。分发构建需要携带适用许可。

GUI 运行层沿用 Debian 的系统版权与公共许可目录，另保留项目及实际分发组件的适用许可。

北斗原始客户端、7z、EXE/DLL、IMG/WZ、账号和运行状态继续外部提供；运行时直接读取只读 IMG。
