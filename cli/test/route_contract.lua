-- 原生边界替身：只验证真实路线 Lua 的观察、停止和复用合同。
local scenario, source = arg[1], arg[2]
local now, inputs, portals, arrived = 0, 0, 0, 0
local control = { owner = "main" }
local pending, pending_at, town_fall_at
local state = {
    ready = true,
    instance_id = "route-contract",
    scene_generation = 1,
    map_id = 50000,
    character = { id = 1, hp = 100, max_hp = 100 },
    position = { x = 1200, y = -85 },
}
if scenario == "wrong-start" then state.position = { x = 300, y = 335 } end
local function copy(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, item in pairs(value) do
        result[key] = copy(item)
    end
    return result
end
local function advance(seconds)
    now = now + seconds
    if pending and now >= pending_at then
        state.map_id = pending
        state.position = pending == 1000000 and { x = -66, y = 274 } or { x = 1420, y = 275 }
        state.scene_generation, state.ready, pending = state.scene_generation + 1, true, nil
        if state.map_id == 1000000 then
            if scenario == "landing" then
                state.position.y, town_fall_at = 269, now + 0.1
            end
            if scenario == "destination" then state.position.x = 1000 end
        end
    end
    if town_fall_at and now >= town_fall_at then
        state.position.y, town_fall_at = 274, nil
    end
    if state.map_id == 50000 and state.position.x > 1389 and state.position.y < 275 then
        state.position.y = math.min(275, state.position.y + seconds * 500)
    end
end
game = {
    time = function() return now end,
    state = function() return copy(state) end,
    tasks = function() return { tasks = { { name = "main" } }, control = copy(control) } end,
    sleep = function(seconds)
        advance(seconds)
        if scenario == "final-preempted" and state.map_id == 1000000 and seconds >= 0.2 then
            -- 另一控制者在终点复采等待内已经完成，owner为空也不能报告旧路线成功。
            control = { from = "other", reason = "task_completed" }
        end
    end,
    stop = function()
        advance(0.01)
        if not control.owner then return { reason = "control_not_owned" } end
        assert(control.owner == "main", "route tried to release another owner's input")
        control = { from = "main", reason = "stopped" }
        return { reason = "control_released" }
    end,
    move = function(direction, seconds)
        inputs = inputs + 1
        assert(not control.owner or control.owner == "main", "route dispatched after losing control")
        control = { owner = "main", reason = "acquired" }
        if scenario == "preempted" then
            control.owner = "other"
            return { reason = "control_preempted" }
        end
        if scenario == "scene" then state.scene_generation = 2 end
        if scenario == "identity" then state.character.id = 2 end
        if scenario == "unknown-hp" then state.character.max_hp = nil end
        if direction == "left" or direction == "right" then
            state.position.x = state.position.x + (direction == "right" and 1 or -1) * seconds * 125
            if scenario == "stalled" then state.position.x = math.min(1380, state.position.x) end
        else
            assert(direction == "up")
            portals = portals + 1
            if state.map_id == 50000 then
                assert(
                    math.abs(state.position.x - 1420) <= 5 and math.abs(state.position.y - 275) <= 5,
                    "route entered the portal before reaching its platform"
                )
                pending = scenario == "unexpected-portal" and 40000 or 1000000
            else
                assert(state.map_id == 1000000 and math.abs(state.position.x + 66) <= 5)
                pending = 50000
            end
            pending_at, state.ready = now + 0.1, false
        end
        advance(seconds)
        return { reason = "native_action_dispatched" }
    end,
    log = function(message)
        if message:find("route_result") then arrived = arrived + 1 end
    end,
}
local ok, failure = pcall(dofile, source)
if scenario == "normal" or scenario == "landing" then
    assert(ok, failure)
    assert(arrived == 2 and portals == 2 and state.map_id == 50000, "route was not reusable for the return journey")
else
    assert(not ok and failure:find("arrived=false"), tostring(failure))
    assert(arrived == 0, "failed route reported arrival")
    if scenario == "wrong-start" then
        assert(inputs == 0 and failure:find("stage=start") and failure:find("inapplicable_start"), failure)
    elseif scenario == "stalled" then
        assert(portals == 0 and now < 10 and failure:find("stage=east%-portal%-platform"), failure)
    elseif scenario == "unexpected-portal" then
        assert(portals == 1 and failure:find("unexpected_transition"), failure)
    elseif scenario == "destination" then
        assert(portals == 1 and now < 10 and failure:find("destination_unconfirmed"), failure)
    elseif scenario == "preempted" then
        assert(inputs == 1 and failure:find("control_preempted"), failure)
    elseif scenario == "final-preempted" then
        assert(portals == 1 and failure:find("control_preempted"), failure)
    elseif scenario == "budget" then
        assert(now < 1.2 and portals == 0 and failure:find("budget"), failure)
    elseif scenario == "missing-terrain" then
        assert(inputs == 0 and failure:find("unknown_drop_target"), failure)
    else
        assert(inputs == 1 and portals == 0, "route continued after identity or scene changed")
    end
end
