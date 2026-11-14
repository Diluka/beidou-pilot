-- walk_to 业务合同桩：只提供原生观察/输入边界，不证明真实游戏物理。
-- 地形与初始状态由调用方传入的 case 文件给出，保证策略上下文与桩观察同源。
local scenario, source, case_path = arg[1], arg[2], arg[3]
local case = dofile(case_path)
local now, inputs, logs, jumps, climbs = 0, 0, {}, 0, 0
local control = { owner = "main" }
local floors, walls = {}, {}
local ropes = case.scene.terrain.ropes or {}
for _, foothold in ipairs(case.scene.terrain.footholds) do
    if foothold.x1 == foothold.x2 then
        walls[#walls + 1] = {
            x = foothold.x1,
            top = math.min(foothold.y1, foothold.y2),
            bottom = math.max(foothold.y1, foothold.y2),
        }
    else
        local left, right = math.min(foothold.x1, foothold.x2), math.max(foothold.x1, foothold.x2)
        local y1, y2 = foothold.y1, foothold.y2
        if foothold.x1 > foothold.x2 then
            y1, y2 = y2, y1
        end
        floors[#floors + 1] = { left = left, right = right, y1 = y1, y2 = y2 }
    end
end
local function floor_height(floor, x)
    if floor.right == floor.left then return floor.y1 end
    return floor.y1 + (floor.y2 - floor.y1) * (x - floor.left) / (floor.right - floor.left)
end
local state = {
    ready = true,
    instance_id = case.scene.instance_id,
    scene_generation = case.scene.scene_generation,
    map_id = case.scene.map_id,
    character = case.character or { id = case.scene.character_id, hp = 100, max_hp = 100 },
    position = { x = case.initial.x, y = case.initial.y },
    facing = "Right",
    inventory = case.inventory or {},
    monsters = {},
}
if state.character.id == nil then state.character.id = case.scene.character_id end
local monsters = {}
for index, mob in ipairs(case.monsters or {}) do
    monsters[index] = {
        object_id = mob.object_id or index,
        template_id = mob.template_id or 100,
        x = mob.x,
        y = mob.y,
        hp = mob.hp or 3,
        active = true,
    }
end
state.inventory = case.inventory or {}
local uses, attacks, skills = 0, 0, 0
local function monster_near(x)
    for _, mob in ipairs(monsters) do
        if mob.active and math.abs(mob.x - x) <= 90 then return mob end
    end
    return nil
end
local floor_index = 1
local function floor_at(x)
    for index, floor in ipairs(floors) do
        if x >= floor.left and x <= floor.right then return index end
    end
    return nil
end
for index, floor in ipairs(floors) do
    if state.position.x >= floor.left and state.position.x <= floor.right then
        floor_index = index
        if math.abs(floor_height(floor, state.position.x) - state.position.y) <= 30 then break end
    end
end
local falling = nil

local function ground(index) return floors[index] and floor_height(floors[index], state.position.x) or state.position.y end

local function wall_between(from_x, to_x)
    for _, wall in ipairs(walls) do
        if math.min(from_x, to_x) - 1 < wall.x and wall.x < math.max(from_x, to_x) + 1 then return wall end
    end
    return nil
end

local function advance(seconds)
    now = now + seconds
    if falling then
        local target = floor_height(floors[falling], state.position.x)
        if state.position.y < target then state.position.y = math.min(target, state.position.y + 600 * seconds) end
        if state.position.y >= target then
            state.position.y, floor_index, falling = target, falling, nil
        end
    elseif floors[floor_index] and state.position.y < ground(floor_index) - 1 then
        -- 起点在空中时按重力落地。
        state.position.y = math.min(ground(floor_index), state.position.y + 600 * seconds)
    end
end

local function copy(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for key, item in pairs(value) do
        result[key] = copy(item)
    end
    return result
end

local function rope_near(x)
    for _, rope in ipairs(ropes) do
        if math.abs(x - rope.x) <= 6 then return rope end
    end
    return nil
end

game = {
    time = function() return now end,
    state = function()
        local snapshot = copy(state)
        snapshot.monsters = copy(monsters)
        return snapshot
    end,
    observe = function(domain)
        if domain == "dialog" then return { status = "ok", data = { dialog_open = false } } end
        return { status = "unsupported" }
    end,
    tasks = function() return { tasks = { { name = "main" } }, control = copy(control) } end,
    sleep = function(seconds) advance(seconds) end,
    stop = function()
        if not control.owner then return { reason = "control_not_owned" } end
        control = { from = "main", reason = "stopped" }
        return { reason = "control_released" }
    end,
    move = function(direction, seconds)
        inputs = inputs + 1
        control = { owner = "main", reason = "acquired" }
        if scenario == "map-change" then state.map_id = 2 end
        if scenario == "identity-change" then state.character.id = 2 end
        if direction == "up" or direction == "down" then
            local rope = rope_near(state.position.x)
            if rope then
                climbs = climbs + 1
                local floor = floors[floor_index]
                local delta = (direction == "up" and -1 or 1) * 90 * seconds
                state.position.y =
                    math.max(rope.y1, math.min(floor_height(floor, state.position.x), state.position.y + delta))
                for index, candidate in ipairs(floors) do
                    if math.abs(floor_height(candidate, state.position.x) - state.position.y) <= 2 then
                        floor_index, falling = index, nil
                    end
                end
            end
        else
            if scenario == "mob-clear" or scenario == "clear-limit" then
                local mob = monster_near(state.position.x)
                if mob then
                    advance(seconds)
                    return { reason = "native_action_dispatched" }
                end
            end
            local dx = (direction == "right" and 1 or -1) * 130 * seconds
            local next_x = state.position.x + dx
            local wall = wall_between(state.position.x, next_x)
            if wall then
                state.position.x = wall.x + (dx > 0 and -12 or 12)
            else
                state.position.x = next_x
                local floor = floors[floor_index]
                if floor and (next_x < floor.left or next_x > floor.right) then
                    local target = floor_at(next_x)
                    if target and floor_height(floors[target], next_x) > state.position.y then falling = target end
                end
            end
            if not falling and floors[floor_index] then state.position.y = ground(floor_index) end
        end
        if scenario == "potion-depleted" then state.character.hp = math.max(0, (state.character.hp or 0) - 6) end
        advance(seconds)
        return { reason = "native_action_dispatched" }
    end,
    jump = function()
        jumps = jumps + 1
        control = { owner = "main", reason = "acquired" }
        if scenario == "jumpup" and floor_index == 1 and state.position.x >= 100 and state.position.x <= 300 then
            floor_index = 2
            state.position.y = ground(2)
        elseif scenario == "rope" then
            local rope = rope_near(state.position.x)
            if rope and state.position.y > rope.y2 + 6 then
                state.position.y = math.min(state.position.y, rope.y2 + 12)
            end
        end
        advance(0.05)
        return { reason = "native_action_dispatched" }
    end,
    face = function(direction)
        state.facing = direction
        advance(0.05)
        return { reason = "native_action_dispatched" }
    end,
    attack = function()
        attacks = attacks + 1
        local mob = monster_near(state.position.x)
        if mob then
            mob.hp = mob.hp - 1
            if mob.hp <= 0 then mob.active = false end
        end
        advance(0.3)
        return { reason = "native_action_dispatched" }
    end,
    skill = function()
        skills = skills + 1
        attacks = attacks + 1
        local mob = monster_near(state.position.x)
        if mob then
            mob.hp = mob.hp - 1
            if mob.hp <= 0 then mob.active = false end
        end
        advance(0.3)
        return { reason = "native_action_dispatched" }
    end,
    use_item = function(item_id)
        uses = uses + 1
        for _, item in ipairs(state.inventory) do
            if item.item_id == item_id and (item.quantity or 0) > 0 then
                item.quantity = item.quantity - 1
                break
            end
        end
        state.character.hp = math.min(state.character.max_hp, (state.character.hp or 0) + 40)
        advance(0.2)
        return { reason = "native_action_dispatched" }
    end,
    log = function(message) logs[#logs + 1] = message end,
}

local chunk, load_error = loadfile(source)
assert(chunk, load_error)
local ok, failure = pcall(chunk)
local function fail_text() return tostring(failure) end
local function has(text) return fail_text():find(text, 1, true) ~= nil end
local function count(pattern)
    local total = 0
    for _, message in ipairs(logs) do
        if message:find(pattern, 1, true) then total = total + 1 end
    end
    return total
end

if scenario == "wall" then
    assert(not ok, "wall scenario should not resolve a path")
    assert(has("walk_to_failed") and has("reason=no_viable_path") and has("map=1"), fail_text())
    assert(inputs == 0, "wall scenario must not move")
elseif scenario == "wall-same-side" then
    assert(ok, fail_text())
    assert(math.abs(state.position.x - 150) <= 12, "did not reach target on the same side")
elseif scenario == "walk" then
    assert(ok, fail_text())
    assert(math.abs(state.position.x - 300) <= 12, "did not reach target")
elseif scenario == "jumpup" then
    assert(ok, fail_text())
    assert(floor_index == 2 and math.abs(state.position.x - 200) <= 12, "did not reach upper platform")
elseif scenario == "jump-fail" then
    assert(not ok, "unexecutable jump edge must stop")
    assert(has("no_viable_path"), fail_text())
    assert(count("walk_to_edge_blocked") >= 1, "failed edge was not disabled")
elseif scenario == "drop" then
    assert(ok, fail_text())
    assert(floor_index == 2 and math.abs(state.position.x - 300) <= 12, "did not reach lower platform")
elseif scenario == "rope" then
    assert(ok, fail_text())
    assert(floor_index == 2 and math.abs(state.position.x - 100) <= 18, "did not climb rope")
elseif scenario == "airborne-start" then
    assert(ok, fail_text())
    assert(math.abs(state.position.y - 200) <= 4, "did not settle before planning")
    assert(math.abs(state.position.x - 100) <= 12, "did not reach target")
elseif scenario == "hp-low" then
    assert(not ok, "low hp must stop")
    assert(has("travel_hp_limit"), fail_text())
elseif scenario == "target-off" then
    assert(not ok, "off-platform target must stop")
    assert(has("reason=target_not_on_foothold"), fail_text())
elseif scenario == "plan-only" then
    assert(ok, fail_text())
    assert(inputs == 0, "plan_only must not move")
    assert(count("walk_to_plan") >= 1, "plan_only did not log a plan")
elseif scenario == "hp-heal" then
    assert(ok, fail_text())
    assert(math.abs(state.position.x - 300) <= 12, "did not reach target while healing")
    assert(uses >= 1, "did not use potion during movement")
elseif scenario == "potion-depleted" then
    assert(not ok, "depleted potion must stop")
    assert(fail_text():find("potion_exhausted", 1, true), fail_text())
elseif scenario == "mob-clear" then
    assert(ok, fail_text())
    assert(math.abs(state.position.x - 300) <= 12, "did not reach target after clearing")
    assert(attacks >= 1, "did not attack the blocking monster")
elseif scenario == "clear-limit" then
    assert(not ok, "clear limit must stop")
    assert(fail_text():find("mob_blocked", 1, true), fail_text())
elseif scenario == "map-change" then
    assert(not ok, "map change must stop")
    assert(has("travel_map_changed"), fail_text())
elseif scenario == "identity-change" then
    assert(not ok, "identity change must stop")
    assert(has("travel_identity_changed"), fail_text())
else
    error("unknown scenario " .. tostring(scenario))
end
