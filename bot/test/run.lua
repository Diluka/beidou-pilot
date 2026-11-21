package.path = "bot/?.lua;bot/?/init.lua;" .. package.path

local expected = {
    terrain = {
        build = 1,
        platform_at = 4,
        plan = 4,
    },
    move = {
        new = 1,
        set_path = 2,
        step = 3,
        stop = 1,
    },
    follow = {
        update = 2,
    },
    combat = {
        select = 2,
        step = 4,
    },
    sustain = {
        step = 2,
    },
    loot = {
        select = 2,
        step = 4,
    },
    io = {
        poll = 2,
        publish = 3,
        event = 3,
    },
    state = {
        new = 0,
        apply = 2,
        transition = 3,
    },
    world = {
        observe = 1,
    },
}

local modules = {}
for name, functions in pairs(expected) do
    local module = require("lib." .. name)
    assert(type(module) == "table", name .. " must return a table")
    modules[name] = module

    local actual_count = 0
    for function_name, fn in pairs(module) do
        actual_count = actual_count + 1
        assert(functions[function_name] ~= nil, name .. " has unexpected export " .. function_name)
        assert(type(fn) == "function", name .. "." .. function_name .. " must be a function")
        assert(debug.getinfo(fn, "u").nparams == functions[function_name],
            name .. "." .. function_name .. " has the wrong parameter count")
    end
    local expected_count = 0
    for _ in pairs(functions) do
        expected_count = expected_count + 1
    end
    assert(actual_count == expected_count, name .. " is missing an export")
end

local main_chunk, main_error = loadfile("bot/main.lua")
assert(main_chunk, main_error)

local navigation = dofile("bot/test/fixtures/synthetic.lua")
assert(type(navigation) == "table" and navigation.map_id ~= nil, "fixture map_id is required")
assert(type(navigation.model) == "table", "fixture model is required")
assert(type(navigation.platforms) == "table" and #navigation.platforms > 0,
    "fixture platforms must be non-empty")
assert(type(navigation.walls) == "table", "fixture walls are required")
assert(type(navigation.ropes) == "table" and #navigation.ropes > 0, "fixture ropes are required")
assert(type(navigation.candidates) == "table", "fixture candidates are required")
local candidate_kinds = {}
local platforms_by_index = {}
for _, platform in ipairs(navigation.platforms) do
    platforms_by_index[platform.index] = platform
end
local function platform_y_at(platform, x)
    if x < math.min(platform.x1, platform.x2) or x > math.max(platform.x1, platform.x2) then
        return nil
    end
    local ratio = (x - platform.x1) / (platform.x2 - platform.x1)
    return platform.y1 + ratio * (platform.y2 - platform.y1)
end
for _, candidate in ipairs(navigation.candidates) do
    candidate_kinds[candidate.kind] = true
    local source = platforms_by_index[candidate.from]
    local destination = platforms_by_index[candidate.to]
    assert(source and platform_y_at(source, candidate.x) ~= nil,
        candidate.kind .. " candidate start must lie on its source platform")
    local destination_y = destination and platform_y_at(destination, candidate.destination.x)
    assert(destination_y and math.abs(destination_y - candidate.destination.y) < 0.001,
        candidate.kind .. " candidate destination must lie on its target platform")
end
for _, kind in ipairs({"walk", "step", "jumpup", "drop", "rope"}) do
    assert(candidate_kinds[kind], "fixture candidate missing " .. kind)
end

local defaults = require("defaults")
assert(defaults.owner == "", "default owner must be empty")
assert(defaults.follow_distance == 80 and defaults.stop_distance == 40,
    "follow distance defaults do not match the package contract")
assert(defaults.pot_hp == 60 and defaults.pot_mp == 30, "potion thresholds do not match the package contract")
assert(defaults.loot_radius == 150, "loot radius default does not match the package contract")
assert(defaults.attack_skill == 0 and defaults.pot_hp_item == 0 and defaults.pot_mp_item == 0,
    "skill and potion item placeholders must be zero")

local function check_stub(fn, expected_status, ...)
    local status, detail = fn(...)
    assert(status == expected_status and detail == "not_implemented", "stub return contract changed")
end

check_stub(modules.terrain.build, nil, {})
check_stub(modules.terrain.platform_at, nil, {}, 0, 0, 0)
check_stub(modules.terrain.plan, nil, {}, 1, 2, {})
check_stub(modules.move.new, nil, {})
check_stub(modules.move.set_path, false, {}, {})
check_stub(modules.move.step, "failed", {}, {}, {})
check_stub(modules.move.stop, false, {})
check_stub(modules.follow.update, nil, {}, {})
check_stub(modules.combat.select, nil, {}, {})
check_stub(modules.combat.step, "failed", {}, {}, {}, {})
check_stub(modules.sustain.step, false, {}, {})
check_stub(modules.loot.select, nil, {}, {})
check_stub(modules.loot.step, "failed", {}, {}, {}, {})
check_stub(modules.io.poll, nil, {}, 0)
check_stub(modules.io.publish, false, {}, {}, 0)
check_stub(modules.io.event, false, {}, "test", {})
check_stub(modules.state.new, nil)
check_stub(modules.state.apply, false, {}, {})
check_stub(modules.state.transition, false, {}, "idle", "test")
check_stub(modules.world.observe, nil, {})

print("bot smoke ok: 9 modules")
