# 易误改约束

- 自维护代码排版与文件组织见[格式规范](../../docs/FORMATTING.md)，统一入口见[tools/format.py](../../tools/format.py)；只处理明确的新自维护白名单，历史编码和第三方例外按规范保留。
- 客户端运行代码来自实例镜像：private/workbenches/workbench 只管理工作目录、Git构建输入及Docker；Python CLI、辅助引擎和内置 Lua 在所属容器内执行。容器 --root/--backend/--instance 只核对本容器，不导入宿主或其他运行根的代码。
- 新实例默认固定 main 的已提交版本；已有实例通过 docker exec 使用启动时的 CLI 与内置 Lua，版本与主检出当前内容无关。工作目录整体挂 /work，根目录维护 account.json 和可选 workbench.json，公共资源只在主检出目录的 private/workbenches/resources.json 一份，开发 worktree 也共用；常驻服务器在脚本固定，调试和实际游戏验收默认复用常驻服与已授权的已有账号角色及就绪实例，仅在场景必须时新建账号或角色，特殊情况确需隔离服时记录原因并在目录内显式声明。每个目录使用 default 容器，CLIENT_ROOT=/work/runtime/default/RUN_ID；脚本读 /work/scripts，继续隔离桥、锁与日志。
- private 下只有公共 workbench 脚本纳入 Git，其他账号、共享配置和运行数据继续忽略。GUI装配统一使用 docker/compose.yaml。原版 `/client` 与 `Data/` `/data` 使用同一只读原件；无头资源和 Python 静态查询通过共享原生 IMG 解析器读取，GUI 客户端从 `/client` 读取运行资源。资源边界变化时同步维护 `docs/ARCHITECTURE.md` 与客户端 Docker 参考。
- cli/test 使用包相对导入共享 BridgeFiles；开发子进程测试的 PYTHONPATH 指 cli 代码根。测试集中放在 cli/test 并统一由包相对导入处理路径。
- Python 只做参数、装载/取消和结果投影，角色控制策略写在 Lua；tick 脚本在入口及每次采样核对原生 instance_id/CID/map/scene_generation，旧规划只作用于原进程。
- tick Lua 状态契约：`context.game.player` 动作设置返回 `ok, reason`，只表示本 tick 意图草稿受理；观察领域未知字段为 `nil` 或带 status/error，不把缺失字段当已知。核对脚本断言时不要按测试替身可造出的缺字段推断。
- 写脚本先查 docs/LUA_API.md 导航，接口细节以 docs/LUA_TICK_API.md 为准；公共接口变化同步更新该文档，记忆只保存入口。
- shared/scripts 只保存随镜像固定的 tick 示例，由调用方显式加载；真实策略写在用户工作台 /work/scripts。示例按实际游戏事实迭代，详见 shared/scripts/AGENTS.md；原生错误从源头修复。
- 原版 V17 跳跃绑定为 type5/id53，id51 是 sit；公共 jump 必须调用跳跃，GUI 专属补丁保留在 GUI 适配层。
- 原生脚本由所属 TickRuntime 持有生命周期。script run 同步等结果，script start 等受理；CLI 中断、等待超时或观察失败只结束等待，已发布脚本继续运行。多会话从 scripts 按 script.id 核对状态，script 仅为最近接纳会话；明确取消用 script cancel --session 并核对该会话终态和放键，客户端另行 close。
- tick 只在宿主帧结束统一提交草稿；正常结束/abort_commit=true 的一次性动作须先经原生消费再终态，显式取消/期限可打断。方向变更确认与动作释放独立，取消动作不能对其他会话方向产生额外边沿；具体合同见 TickRuntime、两端 tick 适配器及 cli/test/tick_*_contract.cpp。
- 宿主实例启停锁和容器动作锁独立；取消通过所属 CLI 收尾并确认放键，宿主 close 经 Docker 核对退出。放键、未知释放和游戏效果分别确认，详见 docs/CONTROL.md。
- harness 普通模式为 cli-v1，shell 直接调用本容器 CLI，无 game_run_lua/game_hunt 动态动作包装；read_only 只保留 game_observe/game_script_status 两个观察工具。LLM 与客户端和 Lua 独立启停，暂停/退出模型时 shell、脚本与客户端保持运行；重新接入先观察已有脚本及控制归属。模型进程与状态目录锁只保护模型会话，角色与脚本控制权以原生状态为准。脚本取消需显式 script cancel --session 并核对原生终态和放键，客户端关闭另行 close；完整合同见 docs/HARNESS.md、docs/CONTROL.md。
- harness 状态按稳定工作目录、角色/世界、目标项目/服务、CLI 路径及 read_only 绑定，不绑定临时容器/run；跨新客户端运行续接时重读原生身份与事实。旧 lua-v1/hunt-v1 或无工具面状态明确拒绝，旧目录按历史保留并新建 state。模型会话和经历不进入客户端库或项目记忆，完整合同见 docs/HARNESS.md。
- 通用编码、授权、外部数据和记忆范围以 AGENTS.md 为准。
