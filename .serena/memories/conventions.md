# 易误改约束

- 自维护代码排版与文件组织见[格式规范](../../docs/FORMATTING.md)，统一入口见[tools/format.py](../../tools/format.py)；只处理明确的新自维护白名单，历史编码和第三方例外按规范保留。
- 宿主 workbenches/workbench 管理分区、版本和容器。Python CLI、辅助引擎和内置 Lua 在所属客户端镜像内执行；容器 --root/--instance 仅核对本容器身份。
- 客户端镜像按角色 ref（默认 main）固定到已提交版本。工作目录整体挂 /work；每个角色用 default 容器，CLIENT_ROOT=/work/runtime/default/RUN_ID。角色标识决定 live/dev 目标，配置错误不回退。长期授权、开发样本和验收边界见 AGENTS.md。
- 私密账号、分区定义、共享资源配置和运行数据全部留在主检出 private/workbenches/。GUI Compose 由当前启动器提供；客户端依旧使用只读原版资源和共享原生 IMG 解析器。资源边界变化时同步维护 docs/ARCHITECTURE.md 与客户端 Docker 参考。
- cli/test 使用包相对导入共享 BridgeFiles；开发子进程测试的 PYTHONPATH 指 cli 代码根。测试集中放在 cli/test 并统一由包相对导入处理路径。
- Python 只做参数、装载/取消和结果投影，角色控制策略写在 Lua；tick 脚本在入口及每次采样核对原生 instance_id/CID/map/scene_generation，旧规划只作用于原进程。
- tick Lua 状态契约：`context.game.player` 动作设置返回 `ok, reason`，只表示本 tick 意图草稿受理；观察领域未知字段为 `nil` 或带 status/error，不把缺失字段当已知。核对脚本断言时不要按测试替身可造出的缺字段推断。
- 写脚本先查 docs/LUA_API.md 导航，接口细节以 docs/LUA_TICK_API.md 为准；公共接口变化同步更新该文档，记忆只保存入口。
- 文档按 docs/README.md 分层：当前能力、设计与路线、研究记录分开写；计划中的接口不能写成已支持，历史临时证据路径不能当作可访问入口。
- shared/scripts 只保存随镜像固定的 tick 示例和校准探针，由调用方显式加载；真实策略写在用户工作台 /work/scripts，应用层（伴游机器人）也放在用户工作台。示例按实际游戏事实迭代，详见 shared/scripts/AGENTS.md；原生错误从源头修复。
- 客户端只有原版 GUI 后端；一个角色一个客户端/一个控制者。聊天、队伍、NPC 交互、运行时路线、交易、手动 AP 是待补能力，不能按计划文档宣称已可用；机器人包迁移到 GUI 尚未完成；养成走停手→handover→维护窗口→重启。
- 原版 V17 跳跃绑定为 type5/id53，id51 是 sit；公共 jump 必须调用跳跃，GUI 专属补丁保留在 GUI 适配层。
- 原生脚本由所属 TickRuntime 持有生命周期。script run 同步等结果，script start 等受理；CLI 中断、等待超时或观察失败只结束等待，已发布脚本继续运行。多会话从 scripts 按 script.id 核对状态，script 仅为最近接纳会话；明确取消用 script cancel --session 并核对该会话终态和放键，客户端另行 close。
- tick 只在宿主帧结束统一提交草稿；正常结束/abort_commit=true 的一次性动作须先经原生消费再终态，显式取消/期限可打断。方向变更确认与动作释放独立，取消动作不能对其他会话方向产生额外边沿；具体合同见 TickRuntime、两端 tick 适配器及 cli/test/tick_*_contract.cpp。
- 宿主实例启停锁和容器动作锁独立；取消通过所属 CLI 收尾并确认放键，宿主 close 经 Docker 核对退出。放键、未知释放和游戏效果分别确认，详见 docs/CONTROL.md。
- 通用编码、授权、外部数据和记忆范围以 AGENTS.md 为准。
