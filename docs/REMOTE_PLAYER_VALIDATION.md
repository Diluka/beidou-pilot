# 远端角色离场与重入观察

> 历史研究记录（2026-11-27）：原生 headless 客户端已退役，本文的双端观测与基线只作历史参考；当前客户端只有原版 GUI 后端。

历史场景：当时用两个独立开发角色验证 headless `game.scene.players`，记录同图移动、门户离场、重新入场并再次移动。准备和原始事件留在各自的开发工作台；账号及运行数据不提交。

## 准备

1. 历史步骤：启动独立开发服，选择两个不同的开发角色，当时观察端使用 headless，移动端可使用原版 GUI。分别核对 `status`、`script status` 和 `snapshot`，确认实例身份、频道、就绪状态与控制权。处理移动端打开的提示对话。
2. 两个角色进入同图安全位置。选取可往返门户，用 `world-map route` 查询两方向的门户坐标；确认返回入口与第一次移动轨迹可区分。路线只是静态资料，实际跨图须以客户端快照核对。
3. 在观察角色的 `scripts/remote-player-observe.lua` 保存下列脚本，将 `target_id` 改为移动角色的实际角色 ID。每次采样重新读取当前领域；`readable=false` 或 `complete` 不为 `true` 时不能把零条目解释为角色消失。

```lua
-- @tick.gear 1
local target_id = 3
local function main(context)
    local scene = context.game.scene
    local state = context.state
    if not state.last or context.tick.time - state.last >= 0.25 then
        state.last = context.tick.time
        local count, positions = 0, {}
        if scene.players then
            for _, player in ipairs(scene.players) do
                if player.character_id == target_id then
                    count = count + 1
                    positions[#positions + 1] = tostring(player.x) .. ',' .. tostring(player.y)
                end
            end
        end
        context.game.log(('remote-player t=%.3f map=%s status=%s complete=%s readable=%s count=%d positions=%s'):format(
            context.tick.time, tostring(context.game.world.map_id), tostring(scene.status),
            tostring(scene.players_complete), tostring(scene.players ~= nil), count,
            table.concat(positions, ';')))
    end
end
```

移动端的简单移动脚本可保存为 `scripts/remote-player-move.lua`，根据落点、平台边缘与安全范围调整方向和时长，再运行 `script run remote-player-move.lua --seconds 5`：

```lua
local function main(context)
    local state = context.state
    state.start = state.start or context.tick.time
    if context.tick.time - state.start < 1 then
        context.game.player.move("left")
    else
        context.game.player.stop()
        return "done"
    end
end
```

以下有界脚本仅适用于已确认角色与门户处于同一可通行平台、横向路线安全且可从该位置进入的场景。按实际地图和门户坐标调整 `source_map` 和 `portal_x`；其他地形由操作者选择合适的有界操作。返回门户可另存一份并调整参数。

```lua
local source_map, portal_x = 101040000, -1002
local function main(context)
    if context.game.world.map_id ~= source_map then return "done" end
    local x = context.game.character.x
    if x > portal_x + 10 then context.game.player.move("left")
    elseif x < portal_x - 10 then context.game.player.move("right")
    else context.game.player.move("up") end
end
```

使用 `script run PORTAL_SCRIPT --seconds 8` 限时；若未跨图，先核对脚本终态、对话及实际位置再决定下一步。

## 执行与判断

1. 在观察端运行 `script start remote-player-observe.lua --seconds 120`，记下 `script_id`、实例和运行身份。观察可读列表中的目标数量和位置。移动端用其工作台的有界 tick Lua 执行普通移动，结束后核对终态、`control_released` 和实际位置。采样应显示唯一目标及位置变化。
2. 移动端接近选定门户并提交 `player.move("up")`，跨图后停止输入；以新鲜快照确认地图改变。用观察端状态及采样核对其留在原图且保持就绪；采样中可读且完整的列表应不再包含目标。
3. 移动端通过返回门户重入原图，先静止并用快照记录实际入场点，再做一次新的有界移动。观察端应只出现一个目标，位置先与本次入场相符，再随新移动变化。必要时在采样时限到达后确认终态，重新启动观察并记录新 `script_id`，再执行移动；不要把未采到的时间段当作证据。
4. 对照各阶段的可读性、数量和位置，记录首次异常阶段及样本。原始事件位于所属实例桥目录的 `script-events.jsonl`（[路径说明](LUA_TICK_API.md#运动校准脚本与离线比较器)）；按实例、run ID、script ID 与事件时间筛选，记录客户端版本、角色身份、地图、门户和采样范围。结束时按会话 ID 取消仍运行的脚本并确认终态和放键；危险区域应回到安全位置或关闭所属客户端。

## 已验证样本

2026-11-18，开发服 v1.12，客户端提交 `c202cdeb7bec436ebc4963504cb37c89617c63c8`：headless 观察端与 GUI 移动端在地图 `101040000`、频道 1 同图。观察到唯一目标从约 `(-757,1468)` 移至 `(-884,1451)`；移动端通过 `west00` 到 `102000000` 后，原图完整可读列表中目标为零。经 `east00` 返回后，观察端看到唯一目标出现在 `(-1002,1411)` 附近并落至 `(-1002,1451)`；移动端快照确认落点约 `(-1002,1451)`。重入后补采的一次移动中，观察位置从 `(-1133,1442)` 变到 `(-1326,2025)`。这次左移导致角色落到下层，重跑时应按现场选择安全方向。这些采样未发现重复或旧轨迹重放，不代表未采样间隙不存在异常。返回时 GUI 弹出 NPC 提示，结束对话后门户可用。两端最终确认放键并关闭。

原始事件保留在开发工作台 `dev/movement-probe` 的运行 `20261118T091826.675614501Z` 桥事件日志中；观察实例 ID 为 `7-1794993520732-289521935`。脚本 `34664cc0f2d043928b224eb0220db6c0` 的采样范围为 t=289736.035–289855.738，其中离场前末次位置样本为 t=289763.642，首次零条目为 t=289763.937，重入首次条目为 t=289853.042；重入后移动由另一个脚本 `7a3ef7ed0ad341fb85545aed39947105` 在 t=289885.947–289894.353 补采。两段之间有空窗，不构成连续轨迹。移动端运行 ID 为 `20261118T092002.264637255Z`；门户跨图及重入另以该端脚本终态与快照核对。
