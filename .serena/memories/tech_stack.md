# 技术与版本入口

- 唯一宿主入口 private/workbenches/workbench 是 Bash/Git/Docker/jq 脚本，调用形式为工作目录加命令；容器内仍使用 cli 提供的 beidou-pilot。headless 是原生无头宿主，beidou-ijl15 是原版桥 DLL 工程，harness 保持独立模型与角色消费者。
- headless 与 GUI 两个完整镜像安装同一份 CLI 和 shared/scripts，分别提供无渲染或 Wine/VirtualGL 原生环境；两端共用 shared/lua-runtime 和固定 Lua 子模块。
- 新建默认从 main 已提交版本构建或复用镜像，可选 workbench.json 保存 backend、ref、timeout 和明确的开发工件设置；已有实例按登记继续用启动版本，不重新加载当前宿主代码。
- 普通常驻服务器的项目、服务及公开镜像引用固定在统一入口中，继续核验真实容器和镜像。开发隔离目标必须在工作目录 workbench.json.server 显式配置为非 beidou-ms，不扩展正式数据写入权限。
- 公共资源路径只在主检出目录的 private/workbenches/resources.json 维护一份，开发 worktree 也共用；每目录提供 account.json、计划、用户 Lua 和运行数据。目录整体挂 /work，每个目录使用 default 容器；CLIENT_ROOT=/work/runtime/default/RUN_ID，脚本读 /work/scripts。原版 /client、NX /data 及可选 XML 保持现有解析语义。
- Docker 定义集中在 docker/：headless/Dockerfile 是唯一无头构建定义，gui/Dockerfile 与唯一 compose.yaml 交付 GUI，runtime/entrypoint.py 准备容器配置和登记。日常客户端运行不在宿主加载 Python 或游戏进程。
- GUI 桥由 Windows/MSVC CI 构建，统一入口默认经 gh 获取匹配提交的工件，显式开发工件也须匹配原生输入；桥路径在镜像内固定。依赖、版本和许可查 docs/DEPENDENCIES.md 及 third_party/UPSTREAM.json，不在记忆抄 hash。
- private/workbenches/workbench 是 private 下唯一 Git 例外；账号、共享配置、角色目录和运行数据保持忽略，不进入镜像或项目记忆。Serena 当前只启用项目记忆，不启动语言服务。
