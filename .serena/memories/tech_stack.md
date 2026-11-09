# 技术与版本入口

- 三个平级组件：cli负责Python标准库CLI与test，headless是原生无头宿主，beidou-ijl15是原版客户端DLL工程。命令入口cli/beidou-pilot，无根部启动包装。
- 两端共用shared/lua-runtime中的C++ Lua调度、State/Action/ActionResult和game绑定；以headless面向脚本接口为基准，DLL直接实现同一契约。共享脚本在shared/scripts，官方Lua依赖仍是third_party/lua子模块。
- Docker定义集中在docker/：docker/headless/Dockerfile定义无头builder/runtime，docker/gui/Dockerfile定义Wine/VirtualGL环境，docker/compose.yaml装配GUI；宿主不编译或运行游戏客户端。根.dockerignore对应无头的项目根构建上下文。准确基线、编译参数以构建定义为准。
- JSON/Lua/Detours官方子模块由gitlink锁定；派生引擎/转换器保持本地适配。版本、目录和许可统一查docs/DEPENDENCIES.md及third_party/UPSTREAM.json，不在记忆手抄版本/hash。
- Serena项目配置见.serena/project.yml，当前只启用记忆。需要符号服务时再单独确定范围，避免纳入第三方、资产和运行目录。
