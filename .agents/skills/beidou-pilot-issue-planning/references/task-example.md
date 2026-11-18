# [Headless CLI] 死亡后可请求一次普通复活

来源：[双端客户端复活需求 #296](https://github.com/Diluka/beidou-pilot/issues/296)。以下仅示范其中一个入口的任务写法。

## 目标

在 headless 客户端中，操作者发现当前角色意外死亡后，可以显式请求一次普通复活，并知道同一角色是否已经恢复。本单只覆盖 headless CLI；GUI 和 Lua 的入口另行验收。

调用方只执行一次命令，从 JSON 读取结果；下面的 `jq` 只投影验收关心的字段：

```sh
beidou-pilot --json revive | jq '{ok, status: .data.status, changed: .data.changed}'
# 确认从死亡恢复时，预期：{"ok":true,"status":"revived","changed":true}
```

## 验收标准

- [ ] 对已确认死亡的角色执行一次命令，只请求一次普通复活。客户端观察到同一角色 HP 从 0 恢复为正值，且地图和位置有效后，命令才报告成功。
- [ ] 对已存活的角色执行同一命令，报告已存活且不发送请求；已发送但未观察到恢复时，报告未确认，不自动重试。
- [ ] 用定向测试核对上述分支的请求次数；在开发服用允许死亡的角色，从真实 headless CLI 执行示例，记录客户端版本以及复活前后的角色身份、HP、地图和位置。
