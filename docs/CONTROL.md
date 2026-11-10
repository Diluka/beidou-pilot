# Lua 与原生控制

## 执行入口

用户策略使用 `script run FILE --seconds N` 或 `script run --code CODE --seconds N`，文件和源码二选一，需要持续运行时明确 `--continuous`。两种输入复用同一装载、身份核对、错误、取消与放键链，可在现有实例中执行，无需重启客户端。基础动作直接调用统一 `game` API；复合能力装载 `shared/scripts/` 的 Lua 文件，调用方传入业务参数，Python只处理参数、生命周期与结果。

```bash
./cli/beidou-pilot --backend headless --instance worker-a --json script run --code 'game.log("你好，Lua")' --seconds 20
./cli/beidou-pilot --backend headless --instance worker-a --json script run /path/control.lua --seconds 20
./cli/beidou-pilot --backend headless --instance worker-a --json script status
```

原始按键与直接技能也是 Lua 的原版扩展。持续动作、分支和循环直接写 Lua；没有宏表达式、JSON 动作预设或 Python 反馈控制层。

## 统一契约与策略分层

以 headless 当前面向脚本的 `State`、`Action`、`ActionResult` 为共同标准，唯一绑定与调度实现在 `shared/lua-runtime/`。原版 DLL 直接提供这一模型，不经旧 GameState 或 LuaController 兼容层；外部命令只接受脚本与停止，不保留旧直接 keys/skill 命令。

相同函数签名与事实边界用于两端，各端读取对象、调用原生输入或技能的实现留在适配器。可选按键/技能能力由 `game.capabilities()` 声明，headless 未支持时明确拒绝；已知程度不同的物理收束等信息保留未知，不伪造对齐。公共 `use_item` 限普通200类恢复药品。

GUI普通200类用药按物品ID与实际消费槽直接调用原生入口，不查键位。请求仍只占一个活动动作，在Lua恢复栈外的原生阶段消费；未派发时可取消，调用已进入只证明本地派发，不承诺撤销药品消耗或确认恢复。显式 `keys/press` 和其他语义动作的现有路径分别保留。

```text
shared/scripts/
  travel/move_to.lua       同层坐标反馈与到达确认
  travel/climb_to.lua      绳梯靠近、对齐及攀爬
  travel/enter_portal.lua  门户接近、进入及转场确认
  travel/_common.lua       旅行能力实际复用的检查与对齐
  combat/fight.lua         目标选择、战斗、补给、拾取与撤退
  recovery/recover.lua     按次数或HP/MP目标用药并确认效果
  examples/               少量公共API示例，不由正式能力加载
```

基础操作是 `game` API 的积木，不创建逐一转发脚本。策略当前是初步脚手架，已有参数、时序和流程需按实际情况迭代，局部维护约定见 [shared/scripts/AGENTS.md](../shared/scripts/AGENTS.md)。执行期限、取消与放键由公共运行时提供；`_common.lua`不是操作入口，不预建未来能力目录。

## 脚本 API 入口

编写脚本先阅读 [Lua API 参考](LUA_API.md)。该文档集中维护完整状态结构、能力字段、函数签名、默认参数、返回值、错误和标准库限制，本篇只说明执行与控制协议。

公共接口变更时，运行时实现和 API 参考在同一改动中更新；策略不通过重复实现基础操作来补出未声明的接口。共享策略仍按其局部维护约定迭代，不把已有参数视为成熟契约。

## 控制权、期限与取消

同一实例只有一个活动动作控制 CLI。一个脚本会话内可通过 `game.spawn/acquire/cancel/tasks` 协作运行多个 Lua 任务；它们共享 Lua 状态，由公共 Runtime 串行派发原生动作。任务等待动作或控制权时，其他任务继续观察和判断。主任务返回后子任务继续，全部任务结束且放键确认后会话结束。公共接口与示例见 [Lua API 的任务与控制权](LUA_API.md#任务与控制权)。

动作控制按任务归属。高优先级任务可请求接管，旧任务立即失去派发资格，原生确认释放后新任务取得控制；相同优先级保持当前控制者。被接管动作返回标准结果并标记 `reason=control_preempted`，游戏效果保持未知。旧任务重新取得控制后读取新状态并规划，运行时不保留待重放动作。指定任务取消、正常返回或 `game.stop()` 只释放该任务仍拥有的输入；停止原任务不能释放后续控制者的输入。`keys/press/skill` 同样受任务归属约束。

GUI按键由适配器保留单份最新期望集合，Lua调用提交后，实际按键在运行时与管理请求处理返回后的原生更新阶段派发。原生NPC窗口处理可以同步进入嵌套更新，此时Lua恢复栈已经归还，嵌套更新继续处理释放、观察和后续脚本。新请求或取消会使旧按下批次失效；已经持有的按键仍需完整发送keyup，并在全部投递返回后等待真实角色消费确认。该阶段划分不增加请求队列，也不改变直接技能的同步返回语义。

`script status` 通过 `script.tasks` 展示任务名称、revision、状态、优先级与等待原因，通过 `script.control` 展示控制者、待取得控制的任务及最近交接原因。现有任务可按条件创建其他任务；外部程序通过 `task add/replace/stop` 管理指定会话中的独立任务，文件和直接源码两种输入见 [CLI参考](CLI.md)。第二次 `script run` 继续受同实例控制锁与原生 busy 检查约束。

任务管理使用独立短锁与 `task-request.txt`，原会话 CLI 继续拥有动作锁及原始 `command.id`。两端使用同一份 `TaskTransport` 解析请求并调用共享 Runtime；它们不从管理入口直接派发原生输入。请求绑定原生 `instance_id/run_id` 与 `script.id`，替换、停止还核对任务 `revision`；新增、替换核对场景代次。源码文件仍原子放在 `scripts/`，结果按请求 ID 保存在 `task-results/`，不覆盖动作或只读观察响应。

替换先编译独立chunk，成功前不改变旧任务。编译后旧版本停止派发，运行时按旧任务的输入归属等待释放确认，再安装同名新版本。管理等待超时或中断不会停止整会话；原会话的取消、期限和角色身份规则仍优先生效，未完成的替换不会在会话结束后安装。管理结果写入失败时宿主以 `task_result_write_failed` 进入既有整会话停止与放键路径，避免丢失反馈后继续控制。

运行中的脚本通过原 CLI 的 Ctrl+C/SIGTERM 或调用方取消标记停止全部任务；期限到达、角色身份变化、离开游戏及任一脚本错误也停止整个会话。桥等待实际放键后返回，只读状态和领域查询仍可并行。

空闲时 `stop`/`bridge stop` 清理遗留控制，不抢占另一个活动动作控制者。无头容器 `open/close` 使用独立生命周期锁，`close` 可以结束活动 Lua 及整个实例；同实例正在启停时返回 `lifecycle_busy`。

Lua 期限控制整个脚本会话，容器没有进程自退期限。脚本结束、超时或取消不关闭容器；`close`/Docker stop 才关闭实例。真实断线和错误会退出并保留原因，调用方决定是否重开，不自动重放旧动作。

动作结果按层次解释：请求接受、输入派发、输入释放、动作收束、游戏效果分别确认。`completed`、原生调用非零或 `held_keys=[]` 都不能单独证明命中或拾取成功；释放后攻击动画、空中运动和受击惯性仍可能继续。采样失效或身份变化时不向后继实例补发控制，释放未确认时返回 `bridge_release_unconfirmed`。

## 观察与传输

CLI 通过原生观察 API 消费 `stage/scene/inventory/character/quests/hotkeys/dialog/ui/shop`。前五域两端共用，后四域为原版 UI 扩展。原版在游戏线程读取 V17 对象，DLL 内部仍依赖版本布局；无头端读取自己的游戏对象，外部 Python 不读取游戏进程内存。

活动 Lua 通过 `game.observe(domain)` 按需调用相同原生采集函数，共享值类型和 Lua 投影由 `shared/lua-runtime/` 维护，不经文件传输、JSON 文本往返或 Python 反馈。查询不需要动作控制权；响应附带当前实例、角色、地图、场景代次及采样时间。轻量 `game.state()` 保持独立，不在每帧采集所有领域；调用者在等待或动作后重新读取。无头任务仍是登录快照，GUI 桌面几何增强不属于原生 Lua 数据，完整字段与未知语义见 [Lua API](LUA_API.md#按需领域观察)。

只读 `observation-request.txt/observation.json` 与动作/Lua的 `command.txt/state.json` 使用独立通道。响应核对请求ID、原生 `instance_id/run_id`、序号和采样年龄；实例名只选择工具会话，不能代替进程身份。请求派发不覆盖活动 Lua。

原版 checksum 保留真实校验结果；无头没有执行的校验为 `null`，另用 `native_values_valid` 表达值是否可用。无头对话/可见性及未实现领域保持明确未知或不支持。

## 原版桌面边界

`engines/desktop.py`只承担登录、鼠标、滚轮、截图和短线性 GUI 操作。当前 Lua 无接口的装备、非普通200类可用物品和传送卷等工作流继续使用桌面实现，不承担角色持续策略。

匹配的 `ijl15.dll` 只安装到独立 GUI 运行副本，并登记构建清单；EXE、原代理 DLL 和桥 DLL 的实际指纹由 [binaries.py](../cli/beidou_pilot/binaries.py) 核验。完整客户端素材和 GUI 环境均由外部准备。
