-- 真实 hunt 策略的业务合同；这里只提供原生观察/输入边界，不证明游戏物理或命中。
local scenario, strategy = arg[1], arg[2]
local now, killed, routes, parallel, summary = 0, {}, 0, 0, ""
local skill_rejected, air_attacks, climbing = false, 0, false
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
game = {
    time = function() return now end,
    state = function() return copy(state) end,
    sleep = function(seconds) advance(math.max(seconds, 0.01)) end,
    stop = function() advance(0.01) end,
    face = function(direction)
        state.facing = direction == "right" and "Right" or "Left"
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
            if not climbing then
                state.position.x = state.position.x + (direction == "right" and 1 or -1) * seconds * 150
            end
        end
    end,
    jump = function() error("unexpected jump in contract scene") end,
    attack = function(seconds, direction, skill_id)
        assert(skill_id == options.skill_id, "attack mode silently changed")
        if scenario == "fall" and state.position.y < 200 then air_attacks = air_attacks + 1 end
        advance(seconds)
        if direction then
            parallel = parallel + 1
            state.position.x = state.position.x + (direction == "right" and 1 or -1) * seconds * 150
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
    else
        assert(#killed == 2 and routes > 0, "hunt did not climb and continue after clearing the first platform")
    end
end
