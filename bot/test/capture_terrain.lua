-- @tick.gear 1
-- @tick.budget_ms 100

local target_map_id = 102000000

local function serialize(value, depth)
    local kind = type(value)
    if kind == "string" then return string.format("%q", value) end
    if kind == "number" then
        assert(value == value and value ~= math.huge and value ~= -math.huge, "fixture contains a non-finite number")
        return string.format("%.17g", value)
    end
    if kind == "boolean" then return tostring(value) end
    assert(kind == "table", "fixture contains unsupported " .. kind)

    local keys = {}
    for key in pairs(value) do
        assert(type(key) == "string" or type(key) == "number", "fixture contains an unsupported table key")
        keys[#keys + 1] = key
    end
    table.sort(keys, function(left, right)
        if type(left) ~= type(right) then return type(left) < type(right) end
        return left < right
    end)

    if #keys == 0 then return "{}" end
    local indent = string.rep("    ", depth)
    local child_indent = string.rep("    ", depth + 1)
    local fields = {}
    local array = true
    for index, key in ipairs(keys) do
        if type(key) ~= "number" or key ~= index then
            array = false
            break
        end
    end
    if array then
        for _, key in ipairs(keys) do
            fields[#fields + 1] = child_indent .. serialize(value[key], depth + 1) .. ","
        end
    else
        for _, key in ipairs(keys) do
            local key_text
            if type(key) == "string" and key:match("^[%a_][%w_]*$") then
                key_text = key
            else
                key_text = "[" .. serialize(key, 0) .. "]"
            end
            fields[#fields + 1] = child_indent .. key_text .. " = " .. serialize(value[key], depth + 1) .. ","
        end
    end
    return "{\n" .. table.concat(fields, "\n") .. "\n" .. indent .. "}"
end

local function main(context)
    local scene = context.scene
    assert(scene.map_id == target_map_id, "capture must run on map " .. target_map_id)
    assert(scene.scene_generation > 0, "scene generation is unavailable")

    local terrain = scene.terrain
    assert(terrain.status == "available", "terrain is not available: " .. tostring(terrain.error))
    local navigation = terrain.navigation
    assert(type(navigation) == "table" and type(navigation.platforms) == "table" and #navigation.platforms > 0,
        "navigation platforms are unavailable")

    local fixture = {
        map_id = scene.map_id,
        scene_generation = scene.scene_generation,
        navigation = navigation,
    }
    local path = ("/work/bot/fixtures/map_%d.lua"):format(scene.map_id)
    local output = assert(io.open(path, "wb"))
    assert(output:write("return ", serialize(fixture, 0), "\n"))
    assert(output:close())
    local verify = assert(io.open(path, "rb"))
    local captured = verify:read("*a")
    assert(verify:close())
    assert(type(captured) == "string" and #captured > 0, "fixture write was not confirmed")

    game.log(("terrain fixture captured map=%d generation=%d platforms=%d ropes=%d bytes=%d path=%s")
        :format(scene.map_id, scene.scene_generation, #navigation.platforms, #navigation.ropes, #captured, path))
    return "done"
end
