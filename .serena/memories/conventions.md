# 易误改约束

- 自维护代码排版与文件组织见[格式规范](../../docs/FORMATTING.md)，统一入口见[tools/format.py](../../tools/format.py)；只处理明确的新自维护白名单，历史编码和第三方例外按规范保留。
- 代码根与运行根不同：--root可指外部Wine运行环境。子进程优先加载cli当前代码，公共策略按代码仓库根shared/scripts读取，不能从运行根导入旧包/脚本。
- cli/test使用包相对导入共享BridgeFiles；子进程测试的PYTHONPATH指cli代码根。不要散放测试或多处sys.path补丁。
- Python只在动作前静态规划，Lua首动作核对原生instance_id/CID/map/scene_generation；旧规划不能被新进程认领。
- 写脚本先查docs/LUA_API.md，常规开发无需逐次读绑定；公共接口变化同步更新该文档，记忆不复制API清单。
- 基础操作属于game API，shared/scripts只保存复合能力；示例在其examples子目录，不自动加载。策略是初步脚手架，按实际行为迭代，详见shared/scripts/AGENTS.md，不冻结旧参数或用兼容层掩盖原生错误。
- 原版V17跳跃绑定为type5/id53，id51是sit；公共jump必须调用跳跃，不能在公共策略里恢复GUI专属补丁绕过原生映射错误。
- 实例启停锁和动作锁职责独立；CLI SIGTERM统一进入取消。放键、未知释放和游戏效果分别确认，详见docs/CONTROL.md。
- 通用编码、授权、外部数据和记忆范围以AGENTS.md为准。
