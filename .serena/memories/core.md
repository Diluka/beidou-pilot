# 项目导航与边界

- 按领域的业务导航见 `docs/business-map/README.md`；各领域 YAML 共同组成 Semantic Atlas 图，查询和维护后仍需回到当前源码及正式文档核实。
- `AGENTS.md`是维护约定入口，统一维护需求入池、sub-issue拆分、自主验收与合并、真实客户端试用规则；正式架构/支持边界见docs/ARCHITECTURE.md，命令见docs/CLI.md，写Lua脚本的接口参考见docs/LUA_API.md，桥执行契约见docs/CONTROL.md，依赖见docs/DEPENDENCIES.md，CI检查与复现见docs/CI.md。
- 运行实例由Docker容器拥有；Lua动作返回/取消保持实例，close独立结束容器。实例关闭与动作锁分别管理，活动Lua期间仍可正常关闭。
- Python角色控制入口统一经过Lua；原生适配器保留底层输入/技能原语，退役的是上层 Python API。GUI 桌面流程按正式支持边界保留。
- Serena保存开发知识；同仓`harness/`独立拥有模型会话、角色设定、目标与经历，作为可选旁路控制端，通过直接CLI/Lua消费客户端能力；镜像继承只为打包复用，LLM与客户端和脚本独立启停，模型退出时已启动脚本继续运行。运行说明见docs/HARNESS.md。客户端库、原生适配器与Lua Runtime保持各自职责。游戏资产、账号与运行数据保留在所属环境。
- 环境与依赖入口：`mem:tech_stack`。最小常用命令：`mem:suggested_commands`。容易误改的源码约束：`mem:conventions`。按影响选择交付验证：`mem:task_completion`。记忆自身维护规则：`mem:memory_maintenance`。
