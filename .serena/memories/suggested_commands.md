# 常用入口

从项目根执行：

```bash
./cli/beidou-pilot --help
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli -v
docker build -t local/beidou-pilot:local .
serena memories check
```

参数、容器启停、外部NX/profile与Lua调用查README.md及docs/CLI.md；共同API和复合策略维护边界见docs/CONTROL.md、shared/scripts/AGENTS.md。子模块准备更新见docs/DEPENDENCIES.md，不在记忆复制完整教程。