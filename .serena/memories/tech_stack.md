# 技术与版本入口

- 宿主通过 workbenches/workbench 的 live/NAME、dev/NAME 选择角色；容器内使用 beidou-pilot。headless 是原生无头宿主，beidou-ijl15 是原版桥 DLL 工程。
- headless 与 GUI 两个客户端镜像安装同一份 CLI 和 shared/scripts，分别提供无渲染或 Wine/VirtualGL 原生环境；两端共用 shared/lua-runtime 和固定 Lua 子模块。
- 新建默认从 main 已提交版本构建或复用镜像，可选 workbench.json 保存 backend、ref、timeout 和明确的开发工件设置；已有实例按登记继续用启动版本，与当前宿主代码无关。
- 两区服务器和资源配置都在主检出 private/workbenches/config/。开发服具备独立网络和数据；server dev 管理其生命周期与服务端 CLI，日常 stop 保留数据，角色 close 不停服。配置和样例见 workbenches/README.md。
- 角色目录挂 /work；live 的 PLAN.md 记录养成，dev 的 STATE.md 记录当前可复现条件；/work/scripts 是用户脚本相对路径的基准。原版客户端只读挂载 /client，原版 Data/ 只读挂载 /data；无头运行时和 Python Catalog 经共享 IMG 解析库读取。
- docker/headless/Dockerfile、docker/gui/Dockerfile 构建角色所选版本的镜像，GUI 用启动器配套的 docker/compose.yaml 装配；开发服部署与客户端构建分开。
- GUI 桥由 Windows/MSVC CI 构建，统一入口默认经 gh 获取匹配提交的工件，显式开发工件也须匹配原生输入；桥路径在镜像内固定。依赖、版本和许可查 docs/DEPENDENCIES.md 及 third_party/UPSTREAM.json，不在记忆抄 hash。
- 公共入口和说明放 workbenches/，整个 private/ 保持忽略；账号和运行数据不进入镜像或项目记忆。Serena 只启用项目记忆，不启动语言服务。
