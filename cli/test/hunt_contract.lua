-- 真实 hunt 策略的业务合同；这里只提供原生观察/输入边界，不证明游戏物理或命中。
local scenario, strategy = arg[1], arg[2]
local now, killed, routes, parallel, summary = 0, {}, 0, 0, ""
local skill_rejected, air_attacks, climbing = false, 0, false
local crossed_real_edge = false
local attack_lock_until, next_gui_hit, first_gui_attack, gui_progress_time = 0.8, 0.8, nil, 0
local direction_only_turn = false
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
    instance_id = state.instance_id,
    character_id = 1,
    scene_generation = 1,
    map_id = 1,
    seconds = scenario == "stalled" and 6 or 8,
    attack_range = 60,
    min_hp_ratio = 0.35,
    min_x = 0,
    max_x = 400,
    terrain = { footholds = { { id = 1, x1 = 0, x2 = 400, y1 = 200, y2 = 200 } }, ropes = {} },
}
if scenario == "rope" then
    options.terrain.footholds[2] = { id = 2, x1 = 0, x2 = 400, y1 = 0, y2 = 0 }
    options.terrain.footholds[3] = { id = 3, x1 = 0, x2 = 400, y1 = 100, y2 = 100 }
    options.terrain.ropes[1] = { x = 100, y1 = 0, y2 = 198 }
    state.monsters = {
        { object_id = 1, template_id = 100, x = 65, y = 200, active = true },
        { object_id = 2, template_id = 100, x = 140, y = 0, active = true },
    }
elseif scenario == "stalled" or scenario == "context" then
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
    options.seconds = scenario == "gui-lock" and 12 or 23
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
local function advance(seconds)
    now = now + seconds
    if scenario == "fall" then state.position.y = math.min(200, state.position.y + seconds * 100) end
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
    stop = function() advance(0.01) end,
    face = function(direction)
        if not (scenario == "gui-lock" or scenario == "gui-turn-stalled") or now >= attack_lock_until then
            state.facing = direction == "right" and "Right" or "Left"
        end
        advance(0.01)
    end,
    move = function(direction, seconds)
        advance(seconds)
        if scenario == "context" then
            state.scene_generation = 2
            return
        end
        if scenario == "stalled" then return end
        if direction == "up" or direction == "down" then
            assert(scenario == "rope" and math.abs(state.position.x - 100) <= 10, "rope approach was not aligned")
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
        end
    end,
    jump = function() error("unexpected jump in contract scene") end,
    attack = function(seconds, direction, skill_id)
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
                break
            end
        end
        return { dispatched = true, skill_dispatched = skill_id and true or nil }
    end,
    log = function(message)
        if message:find("hunt_route") then routes = routes + 1 end
        if message:find("hunt_summary") then summary = message end
    end,
}
local ok, failure = pcall(dofile, strategy)
if scenario == "stalled" then
    assert(not ok and failure:find("hunt_chase_stalled"), tostring(failure))
    assert(#killed == 0)
elseif scenario == "context" then
    assert(not ok and failure:find("hunt_context_changed"), tostring(failure))
    assert(#killed == 0)
elseif scenario == "gui-turn-stalled" then
    assert(not ok and failure:find("hunt_combat_progress_unconfirmed"), tostring(failure))
    assert(#killed == 0 and parallel == 0, "hunt kept attacking while the native facing never changed")
else
    assert(ok, failure)
    if scenario == "specified" then
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
    else
        assert(#killed == 2 and routes > 0, "hunt did not climb and continue after clearing the first platform")
    end
end
