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
    target = {
        selector = 1,
        step = 6,
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
    metrics = {
        new = 1,
        observe = 3,
        event = 3,
        flush = 3,
        target = 2,
        visit = 2,
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
for _, path in ipairs({"bot/test/capture_terrain.lua", "bot/test/owner_drive.lua", "bot/test/test_terrain.lua", "bot/test/test_move.lua", "bot/test/test_sustain.lua", "bot/test/test_follow.lua", "bot/test/test_loot.lua", "bot/test/test_combat.lua", "bot/test/test_memory.lua", "bot/test/test_equipment.lua", "bot/safe_spot.lua"}) do
    local chunk, load_error = loadfile(path)
    assert(chunk, load_error)
end

local fixtures = {
    dofile("bot/test/fixtures/synthetic.lua"),
    dofile("bot/test/fixtures/map_102000000.lua"),
    dofile("bot/test/fixtures/map_10000.lua"),
}
for _, fixture in ipairs(fixtures) do
    assert(type(fixture) == "table" and type(fixture.map_id) == "number"
        and fixture.map_id > 0 and fixture.map_id % 1 == 0, "fixture map_id must be a positive integer")
    assert(type(fixture.scene_generation) == "number" and fixture.scene_generation > 0
        and fixture.scene_generation % 1 == 0, "fixture scene_generation must be a positive integer")
    assert(type(fixture.navigation) == "table", "fixture navigation is required")
    local allowed_fixture_fields = {map_id = true, scene_generation = true, navigation = true}
    for field in pairs(fixture) do
        assert(allowed_fixture_fields[field], "fixture has unexpected field " .. tostring(field))
    end
    local navigation = fixture.navigation
    local allowed_navigation_fields = {
        model = true, terrain_left = true, terrain_right = true,
        platforms = true, walls = true, ropes = true, candidates = true,
    }
    for field in pairs(navigation) do
        assert(allowed_navigation_fields[field], "fixture navigation has unexpected field " .. tostring(field))
    end

    local model_fields = {
        "stand_height", "wall_margin", "min_platform_width", "jump_rise",
        "drop_min", "drop_max", "rope_grab",
    }
    assert(type(navigation.model) == "table", "fixture model is required")
    local allowed_model_fields = {}
    for _, field in ipairs(model_fields) do
        allowed_model_fields[field] = true
        assert(type(navigation.model[field]) == "number", "fixture model." .. field .. " must be numeric")
    end
    for field in pairs(navigation.model) do
        assert(allowed_model_fields[field], "fixture model has unexpected field " .. field)
    end
    assert(type(navigation.terrain_left) == "number" and type(navigation.terrain_right) == "number"
        and navigation.terrain_left <= navigation.terrain_right, "fixture terrain bounds are invalid")

    local platforms_by_index = {}
    local allowed_platform_fields = {
        index = true, left = true, right = true, open_left = true, open_right = true, segments = true,
    }
    assert(type(navigation.platforms) == "table" and #navigation.platforms > 0,
        "fixture platforms must be non-empty")
    for _, platform in ipairs(navigation.platforms) do
        assert(type(platform.index) == "number" and platform.index >= 1 and platform.index % 1 == 0
            and platforms_by_index[platform.index] == nil,
            "fixture platform indexes must be positive integers and unique")
        assert(type(platform.left) == "number" and type(platform.right) == "number"
            and platform.left <= platform.right, "fixture platform bounds are invalid")
        assert(type(platform.open_left) == "boolean" and type(platform.open_right) == "boolean",
            "fixture platform open-edge flags must be boolean")
        assert(type(platform.segments) == "table" and #platform.segments > 0 and #platform.segments % 4 == 0,
            "fixture platform segments must contain left/right/y1/y2 tuples")
        for field in pairs(platform) do
            assert(allowed_platform_fields[field], "fixture platform has unexpected field " .. field)
        end
        for i = 1, #platform.segments, 4 do
            local left, right, y1, y2 = platform.segments[i], platform.segments[i + 1],
                platform.segments[i + 2], platform.segments[i + 3]
            assert(type(left) == "number" and type(right) == "number"
                and type(y1) == "number" and type(y2) == "number" and left <= right,
                "fixture platform segment geometry is invalid")
        end
        platforms_by_index[platform.index] = platform
    end

    local function platform_y_at(platform, x)
        for i = 1, #platform.segments, 4 do
            local left, right, y1, y2 = platform.segments[i], platform.segments[i + 1],
                platform.segments[i + 2], platform.segments[i + 3]
            if x >= left and x <= right then
                if left == right then
                    if y1 == y2 then return y1 end
                else
                    return y1 + (x - left) / (right - left) * (y2 - y1)
                end
            end
        end
    end

    assert(type(navigation.walls) == "table" and #navigation.walls % 3 == 0,
        "fixture walls must contain x/top/bottom tuples")
    for _, value in ipairs(navigation.walls) do
        assert(type(value) == "number", "fixture wall values must be numeric")
    end

    local ropes_by_index = {}
    local allowed_rope_fields = {index = true, x = true, y1 = true, y2 = true, platforms = true}
    assert(type(navigation.ropes) == "table", "fixture ropes are required")
    for _, rope in ipairs(navigation.ropes) do
        assert(type(rope.index) == "number" and rope.index >= 1 and rope.index % 1 == 0
            and ropes_by_index[rope.index] == nil,
            "fixture rope indexes must be positive integers and unique")
        assert(type(rope.x) == "number" and type(rope.y1) == "number" and type(rope.y2) == "number",
            "fixture rope geometry must be numeric")
        assert(type(rope.platforms) == "table" and #rope.platforms % 2 == 0,
            "fixture rope platforms must contain platform-index/height pairs")
        for field in pairs(rope) do
            assert(allowed_rope_fields[field], "fixture rope has unexpected field " .. field)
        end
        for i = 1, #rope.platforms, 2 do
            local platform_index, y = rope.platforms[i], rope.platforms[i + 1]
            assert(type(platform_index) == "number" and platforms_by_index[platform_index]
                and type(y) == "number", "fixture rope platform pair is invalid")
            local actual_y = platform_y_at(platforms_by_index[platform_index], rope.x)
            assert(actual_y ~= nil and math.abs(actual_y - y) < 0.001,
                "fixture rope platform height must match its platform")
        end
        ropes_by_index[rope.index] = rope
    end

    local candidate_specs = {
        walk = {size = 5, rise_sign = 1, rise_mode = "edges"},
        step = {size = 5, rise_sign = 1, rise_mode = "edges"},
        jumpup = {size = 5, rise_sign = 1, rise_mode = "points"},
        drop = {size = 5, rise_sign = -1, rise_mode = "drop_edge"},
        rope = {size = 6, rise_sign = -1, rise_mode = "points"},
    }
    assert(type(navigation.candidates) == "table", "fixture candidates are required")
    for kind in pairs(navigation.candidates) do
        assert(candidate_specs[kind], "fixture candidates have unexpected kind " .. tostring(kind))
    end
    for kind, spec in pairs(candidate_specs) do
        local values = navigation.candidates[kind]
        assert(type(values) == "table" and #values % spec.size == 0,
            "fixture " .. kind .. " candidates must contain complete flat tuples")
        for i = 1, #values, spec.size do
            local from, to, x, destination, rise = values[i], values[i + 1], values[i + 2],
                values[i + 3], values[i + 4]
            for offset = 0, spec.size - 1 do
                assert(type(values[i + offset]) == "number",
                    "fixture " .. kind .. " candidate values must be numeric")
            end
            local source = platforms_by_index[from]
            local target = platforms_by_index[to]
            assert(source and target, kind .. " candidate platforms must exist")
            local source_y = platform_y_at(source, x)
            local destination_y = platform_y_at(target, destination)
            assert(source_y ~= nil, kind .. " candidate start must lie on its source platform")
            assert(destination_y ~= nil, kind .. " candidate destination must lie on its target platform")
            local rise_source_y, rise_target_y = source_y, destination_y
            if spec.rise_mode == "edges" then
                local direction = source.right <= target.left and 1 or -1
                local source_edge = direction == 1 and source.right or source.left
                local target_edge = direction == 1 and target.left or target.right
                rise_source_y = platform_y_at(source, source_edge)
                rise_target_y = platform_y_at(target, target_edge)
            elseif spec.rise_mode == "drop_edge" then
                local source_edge
                if destination < source.left then
                    source_edge = source.left
                else
                    assert(destination > source.right, "drop candidate must land outside its source platform")
                    source_edge = source.right
                end
                rise_source_y = platform_y_at(source, source_edge)
            end
            assert(rise_source_y ~= nil and rise_target_y ~= nil,
                kind .. " candidate rise reference heights must lie on their platforms")
            assert(math.abs(rise - spec.rise_sign * (rise_source_y - rise_target_y)) < 0.001,
                kind .. " candidate rise must match its movement reference heights")
            if kind == "rope" then
                local rope_index = values[i + 5]
                local rope = ropes_by_index[rope_index]
                assert(rope and x == rope.x and destination == rope.x,
                    "rope candidate must reference the matching rope")
                local source_level, target_level = false, false
                for j = 1, #rope.platforms, 2 do
                    if rope.platforms[j] == from and math.abs(rope.platforms[j + 1] - source_y) < 0.001 then
                        source_level = true
                    end
                    if rope.platforms[j] == to and math.abs(rope.platforms[j + 1] - destination_y) < 0.001 then
                        target_level = true
                    end
                end
                assert(source_level and target_level and source_y ~= destination_y,
                    "rope candidate endpoints must match its platform intersections")
            end
        end
    end

end

local defaults = require("defaults")
local expected_defaults = {
    owner_name = "",
    owner_character_id = 0,
    attack_skill_id = 0,
    hp_item = 0,
    mp_item = 0,
    follow_distance = 80,
    stop_distance = 40,
    pot_hp = 60,
    pot_mp = 30,
    loot_radius = 150,
    metrics_enabled = 1,
    attack_mode = "melee",
    attack_range = 110,
    min_range = 60,
    ranged_skill_id = 3000002,
    ranged_skill_bonus_per_level = 15,
    ranged_skill_level = 0,
    skill_mp_cost = 10,
    ammo_item_id = 2060000,
    ammo_low = 50,
}
local default_count = 0
for key, value in pairs(defaults) do
    default_count = default_count + 1
    assert(expected_defaults[key] == value, "unexpected or incorrect default " .. tostring(key))
end
local expected_default_count = 0
for _ in pairs(expected_defaults) do expected_default_count = expected_default_count + 1 end
assert(default_count == expected_default_count, "defaults must contain exactly the documented keys")

local function check_stub(fn, expected_status, ...)
    local status, detail = fn(...)
    assert(status == expected_status and detail == "not_implemented", "stub return contract changed")
end

dofile("bot/test/test_move.lua")
dofile("bot/test/test_io.lua")
dofile("bot/test/test_target.lua")

dofile("bot/test/test_terrain.lua")
dofile("bot/test/test_sustain.lua")
dofile("bot/test/test_supply.lua")
dofile("bot/test/test_follow.lua")
dofile("bot/test/test_loot.lua")
dofile("bot/test/test_combat.lua")
dofile("bot/test/test_hunt.lua")
dofile("bot/test/test_travel.lua")
dofile("bot/test/test_map_binding.lua")
dofile("bot/test/test_supply_guard.lua")
dofile("bot/test/test_supply_stop.lua")
dofile("bot/test/test_memory.lua")
dofile("bot/test/test_equipment.lua")
dofile("bot/test/test_metrics.lua")
dofile("bot/test/test_metrics_storage.lua")
dofile("bot/test/test_metrics_wire.lua")
print("bot smoke ok: 10 modules")
