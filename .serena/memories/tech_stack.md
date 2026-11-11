# 技术与版本入口

- 唯一宿主入口 private/workbenches/workbench 是 Bash/Git/Docker/jq 脚本，调用形式为工作目录加命令；容器内仍使用 cli 提供的 beidou-pilot。headless 是原生无头宿主，beidou-ijl15 是原版桥 DLL 工程，harness 保持独立模型与角色消费者。
- headless 与 GUI 两个客户端 base 安装同一份 CLI 和 shared/scripts，分别提供无渲染或 Wine/VirtualGL 原生环境；两端共用 shared/lua-runtime 和固定 Lua 子模块。可选 harness 镜像继承对应 base，仅复用打包，增加 Node/Codex、Python harness 和专用客户端技能，不改变客户端 PID1。LLM 作为可选旁路独立启停，客户端与已启动脚本在无 LLM 时继续。
- workbench.json 的 harness 默认 false；true 时统一入口先构建客户端再派生 harness。model_proxy=http://IPv4:port 可选，未配置不影响客户端与脚本；仅在 harness 且代理非空时额外连接默认 bridge，GUI 只额外放行代理地址和端口。游戏服保留 internal 网络，外部 /client、/data 不变。
- 宿主 workbench DIR ai 以 docker exec 启动容器内 beidou-game-ai，其本地 app-server 和 shell 直接使用同容器 beidou-pilot。专用技能位于 /game/.agents/skills，公共文档按相对结构打包，不复制仓库 AGENTS、开发 HOME 或宿主技能；技能正文直接使用 CLI，Docker 用法为参考。
- 新建默认从 main 已提交版本构建或复用镜像，可选 workbench.json 保存 backend、ref、timeout 和明确的开发工件设置；已有实例按登记继续用启动版本，不重新加载当前宿主代码。
- 普通常驻服务器的项目、服务及公开镜像引用固定在统一入口中，继续核验真实容器和镜像。调试与实际游戏验收默认复用常驻服、已授权的已有账号角色和就绪实例以减少主机内存占用；仅在场景必须时新建账号或角色。特殊情况确需隔离服时记录原因，并在工作目录 workbench.json.server 显式配置为非 beidou-ms；不扩展直接修改正式数据库的权限。
- 公共资源路径只在主检出目录的 private/workbenches/resources.json 维护一份，开发 worktree 也共用；每目录提供 account.json、计划、用户 Lua 和运行数据。目录整体挂 /work，每个目录使用 default 容器；CLIENT_ROOT=/work/runtime/default/RUN_ID，脚本读 /work/scripts。原版 /client、NX /data 及可选 XML 保持现有解析语义。
- Docker 定义集中在 docker/：headless/Dockerfile 是唯一无头构建定义，gui/Dockerfile 与唯一 compose.yaml 交付 GUI，runtime/entrypoint.py 准备容器配置和登记。日常客户端运行不在宿主加载 Python 或游戏进程。
- GUI 桥由 Windows/MSVC CI 构建，统一入口默认经 gh 获取匹配提交的工件，显式开发工件也须匹配原生输入；桥路径在镜像内固定。依赖、版本和许可查 docs/DEPENDENCIES.md 及 third_party/UPSTREAM.json，不在记忆抄 hash。
- private/workbenches/workbench 是 private 下唯一 Git 例外；账号、共享配置、角色目录和运行数据保持忽略，不进入镜像或项目记忆。Serena 当前只启用项目记忆，不启动语言服务。
