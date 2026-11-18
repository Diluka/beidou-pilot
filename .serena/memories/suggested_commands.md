# 常用入口

从项目根执行；用已准备的角色目录名替换 NAME：

```bash
workbenches/workbench --help
workbenches/workbench list dev
workbenches/workbench server dev status
workbenches/workbench dev/NAME notes
workbenches/workbench dev/NAME build
workbenches/workbench dev/NAME resources-check
workbenches/workbench dev/NAME status
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli -v
serena memories check
```

工作台结构、分区配置和开发服 CLI 查 workbenches/README.md。dev/NAME 读取开发角色状态；live/NAME 读取已授权养成计划。resources-check 固定用 headless 镜像离线检查。

整个目录挂 /work，用户 Lua 位于 /work/scripts。构建、工件、启停和运行版本查 README.md、docs/CLI.md；共同 API 和策略边界查 docs/CONTROL.md、shared/scripts/AGENTS.md。子模块和 CI 查 docs/DEPENDENCIES.md、docs/CI.md；记忆只保存入口，完整教程与本机私密配置保留在原处。
