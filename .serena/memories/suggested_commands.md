# 常用入口

从项目根执行；/external/workbench 是占位目录：

```bash
private/workbenches/workbench --help
private/workbenches/workbench --list
private/workbenches/workbench /external/workbench notes
private/workbenches/workbench /external/workbench build
private/workbenches/workbench /external/workbench resources-check
private/workbenches/workbench /external/workbench status
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli -v
serena memories check
```

工作目录保存 account.json 和可选 workbench.json（普通 GUI 示例仅 backend=beidou），共享资源路径只在主检出目录的 private/workbenches/resources.json。服务器默认固定，调试与实际游戏验收也复用常驻服和授权已有账号角色，仅场景必须时新建账号或角色；特殊情况确需隔离服时记录原因，隔离对象在 workbench.json.server；配置不经宿主命令行覆盖。resources-check 固定使用 headless 镜像离线检查，与账号、服务器和现存实例无关。

整个目录挂 /work，用户 Lua 位于 /work/scripts。构建、工件、启停和运行版本查 README.md、docs/CLI.md；共同 API 和策略边界查 docs/CONTROL.md、shared/scripts/AGENTS.md。子模块和 CI 查 docs/DEPENDENCIES.md、docs/CI.md；记忆只保存入口，完整教程与本机私密配置保留在原处。
