# 常用入口

从项目根执行；/external/workbench 是示例占位路径：

```bash
./beidou-pilot --help
./beidou-pilot --workbench /external/workbench --backend headless --json build
./beidou-pilot --workbench /external/workbench --backend headless --json resources-check
./beidou-pilot --workbench /external/workbench --json status
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=cli python3 -m unittest discover -s cli/test -t cli -v
serena memories check
```

工作台使用成对的 account.json/server.json，启动参数为 --account/--server；数据整体挂到 /work，角色 Lua 用 /work/scripts 路径。构建、工件获取、容器启停、外部资源与 Lua 调用查 README.md 和 docs/CLI.md；resources-check 只离线检查 NX，不需要服务器或账号配置。GUI 默认获取对应提交的成功 CI 工件，开发时可显式指定匹配的桥工件目录。

共同 API 和策略维护边界见 docs/CONTROL.md、shared/scripts/AGENTS.md。子模块准备更新见 docs/DEPENDENCIES.md，CI 与实际客户端验收见 docs/CI.md；记忆不复制完整教程或本机私密配置。
