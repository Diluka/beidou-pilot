local M = {}

local function finite_number(value)
    return type(value) == "number" and value == value and value ~= math.huge and value ~= -math.huge
end

local function dense_array_length(values)
    if type(values) ~= "table" then return nil end
    local count, maximum = 0, 0
    for key in pairs(values) do
        if not finite_number(key) or key < 1 or key % 1 ~= 0 then return nil end
        count = count + 1
        if key > maximum then maximum = key end
    end
    if count ~= maximum then return nil end
    return maximum
end

local function invalid(field)
    return nil, "navigation_invalid:" .. field
end

function M.build(navigation)
    if navigation == nil then return nil, "navigation_unavailable" end
    if type(navigation) ~= "table" then return invalid("navigation") end

    local model = navigation.model
    if type(model) ~= "table" then return invalid("model") end
    for _, field in ipairs({
        "stand_height", "wall_margin", "min_platform_width", "jump_rise",
        "drop_min", "drop_max", "rope_grab",
    }) do
        if not finite_number(model[field]) then return invalid("model") end
    end

    local platforms = navigation.platforms
    local platform_count = dense_array_length(platforms)
    if platform_count == nil or platform_count == 0 then return invalid("platforms") end
    local platform_indexes = {}
    for index = 1, platform_count do
        local platform = platforms[index]
        local segments = type(platform) == "table" and platform.segments or nil
        local segment_count = dense_array_length(segments)
        if type(platform) ~= "table"
            or platform.index ~= index
            or not finite_number(platform.left)
            or not finite_number(platform.right)
            or platform.left > platform.right
            or type(platform.open_left) ~= "boolean"
            or type(platform.open_right) ~= "boolean"
            or segment_count == nil
            or segment_count == 0
            or segment_count % 4 ~= 0 then
            return invalid("platforms")
        end
        for segment_index = 1, segment_count, 4 do
            local left, right, y1, y2 = segments[segment_index], segments[segment_index + 1],
                segments[segment_index + 2], segments[segment_index + 3]
            if not finite_number(left) or not finite_number(right)
                or not finite_number(y1) or not finite_number(y2) or left > right then
                return invalid("platforms")
            end
        end
        platform_indexes[index] = true
    end

    local terrain_left, terrain_right = navigation.terrain_left, navigation.terrain_right
    if not finite_number(terrain_left) or not finite_number(terrain_right) or terrain_left > terrain_right then
        return invalid("terrain_bounds")
    end
    local walls = navigation.walls
    local wall_count = dense_array_length(walls)
    if wall_count == nil or wall_count % 3 ~= 0 then return invalid("walls") end
    for index = 1, wall_count do
        if not finite_number(walls[index]) then return invalid("walls") end
    end

    local ropes = navigation.ropes
    local rope_count = dense_array_length(ropes)
    if rope_count == nil then return invalid("ropes") end
    local rope_indexes = {}
    for index = 1, rope_count do
        local rope = ropes[index]
        if type(rope) ~= "table" or not finite_number(rope.index)
            or rope.index < 1 or rope.index % 1 ~= 0 or rope_indexes[rope.index]
            or not finite_number(rope.x) or not finite_number(rope.y1) or not finite_number(rope.y2) then
            return invalid("ropes")
        end
        local rope_platforms = rope.platforms
        local rope_platform_count = dense_array_length(rope_platforms)
        if rope_platform_count == nil or rope_platform_count % 2 ~= 0 then return invalid("ropes") end
        for pair_index = 1, rope_platform_count, 2 do
            local platform_index, y = rope_platforms[pair_index], rope_platforms[pair_index + 1]
            if not finite_number(platform_index) or platform_index % 1 ~= 0
                or not platform_indexes[platform_index] or not finite_number(y) then
                return invalid("ropes")
            end
        end
        rope_indexes[rope.index] = true
    end

    local candidates = navigation.candidates
    if type(candidates) ~= "table" then return invalid("candidates") end
    for kind, tuple_size in pairs({walk = 5, step = 5, jumpup = 5, drop = 5, rope = 6}) do
        local values = candidates[kind]
        local candidate_count = dense_array_length(values)
        if candidate_count == nil or candidate_count % tuple_size ~= 0 then return invalid("candidates") end
        for index = 1, candidate_count do
            if not finite_number(values[index]) then return invalid("candidates") end
        end
        for index = 1, candidate_count, tuple_size do
            local from, to = values[index], values[index + 1]
            if from % 1 ~= 0 or to % 1 ~= 0 or not platform_indexes[from] or not platform_indexes[to] then
                return invalid("candidates")
            end
            if kind == "rope" then
                local rope_index = values[index + 5]
                if rope_index % 1 ~= 0 or not rope_indexes[rope_index] then return invalid("candidates") end
            end
        end
    end

    return {
        navigation = navigation,
        platforms = platforms,
        walls = walls,
        ropes = ropes,
        candidates = candidates,
        model = model,
        terrain_left = terrain_left,
        terrain_right = terrain_right,
    }
end

function M.platform_at(graph, x, y, tolerance)
    if type(graph) ~= "table" or type(graph.platforms) ~= "table"
        or not finite_number(x) or not finite_number(y)
        or not finite_number(tolerance) or tolerance < 0 then
        return nil
    end

    local best_index, best_distance
    for platform_index, platform in ipairs(graph.platforms) do
        if x >= platform.left and x <= platform.right then
            for segment_index = 1, #platform.segments, 4 do
                local left, right, y1, y2 = platform.segments[segment_index], platform.segments[segment_index + 1],
                    platform.segments[segment_index + 2], platform.segments[segment_index + 3]
                if x >= left and x <= right then
                    local height
                    if left == right then
                        if y1 == y2 then height = y1 end
                    else
                        height = y1 + (x - left) / (right - left) * (y2 - y1)
                    end
                    if height ~= nil then
                        local distance = math.abs(y - height)
                        if distance <= tolerance and (best_distance == nil or distance < best_distance
                            or (distance == best_distance and platform_index < best_index)) then
                            best_index, best_distance = platform_index, distance
                        end
                    end
                end
            end
        end
    end
    return best_index
end

function M.plan(graph, from_index, to_index, options)
    return nil, "not_implemented"
end

return M
