# 跨客户端观察采样

`observe_clients.py` 在同一 host 时钟下同时读取两个客户端实例的桥状态，用于核对「一个客户端里自己看自己」与「另一个客户端看到的它」是否一致。工具只读桥状态文件（`runtime/.../bridge/state.json`），不发送输入、不写角色数据；需要两个工作台实例都处于运行状态。

## 用法

```bash
# 在任意检出内执行；工作台选择支持 live/NAME、dev/NAME 或绝对路径
python3 tools/observer/observe_clients.py \
  live/workspace-adventurer-bow live/workspace-adventurer-assassin \
  --seconds 20 --interval 0.03 \
  --output /tmp/observer.jsonl --summary /tmp/observer-summary.json
```

- 输出 JSONL：每个采样点记录两侧自身的 `self_view`（x/y/vx/vy/on_ground）与对另一侧角色的 `view_of_*`（x/y/vx/vy/facing），以及 `observed_at_ms`、`map_id`。
- 结束时输出摘要 JSON：`first_to_second` 与 `second_to_first` 两个方向各自的入图位置差（initial/final/max offset）、观察端单帧最大位移（max_observer_jump_px）、自身最大速度、停止后观察端 velocity 仍非零的样本数。
- 客户端重开（run 目录变化）会被自动重新解析；路径失效时写入 warnings。

## 判读

- **入图位置差**：停留不动时观察端与本地位置的偏移，期望 ≤2px；headless 当前基线见下。
- **单帧最大位移**：观察端相邻采样点的位移，移动中不应出现 >10px 的跳变（换算采样间隔后）。
- **停止后残留**：自身静止（速度 <1px/s）但观察端 `vx` 仍非零的样本数，期望停止后 1s 内归零。
- **最终位置差**：停止后两端位置应一致。

采样间隔内观察到的跳变包含客户端自身的插值行为，因此判读时结合采样间隔与角色实际速度；多采样点持续出现的偏移才是同步问题。

## 当前基线（2026-11-25，live 服，地图 10000）

原始 JSONL 保留在调查环境（`tmp/follow-recording/`），结论见 issue：

- 入图位置差 60px（headless 本地贴地 vs 服务端进入场地广播 y-42），首次移动时观察端出现 409→451→469 的位置跳变：见 #371。
- headless 移动后停止，GUI 观察端保留约 -123px/s 的残留速度、位置尾巴 1.35–2.29s、最终位置差 6–9px：见 #371。
- headless 观察远端玩家时速度按 8ms 间隔计算，数值放大约 3.75 倍：见 #379。
- headless 移动包第一个上下文字节恒为 0，服务端启用 fieldKey 校验后会被静默丢弃：见 #372。
