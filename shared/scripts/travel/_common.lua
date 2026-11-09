-- 移动、爬绳和门户共用的原生状态边界及同层对齐。
local function travel_initial()
    local s = game.state()
    assert(s.ready, "travel_observation_unavailable")
    assert(s.instance_id == options.instance_id and s.character.id == options.character_id, "travel_identity_changed")
    assert(s.map_id == options.map_id and s.scene_generation == options.scene_generation, "travel_map_changed")
    assert(s.character.hp > 0 and s.character.hp / s.character.max_hp >= options.min_hp_ratio, "travel_hp_limit")
    return s
end

local function travel_state(initial, min_hp_ratio, deadline, allow_transition)
    local s = game.state()
    assert(s.instance_id == initial.instance_id, "travel_identity_changed")
    while allow_transition and not s.ready and game.time() < deadline do
        game.sleep(0.05)
        s = game.state()
        assert(s.instance_id == initial.instance_id, "travel_identity_changed")
    end
    assert(s.ready, "travel_observation_unavailable")
    assert(s.character.id == initial.character.id, "travel_identity_changed")
    if not allow_transition then
        assert(s.map_id == initial.map_id and s.scene_generation == initial.scene_generation, "travel_map_changed")
    end
    assert(s.character.hp > 0 and s.character.hp / s.character.max_hp >= min_hp_ratio, "travel_hp_limit")
    return s
end

local function align_to_x(initial, x, tolerance, y_tolerance, deadline, min_hp_ratio, transitioned)
    local state = initial
    local steps = 0
    local stalled = 0
    local speed = 125
    while game.time() < deadline do
        state = travel_state(initial, min_hp_ratio, deadline, transitioned ~= nil)
        if transitioned and transitioned(state) then return state, steps, true end
        assert(state.map_id == initial.map_id and state.scene_generation == initial.scene_generation, "travel_map_changed")
        assert(math.abs(state.position.y - initial.position.y) <= y_tolerance, "travel_layer_changed")
        local distance = x - state.position.x
        if math.abs(distance) <= tolerance then
            game.stop()
            game.sleep(0.15)
            local settled = travel_state(initial, min_hp_ratio, deadline, transitioned ~= nil)
            if transitioned and transitioned(settled) then return settled, steps, true end
            assert(settled.map_id == initial.map_id and settled.scene_generation == initial.scene_generation, "travel_map_changed")
            assert(math.abs(settled.position.y - initial.position.y) <= y_tolerance, "travel_layer_changed")
            if math.abs(settled.position.x - x) <= tolerance then return settled, steps, false end
            state = settled
        else
            local duration = math.max(0.05, math.min(0.8, math.abs(distance) / speed * 0.8))
            if game.time() + duration + 0.12 >= deadline then break end
            game.move(distance > 0 and "right" or "left", duration)
            game.sleep(0.12)
            local after = travel_state(initial, min_hp_ratio, deadline, transitioned ~= nil)
            if transitioned and transitioned(after) then return after, steps + 1, true end
            assert(after.map_id == initial.map_id and after.scene_generation == initial.scene_generation, "travel_map_changed")
            assert(math.abs(after.position.y - initial.position.y) <= y_tolerance, "travel_layer_changed")
            steps = steps + 1
            local progress = math.abs(state.position.x - x) - math.abs(after.position.x - x)
            stalled = progress <= 1 and stalled + 1 or 0
            assert(stalled < 3, "travel_no_progress")
            local moved = math.abs(after.position.x - state.position.x)
            if moved > 1 then speed = math.max(40, math.min(300, moved / duration)) end
            state = after
        end
    end
    error("travel_budget_exhausted")
end
