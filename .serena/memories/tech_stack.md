# 技术与版本入口

- 根 beidou-pilot 是宿主 Bash/Git/Docker/jq 薄入口。cli 提供两个镜像共用的 Python 标准库 CLI 与 test；headless 是原生无头宿主，beidou-ijl15 是原版桥 DLL 工程。harness 保持独立模型与角色消费者。
- 客户端运行交付为 headless 与 GUI 两个完整镜像，安装同一份 CLI 和 shared/scripts；分别提供原生无渲染或 Wine/VirtualGL 环境。两端共用 shared/lua-runtime 中的 C++ Lua 调度和 game 绑定，官方 Lua 是固定子模块。
- 新实例从 main 的已提交版本构建或复用镜像，显式 --ref 用于开发验收；已有实例代码随镜像固定。启动登记和原生 instance_id/run_id 分别核对容器与游戏会话，日常命令通过 docker exec 执行。
- Docker 定义集中在 docker/：headless/Dockerfile 是唯一无头构建定义，gui/Dockerfile 与唯一 compose.yaml 交付 GUI，runtime/entrypoint.py 准备容器配置和登记。两端用根构建上下文，宿主不运行 Python 客户端或游戏进程。
- 工作台整体读写挂到 /work，根目录提供 account.json/server.json 与外部 resources.json。实例运行根为 /work/runtime/INSTANCE/RUN_ID，角色脚本直接读 /work/scripts。原版 /client、NX /data 与可选 XML 保留各自现有读取语义；不会因挂载调整自动改为原始 IMG 直读。
- GUI 桥由 Windows/MSVC CI 构建，根入口默认通过 gh 获取所选提交成功的工件；开发可显式复用原生输入匹配的工件。运行桥路径由镜像内固定配置产生。
- JSON/Lua/Detours 官方子模块由 gitlink 锁定；派生引擎/转换器保留适配。来源、目录和许可查 docs/DEPENDENCIES.md 与 third_party/UPSTREAM.json，不在记忆手抄版本/hash。
- Serena 项目配置见 .serena/project.yml，当前只启用项目记忆。需要符号服务时再确定范围，避免纳入第三方、资产和运行目录。游戏资源、账号和运行数据不写入记忆。
