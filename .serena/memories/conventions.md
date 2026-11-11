# 易误改约束

- 自维护代码排版与文件组织见[格式规范](../../docs/FORMATTING.md)，统一入口见[tools/format.py](../../tools/format.py)；只处理明确的新自维护白名单，历史编码和第三方例外按规范保留。
- 客户端运行代码来自实例镜像：private/workbenches/workbench 只管理工作目录、Git构建输入及Docker；Python CLI、辅助引擎和内置 Lua 在所属容器内执行。容器 --root/--backend/--instance 只核对本容器，不导入宿主或其他运行根的代码。
- 新实例默认固定 main 的已提交版本；已有实例通过 docker exec 使用启动时的 CLI 与内置 Lua，不能随主检出更新。工作目录整体挂 /work，根目录维护 account.json 和可选 workbench.json，公共资源只在主检出目录的 private/workbenches/resources.json 一份，开发 worktree 也共用；常驻服务器在脚本固定，开发隔离选择只在目录内显式声明。每个目录使用 default 容器，CLIENT_ROOT=/work/runtime/default/RUN_ID；脚本读 /work/scripts，继续隔离桥、锁与日志。
- private 下只有公共 workbench 脚本纳入 Git，其他账号、共享配置和运行数据继续忽略。GUI装配只有 docker/compose.yaml，不增加工作台子目录或可选资料的覆盖文件。原版 /client 与 NX /data 的格式、来源和只读挂载仍按当前支持边界，原始 IMG 直读需单独核实，不能随部署重命名就宣称实现。
- cli/test 使用包相对导入共享 BridgeFiles；开发子进程测试的 PYTHONPATH 指 cli 代码根。不要散放测试或多处 sys.path 补丁。
- Python 只在动作前静态规划，Lua 首动作核对原生 instance_id/CID/map/scene_generation；旧规划不能被新进程认领。
- 写脚本先查 docs/LUA_API.md，常规开发无需逐次读绑定；公共接口变化同步更新该文档，记忆不复制 API 清单。
- 基础操作属于 game API，shared/scripts 只保存复合能力；示例在其 examples 子目录，不自动加载。策略是初步脚手架，按实际行为迭代，详见 shared/scripts/AGENTS.md，不冻结旧参数或用兼容层掩盖原生错误。
- 原版 V17 跳跃绑定为 type5/id53，id51 是 sit；公共 jump 必须调用跳跃，不能在公共策略里恢复 GUI 专属补丁绕过原生映射错误。
- 宿主实例启停锁和容器动作锁独立；取消通过所属 CLI 收尾并确认放键，宿主 close 经 Docker 核对退出。放键、未知释放和游戏效果分别确认，详见 docs/CONTROL.md。
- 通用编码、授权、外部数据和记忆范围以 AGENTS.md 为准。
