-- 移动、爬绳、门户和已知路线共用的原生状态边界及同层对齐。
local function travel_check(condition, reason, fail)
    if not condition then
        if fail then
            fail(reason)
        else
            error(reason)
        end
    end
end
local function travel_action(result, fail)
    if result then travel_check(result.reason ~= "control_preempted", result.reason, fail) end
    return result
end
local function travel_initial(context, min_hp_ratio, fail)
    local s = game.state()
    local scene = context.scene
    travel_check(s.ready and s.character and s.position, "travel_observation_unavailable", fail)
    travel_check(
        s.instance_id == scene.instance_id and s.character.id == scene.character_id,
        "travel_identity_changed",
        fail
    )
    travel_check(s.map_id == scene.map_id and s.scene_generation == scene.scene_generation, "travel_map_changed", fail)
    travel_check(
        s.character.hp and s.character.max_hp and s.character.max_hp > 0,
        "travel_observation_unavailable",
        fail
    )
    travel_check(s.character.hp > 0 and s.character.hp / s.character.max_hp >= min_hp_ratio, "travel_hp_limit", fail)
    return s
end

local function travel_state(initial, min_hp_ratio, deadline, allow_transition, fail)
    local s = game.state()
    travel_check(s.instance_id == initial.instance_id, "travel_identity_changed", fail)
    while allow_transition and not s.ready and game.time() < deadline do
        game.sleep(0.05)
        s = game.state()
        travel_check(s.instance_id == initial.instance_id, "travel_identity_changed", fail)
    end
    travel_check(s.ready and s.character and s.position, "travel_observation_unavailable", fail)
    travel_check(s.character.id == initial.character.id, "travel_identity_changed", fail)
    if not allow_transition then
        travel_check(
            s.map_id == initial.map_id and s.scene_generation == initial.scene_generation,
            "travel_map_changed",
            fail
        )
    end
    travel_check(
        s.character.hp and s.character.max_hp and s.character.max_hp > 0,
        "travel_observation_unavailable",
        fail
    )
    travel_check(s.character.hp > 0 and s.character.hp / s.character.max_hp >= min_hp_ratio, "travel_hp_limit", fail)
    return s
end

local function align_to_x(initial, x, tolerance, y_tolerance, deadline, min_hp_ratio, transitioned, fail)
    local state = initial
    local steps = 0
    local stalled = 0
    local speed = 125
    while game.time() < deadline do
        state = travel_state(initial, min_hp_ratio, deadline, transitioned ~= nil, fail)
        if transitioned and transitioned(state) then return state, steps, true end
        travel_check(
            state.map_id == initial.map_id and state.scene_generation == initial.scene_generation,
            "travel_map_changed",
            fail
        )
        travel_check(math.abs(state.position.y - initial.position.y) <= y_tolerance, "travel_layer_changed", fail)
        local distance = x - state.position.x
        if math.abs(distance) <= tolerance then
            travel_action(game.stop(), fail)
            game.sleep(0.15)
            local settled = travel_state(initial, min_hp_ratio, deadline, transitioned ~= nil, fail)
            if transitioned and transitioned(settled) then return settled, steps, true end
            travel_check(
                settled.map_id == initial.map_id and settled.scene_generation == initial.scene_generation,
                "travel_map_changed",
                fail
            )
            travel_check(math.abs(settled.position.y - initial.position.y) <= y_tolerance, "travel_layer_changed", fail)
            if math.abs(settled.position.x - x) <= tolerance then return settled, steps, false end
            state = settled
        else
            local duration = math.max(0.05, math.min(0.8, math.abs(distance) / speed * 0.8))
            if game.time() + duration + 0.12 >= deadline then break end
            travel_action(game.move(distance > 0 and "right" or "left", duration), fail)
            game.sleep(0.12)
            local after = travel_state(initial, min_hp_ratio, deadline, transitioned ~= nil, fail)
            if transitioned and transitioned(after) then return after, steps + 1, true end
            travel_check(
                after.map_id == initial.map_id and after.scene_generation == initial.scene_generation,
                "travel_map_changed",
                fail
            )
            travel_check(math.abs(after.position.y - initial.position.y) <= y_tolerance, "travel_layer_changed", fail)
            steps = steps + 1
            local progress = math.abs(state.position.x - x) - math.abs(after.position.x - x)
            stalled = progress <= 1 and stalled + 1 or 0
            travel_check(stalled < 3, "travel_no_progress", fail)
            local moved = math.abs(after.position.x - state.position.x)
            if moved > 1 then speed = math.max(40, math.min(300, moved / duration)) end
            state = after
        end
    end
    travel_check(false, "travel_budget_exhausted", fail)
end
