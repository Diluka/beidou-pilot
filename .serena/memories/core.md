# 项目导航与边界

- `AGENTS.md`是维护约定入口；正式架构/支持边界见docs/ARCHITECTURE.md，命令见docs/CLI.md，写Lua脚本的接口参考见docs/LUA_API.md，桥执行契约见docs/CONTROL.md，依赖见docs/DEPENDENCIES.md。
- 运行实例由Docker容器拥有；Lua动作返回/取消保持实例，close独立结束容器。不能让动作锁挡住活动Lua期间的实例关闭。
- Python角色控制入口统一经过Lua；原生适配器仍保留底层输入/技能原语，不把Python API退役写成底层能力被删除。GUI尚无Lua接口的桌面流程按正式支持边界保留。
- Serena保存开发知识；玩家性格、长期目标/记忆和模型属于后续bot中心。游戏资产、账号与运行数据不进入项目记忆或镜像。
- 环境与依赖入口：`mem:tech_stack`。最小常用命令：`mem:suggested_commands`。容易误改的源码约束：`mem:conventions`。按影响选择交付验证：`mem:task_completion`。记忆自身维护规则：`mem:memory_maintenance`。