-- 真实 hunt 策略的业务合同；这里只提供原生观察/输入边界，不证明游戏物理或命中。
local scenario, strategy = arg[1], arg[2]
local now, killed, routes, parallel, summary = 0, {}, 0, 0, ""
local skill_rejected, air_attacks, climbing = false, 0, false
local crossed_real_edge = false
local attack_lock_until, next_gui_hit, first_gui_attack, gui_progress_time = 0.8, 0.8, nil, 0
local direction_only_turn = false
local open_rope_x, blocked_rope_x = 100, nil
local blocked_visits, blocked_logs, blocked_diagnostic = 0, 0, nil
local blocked_rope_contact, released_after_block, rope_reached_at = false, false, nil
local horizontal_velocity, brake_at, landing_at = 0, nil, nil
local settled_jump, local_spawned, kills_before_climbing = false, false, nil
local resume = scenario:find("^resume") ~= nil
local recovered, resume_moves = false, 0
local state = {
    ready = true,
    instance_id = "hunt-contract",
    scene_generation = 1,
    map_id = 1,
    character = { id = 1, hp = 100, max_hp = 100, level = 3, experience = 0 },
    position = { x = 20, y = 200 },
    facing = "Right",
    inventory = {},
    monsters = {},
}
local function copy(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, item in pairs(value) do
        result[key] = copy(item)
    end
    return result
end
options = {
    budget_seconds = scenario == "stalled" and 6 or 8,
    attack_range = 60,
    min_hp_ratio = 0.35,
    min_x = 0,
    max_x = 400,
    terrain = { footholds = { { id = 1, x1 = 0, x2 = 400, y1 = 200, y2 = 200 } }, ropes = {} },
}
if resume then
    state.position.x, state.position.y, climbing = 100, scenario == "resume-top" and 0 or 90, true
    if scenario == "resume-bottom" then state.position.y = 170 end
    if scenario == "resume-budget" then options.budget_seconds = 0.6 end
    options.terrain.footholds[2] = { id = 2, x1 = 0, x2 = 400, y1 = 0, y2 = 0 }
    options.terrain.ropes[1] = { x = 100, y1 = 0, y2 = 198 }
    state.monsters = { { object_id = 1, template_id = 100, x = 140, y = 0, active = true } }
    if scenario == "resume-bottom" then state.monsters[1].y = 200 end
    if scenario == "resume-no-endpoint" then
        options.min_x, options.max_x = 95, 105
    end
elseif scenario == "rope" then
    options.terrain.footholds[2] = { id = 2, x1 = 0, x2 = 400, y1 = 0, y2 = 0 }
    options.terrain.footholds[3] = { id = 3, x1 = 0, x2 = 400, y1 = 100, y2 = 100 }
    options.terrain.ropes[1] = { x = 100, y1 = 0, y2 = 198 }
    state.monsters = {
        { object_id = 1, template_id = 100, x = 65, y = 200, active = true },
        { object_id = 2, template_id = 100, x = 140, y = 0, active = true },
    }
elseif scenario == "rope-inertia" then
    options.budget_seconds, options.stop_level = 12, 4
    options.terrain.footholds[2] = { id = 2, x1 = 0, x2 = 400, y1 = 0, y2 = 0 }
    options.terrain.ropes[1] = { x = open_rope_x, y1 = 0, y2 = 170 }
    state.monsters = {
        { object_id = 1, template_id = 100, x = 65, y = 200, active = true },
        { object_id = 2, template_id = 100, x = 140, y = 0, active = true },
    }
elseif scenario == "wide-local-spawn" then
    options.budget_seconds, options.stop_level, options.max_x, open_rope_x = 40, 4, 2400, 300
    options.terrain.footholds[1].x2 = 2400
    options.terrain.footholds[2] = { id = 2, x1 = 0, x2 = 2400, y1 = 0, y2 = 0 }
    options.terrain.ropes[1] = { x = open_rope_x, y1 = 0, y2 = 198 }
    state.monsters = {
        { object_id = 1, template_id = 200, x = 2200, y = 200, active = false },
        { object_id = 2, template_id = 100, x = 340, y = 0, active = true },
    }
elseif scenario == "rope-long-approach" or scenario == "rope-blocked" or scenario == "rope-blocked-only" then
    options.budget_seconds, options.stop_level = 26, 4
    if scenario == "rope-long-approach" then
        options.max_x, open_rope_x = 2400, 2100
        options.terrain.footholds[1].x2 = 2400
        options.terrain.ropes[1] = { x = open_rope_x, y1 = 0, y2 = 198 }
    else
        blocked_rope_x = 100
        options.terrain.ropes[1] = { x = blocked_rope_x, y1 = 0, y2 = 198 }
        if scenario == "rope-blocked" then
            open_rope_x = 320
            options.terrain.ropes[2] = { x = open_rope_x, y1 = 0, y2 = 198 }
        else
            open_rope_x = nil
        end
    end
    options.terrain.footholds[2] = { id = 2, x1 = 0, x2 = options.max_x, y1 = 0, y2 = 0 }
    state.monsters = {
        { object_id = 1, template_id = 100, x = 65, y = 200, active = true },
        { object_id = 2, template_id = 100, x = (open_rope_x or blocked_rope_x) + 40, y = 0, active = true },
    }
elseif scenario == "stalled" then
    state.monsters = { { object_id = 1, template_id = 100, x = 300, y = 200, active = true } }
elseif scenario == "fall" then
    options.terrain.footholds[2] = { id = 2, x1 = 180, x2 = 400, y1 = 100, y2 = 100 }
    state.position.x, state.position.y = 160, 50
    state.monsters = { { object_id = 1, template_id = 100, x = 185, y = 100, active = true } }
elseif scenario == "slope" then
    -- Map101040001：连续坡道不能在内部落层，地图夹持也使最左侧看似可落的边缘不可达。
    options.terrain.footholds = {
        { id = 10, prev = 0, next = 11, x1 = 0, x2 = 80, y1 = 0, y2 = 0 },
        { id = 11, prev = 10, next = 12, x1 = 80, x2 = 160, y1 = 0, y2 = 20 },
        { id = 12, prev = 11, next = 0, x1 = 160, x2 = 240, y1 = 20, y2 = 20 },
        { id = 20, prev = 0, next = 0, x1 = -20, x2 = 350, y1 = 100, y2 = 100 },
    }
    options.min_x = -20
    state.position.x, state.position.y = 40, 0
    state.monsters = { { object_id = 1, template_id = 100, x = 280, y = 100, active = true } }
elseif scenario == "gui-lock" or scenario == "gui-turn-stalled" then
    options.budget_seconds = scenario == "gui-lock" and 12 or 23
    state.facing = "Left"
    state.monsters = { { object_id = 1, template_id = 100, x = 70, y = 200, active = true, hp_percent = 100 } }
else
    state.monsters = {
        { object_id = 1, template_id = 100, x = 65, y = 200, active = true },
        { object_id = 2, template_id = 200, x = 110, y = 200, active = true },
        { object_id = 3, template_id = 100, x = 180, y = 200, active = true },
    }
    if scenario == "specified" then options.mob_id = 100 end
    if scenario == "skill" then options.skill_id = 123 end
    if scenario == "narrow" then
        options.min_x, options.max_x = 100, 110
        state.position.x, state.monsters = 105, {}
    end
end
local function advance(seconds, horizontal_input)
    if scenario == "rope-inertia" and not horizontal_input then
        -- 释放横向键后仍有惯性；stop 后经过原生减速时间才停稳。
        local moving = brake_at and math.max(0, math.min(seconds, brake_at - now)) or seconds
        state.position.x = state.position.x + horizontal_velocity * moving
        if brake_at and now + seconds >= brake_at then
            horizontal_velocity, brake_at = 0, nil
        end
    end
    now = now + seconds
    if scenario == "fall" then state.position.y = math.min(200, state.position.y + seconds * 100) end
    if scenario == "rope-inertia" and landing_at and now >= landing_at and not climbing then
        state.position.y, landing_at = 200, nil
    end
    if scenario == "wide-local-spawn" and not local_spawned and now >= 0.1 then
        state.monsters[1].active, local_spawned = true, true
    end
end
local function horizontal(direction, seconds)
    if scenario == "gui-lock" or scenario == "gui-turn-stalled" then
        if now < attack_lock_until or scenario == "gui-turn-stalled" then return end
        local facing = direction == "right" and "Right" or "Left"
        if state.facing ~= facing then
            -- 松开攻击后先在原生更新中转向，剩余窗口仅前进少量；不强行解除动画锁。
            state.facing, direction_only_turn = facing, true
            state.position.x = state.position.x + (direction == "right" and 1 or -1) * 2
            return
        end
    end
    state.facing = direction == "right" and "Right" or "Left"
    state.position.x = state.position.x + (direction == "right" and 1 or -1) * seconds * 150
    if scenario == "rope-inertia" then
        horizontal_velocity, brake_at = (direction == "right" and 1 or -1) * 150, nil
    end
    if scenario == "slope" then state.position.x = math.max(10, math.min(320, state.position.x)) end
    if scenario == "slope" and state.position.y < 50 then
        -- 外部物理边界直接给定这条坡道；不调用策略的分段、连接或落层算法。
        local x = state.position.x
        if x <= 80 then
            state.position.y = 0
        elseif x <= 160 then
            state.position.y = (x - 80) / 4
        elseif x <= 240 then
            state.position.y = 20
        else
            state.position.y, crossed_real_edge = 100, true
        end
    end
end
game = {
    time = function() return now end,
    state = function() return copy(state) end,
    sleep = function(seconds) advance(math.max(seconds, 0.01)) end,
    stop = function()
        if blocked_logs > 0 then released_after_block = true end
        if scenario == "rope-inertia" then brake_at = now + 0.04 end
        advance(0.01)
    end,
    face = function(direction)
        if not (scenario == "gui-lock" or scenario == "gui-turn-stalled") or now >= attack_lock_until then
            state.facing = direction == "right" and "Right" or "Left"
        end
        advance(0.01)
    end,
    move = function(direction, seconds)
        if resume then
            resume_moves = resume_moves + 1
            if scenario == "resume-preempted" then
                assert(resume_moves == 1, "recovery continued after losing control")
                return { reason = "control_preempted" }
            end
            if scenario == "resume-stalled" then
                advance(seconds)
                return
            end
        end
        advance(seconds, direction == "left" or direction == "right")
        if scenario == "stalled" then return end
        if direction == "up" or direction == "down" then
            -- 原生边界：第一根绳梯不响应攀爬，另一根绳梯正常；不读取策略的边或平台图。
            if blocked_rope_x and math.abs(state.position.x - blocked_rope_x) <= 10 then
                if not blocked_rope_contact then blocked_visits = blocked_visits + 1 end
                blocked_rope_contact = true
                return
            end
            if scenario == "rope-inertia" and math.abs(state.position.x - open_rope_x) > 10 then return end
            assert(open_rope_x and math.abs(state.position.x - open_rope_x) <= 10, "rope approach was not aligned")
            if blocked_logs > 0 then assert(released_after_block, "blocked navigation did not release control") end
            rope_reached_at = rope_reached_at or now
            kills_before_climbing = kills_before_climbing or #killed
            horizontal_velocity, brake_at, landing_at = 0, nil, nil
            climbing = true
            state.position.y = state.position.y + (direction == "up" and -1 or 1) * seconds * 100
            -- 客户端采样直接看到绳顶脱离后落回平台，过顶坐标不必可见。
            if state.position.y < -6 then
                state.position.y, climbing = 0, false
            end
            if state.position.y > 198 then
                state.position.y, climbing = 200, false
            end
        else
            if not climbing then horizontal(direction, seconds) end
            if blocked_rope_x and math.abs(state.position.x - blocked_rope_x) > 10 then blocked_rope_contact = false end
        end
    end,
    jump = function()
        assert(scenario == "rope-inertia", "unexpected jump in contract scene")
        advance(0.06)
        settled_jump = settled_jump or horizontal_velocity == 0
        state.position.y, landing_at = 170, now + 0.3
    end,
    attack = function(seconds, direction, skill_id)
        if resume then assert(recovered and not climbing, "hunt attacked before confirming rope recovery") end
        assert(skill_id == options.skill_id, "attack mode silently changed")
        if scenario == "fall" and state.position.y < 200 then air_attacks = air_attacks + 1 end
        advance(seconds)
        if scenario == "gui-lock" or scenario == "gui-turn-stalled" then
            if direction then parallel = parallel + 1 end
            -- GUI攻击动画中不转向也不位移；持续攻击可以在同一位置造成实际进展。
            attack_lock_until = now + 0.8
            first_gui_attack = first_gui_attack or now
            local mob = state.monsters[1]
            if state.facing == "Right" and mob.active and now >= next_gui_hit then
                mob.hp_percent = mob.hp_percent - 20
                next_gui_hit = now + 0.8
                if mob.hp_percent == 0 then
                    mob.active = false
                    killed[#killed + 1] = mob.template_id
                    state.character.experience = state.character.experience + 3
                    gui_progress_time = now - first_gui_attack
                end
            end
            return { dispatched = true }
        end
        if direction then
            parallel = parallel + 1
            horizontal(direction, seconds)
        end
        if skill_id and not skill_rejected then
            skill_rejected = true
            return { dispatched = true, skill_dispatched = false }
        end
        for _, mob in ipairs(state.monsters) do
            if
                mob.active
                and math.abs(mob.y - state.position.y) < 6
                and math.abs(mob.x - state.position.x) <= 60
                and (mob.x >= state.position.x) == (state.facing == "Right")
            then
                mob.active = false
                killed[#killed + 1] = mob.template_id
                state.character.experience = state.character.experience + 3
                if options.stop_level and #killed == 2 then state.character.level = options.stop_level end
                break
            end
        end
        return { dispatched = true, skill_dispatched = skill_id and true or nil }
    end,
    log = function(message)
        if message:find("hunt_rope_recovered") then recovered = true end
        if message:find("hunt_route") then routes = routes + 1 end
        if message:find("hunt_summary") then summary = message end
        if message:find("hunt_navigation_blocked") then
            blocked_logs, blocked_diagnostic = blocked_logs + 1, message
        end
    end,
}
local scene = {
    instance_id = state.instance_id,
    character_id = state.character.id,
    map_id = state.map_id,
    scene_generation = state.scene_generation,
    terrain = { status = "available", footholds = options.terrain.footholds, ropes = options.terrain.ropes },
}
if scenario == "stale-entry" then scene.character_id = scene.character_id + 1 end
local handle = assert(io.open(strategy, "r"))
local source = handle:read("*a")
handle:close()
local prefix = [[
local __beidou_context = ...
local __beidou_state = game.state()
if not (__beidou_state.ready and __beidou_state.instance_id == __beidou_context.scene.instance_id
    and __beidou_state.character and __beidou_state.character.id == __beidou_context.scene.character_id
    and __beidou_state.map_id == __beidou_context.scene.map_id
    and __beidou_state.scene_generation == __beidou_context.scene.scene_generation) then
    error("strategy_scene_context_stale")
end
]]
local chunk = assert(load(prefix .. source .. "\nreturn main(__beidou_context)", "@hunt-contract"))
local ok, failure = pcall(chunk, { options = options, scene = scene })
if scenario == "stale-entry" then
    assert(not ok and failure:find("strategy_scene_context_stale"), tostring(failure))
    assert(#killed == 0 and parallel == 0, "stale context dispatched a hunt action")
elseif scenario == "resume-no-endpoint" then
    assert(not ok and failure:find("hunt_rope_recovery_no_safe_endpoint"), tostring(failure))
    assert(resume_moves == 0 and #killed == 0, "recovery ignored the hunting boundary")
elseif scenario == "resume-stalled" then
    assert(not ok and failure:find("hunt_rope_recovery_stalled"), tostring(failure))
    assert(now < 4 and #killed == 0, "blocked rope recovery was unbounded or attacked")
elseif scenario == "resume-preempted" then
    assert(not ok and failure:find("control_preempted"), tostring(failure))
    assert(resume_moves == 1 and #killed == 0, "recovery dispatched after control was preempted")
elseif scenario == "resume-budget" then
    assert(not ok and failure:find("hunt_rope_recovery_budget"), tostring(failure))
    assert(now < 0.7 and #killed == 0, "rope recovery ignored the total hunting budget")
elseif scenario == "stalled" then
    assert(not ok and failure:find("hunt_chase_stalled"), tostring(failure))
    assert(#killed == 0)
elseif scenario == "gui-turn-stalled" then
    assert(not ok and failure:find("hunt_combat_progress_unconfirmed"), tostring(failure))
    assert(#killed == 0 and parallel == 0, "hunt kept attacking while the native facing never changed")
elseif scenario == "rope-blocked-only" then
    assert(not ok and failure:find("hunt_targets_unreachable"), tostring(failure))
    assert(#killed == 1 and blocked_visits == 1 and released_after_block, "unreachable hunt retried the blocked route")
else
    assert(ok, failure)
    if resume then
        assert(recovered and #killed == 1, "hunt did not recover from the rope and obtain combat progress")
    elseif scenario == "specified" then
        assert(#killed == 2 and state.monsters[2].active, "specified hunt attacked another monster type")
    elseif scenario == "all" then
        assert(#killed == 3 and parallel > 0, "all hunt did not move and attack while continuing to next targets")
    elseif scenario == "skill" then
        assert(
            #killed == 3 and parallel > 0 and summary:find("rejected=1"),
            "skill rejection was counted as a successful skill"
        )
    elseif scenario == "narrow" then
        assert(state.position.x >= options.min_x and state.position.x <= options.max_x, "patrol moved outside the area")
    elseif scenario == "fall" then
        assert(#killed == 1 and air_attacks > 0, "falling hunt incorrectly waited for landing before attacking")
    elseif scenario == "slope" then
        assert(#killed == 1 and crossed_real_edge, "hunt mistook an internal slope seam for a drop edge")
    elseif scenario == "gui-lock" then
        assert(
            #killed == 1 and direction_only_turn and parallel > 0 and gui_progress_time > 3,
            "hunt did not release Attack to turn or rejected native movement lock despite combat progress"
        )
    elseif scenario == "rope-long-approach" then
        assert(#killed == 2 and rope_reached_at > 12, "hunt stopped a progressing approach before reaching the rope")
    elseif scenario == "rope-blocked" then
        assert(#killed == 2 and blocked_visits == 1, "hunt did not use the available rope after a blocked route")
    elseif scenario == "rope-inertia" then
        assert(#killed == 2 and settled_jump, "hunt did not stop horizontal inertia before jumping to the rope")
    elseif scenario == "wide-local-spawn" then
        assert(
            #killed == 2 and killed[1] == 200 and killed[2] == 100 and kills_before_climbing == 1,
            "hunt did not clear the new same-platform target before continuing to another platform"
        )
    else
        assert(#killed == 2 and routes > 0, "hunt did not climb and continue after clearing the first platform")
    end
end
if blocked_rope_x then
    assert(blocked_logs == 1, "blocked route was not diagnosed exactly once")
    for _, field in ipairs({ "kind=rope", "from=", "to=", "stage=", "x=", "y=", "goal" }) do
        assert(blocked_diagnostic:find(field, 1, true), "blocked route diagnostic missed " .. field)
    end
end
