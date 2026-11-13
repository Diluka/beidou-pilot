-- navigate 业务合同桩：模拟按上换图与每张地图的地面，只验证真实策略的段序列与失败语义。
-- 地形与路线由调用方传入的 case 文件给出，保证策略上下文与桩观察同源。
local scenario, source, case_path = arg[1], arg[2], arg[3]
local case = dofile(case_path)
local now, inputs, logs, transitions = 0, 0, {}, 0
local control = { owner = "main" }
local state = {
    ready = true,
    instance_id = case.scene.instance_id,
    scene_generation = 1,
    map_id = case.scene.map_id,
    character = { id = case.scene.character_id, hp = case.hp or 100, max_hp = case.max_hp or 100 },
    position = { x = case.start.x, y = case.start.y },
    facing = "Right",
    inventory = {},
    monsters = {},
}
local pending = nil

-- 每张地图的地面高度：取水平 foothold（x1 ~= x2 且 y1 == y2）的覆盖段。
local floors = {}
for _, leg in ipairs(case.route.legs) do
    local rows = {}
    for _, row in ipairs(leg.terrain.footholds) do
        if row[2] ~= row[3] and row[4] == row[5] then
            rows[#rows + 1] = { left = math.min(row[2], row[3]), right = math.max(row[2], row[3]), y = row[4] }
        end
    end
    floors[leg.map_id] = rows
end
if case.route.final then
    local rows = {}
    for _, row in ipairs(case.route.final.terrain.footholds) do
        if row[2] ~= row[3] and row[4] == row[5] then
            rows[#rows + 1] = { left = math.min(row[2], row[3]), right = math.max(row[2], row[3]), y = row[4] }
        end
    end
    floors[case.route.final.map_id] = rows
end

local function floor_height(map_id, x)
    for _, row in ipairs(floors[map_id] or {}) do
        if x >= row.left and x <= row.right then return row.y end
    end
    return nil
end

local function advance(seconds)
    now = now + seconds
    if pending and now >= pending.at then
        state.map_id, state.position = pending.map_id, { x = pending.x, y = pending.y }
        pending = nil
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

game = {
    time = function() return now end,
    state = function() return copy(state) end,
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
        if direction == "up" then
            transitions = transitions + 1
            if scenario == "portal-unconfirmed" then
                advance(seconds)
                return { reason = "native_action_dispatched" }
            end
            local target = case.arrivals[tostring(state.map_id)]
            if not target then error("contract: missing arrival for map " .. tostring(state.map_id)) end
            local target_map = target.map_id
            if scenario == "map-mismatch" and transitions == 2 then target_map = target.map_id + 1 end
            pending = { map_id = target_map, x = target.x, y = target.y, at = now + 0.2 }
            advance(seconds)
            return { reason = "native_action_dispatched" }
        end
        if direction == "left" or direction == "right" then
            local next_x = state.position.x + (direction == "right" and 1 or -1) * 130 * seconds
            local height = floor_height(state.map_id, next_x)
            if height then
                state.position = { x = next_x, y = height }
            else
                local edge = floor_height(state.map_id, state.position.x)
                state.position = { x = next_x, y = edge or state.position.y }
            end
        end
        advance(seconds)
        return { reason = "native_action_dispatched" }
    end,
    jump = function()
        inputs = inputs + 1
        advance(0.05)
        return { reason = "native_action_dispatched" }
    end,
    log = function(message) logs[#logs + 1] = message end,
}

local chunk, load_error = loadfile(source)
assert(chunk, load_error)
local ok, failure = pcall(chunk)
local function fail_text() return tostring(failure) end
local function count(pattern)
    local total = 0
    for _, message in ipairs(logs) do
        if message:find(pattern, 1, true) then total = total + 1 end
    end
    return total
end

if scenario == "two-legs" or scenario == "one-leg" then
    assert(ok, fail_text())
    assert(state.map_id == case.route.goal, "did not reach goal map")
    assert(count("navigate_arrived") == 1, "arrived was not logged exactly once")
    assert(count("navigate_leg") == #case.route.legs, "leg count mismatch")
elseif scenario == "map-mismatch" then
    assert(not ok, "unexpected map must stop")
    assert(fail_text():find("navigate_map_mismatch", 1, true), fail_text())
elseif scenario == "portal-unconfirmed" then
    assert(not ok, "portal without transition must stop")
    assert(fail_text():find("portal_unconfirmed", 1, true), fail_text())
elseif scenario == "on-goal-map" then
    assert(ok, fail_text())
    assert(state.map_id == case.route.goal)
    assert(count("navigate_leg") == 0, "already-on-goal-map must not transition")
elseif scenario == "hp-low" then
    assert(not ok, "low hp must stop")
    assert(fail_text():find("hp_limit", 1, true), fail_text())
    assert(transitions == 0, "low hp stopped after entering a portal")
elseif scenario == "budget" then
    assert(not ok, "exhausted budget must stop")
else
    error("unknown scenario " .. tostring(scenario))
end
