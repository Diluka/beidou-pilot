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

-- Height envelope of the segments that intersect a possible launch/landing strip.
local function height_range(platform, left, right, require_floor)
    if right < platform.left or platform.right < left then return nil end
    local low, high, covered = nil, nil, left
    local segments = platform.segments -- native segments are ordered left to right
    for i = 1, #segments, 4 do
        local a, b, y, end_y = segments[i], segments[i + 1], segments[i + 2], segments[i + 3]
        if a <= right and b >= left and (a < b or y == end_y) then
            if require_floor and a > covered then return nil end
            covered = math.max(covered, b)
            local slope = a < b and (end_y - y) / (b - a) or 0
            local y1 = y + (math.max(left, a) - a) * slope
            local y2 = y + (math.min(right, b) - a) * slope
            low, high = math.min(low or y1, y1, y2), math.max(high or y1, y1, y2)
        end
    end
    if require_floor and covered < right then return nil end
    return low, high
end

local function vertical_launch(platforms, from, to, probe, max_rise, apex)
    local source, target = platforms[from], platforms[to]
    -- move aligns to within 8px. Check the whole strip, not just its midpoint.
    local tolerance = 8
    local left = math.max(source.left, target.left) + tolerance
    local right = math.min(source.right, target.right) - tolerance
    if left > right then return nil end
    for _, x in ipairs({probe, left, right}) do
        if left <= x and x <= right then
            local lo, hi = x - tolerance, x + tolerance
            local top, bottom = height_range(source, lo, hi, true)
            local target_top, target_bottom = height_range(target, lo, hi, true)
            if top and target_top and bottom - target_top <= max_rise and target_bottom < top then
                local clear = true
                for i, p in ipairs(platforms) do
                    if i ~= from and i ~= to then
                        local near, far = height_range(p, lo, hi)
                        if near and near <= target_bottom and far >= top - apex then
                            clear = false
                            break
                        end
                    end
                end
                if clear then
                    return x, height_range(source, x, x) - height_range(target, x, x)
                end
            end
        end
    end
end

local function horizontal_launch(source, target, from, to, platforms, walls, model, max_rise)
    local rightward = source.right < target.left
    local leftward = target.right < source.left
    if not rightward and not leftward then return nil end
    local source_width = source.right - source.left
    local target_width = target.right - target.left
    local margin = math.min(8, source_width / 4, target_width / 4)
    local launch = rightward and source.right - margin or source.left + margin
    local destination = rightward and target.left + margin or target.right - margin
    -- Bound the horizontal span by the jump envelope plus the actor's height.
    if math.abs(destination - launch) > max_rise + model.stand_height then return nil end

    local source_edge = rightward and source.right or source.left
    local target_edge = rightward and target.left or target.right
    if not height_range(source, math.min(launch, source_edge), math.max(launch, source_edge), true)
        or not height_range(target, math.min(destination, target_edge), math.max(destination, target_edge), true) then
        return nil
    end
    local source_y = height_range(source, launch, launch)
    local target_y = height_range(target, destination, destination)
    if not source_y or not target_y then return nil end
    local rise = source_y - target_y
    if rise > max_rise or rise < -(model.drop_max + max_rise) then return nil end

    local apex_y = source_y - max_rise
    local left, right = math.min(launch, destination), math.max(launch, destination)
    for index, platform in ipairs(platforms) do
        if index ~= from and index ~= to then
            local near, far = height_range(platform, left, right)
            if near and near <= target_y and far >= apex_y then return nil end
        end
    end
    for index = 1, #walls, 3 do
        local x, top, bottom = walls[index], walls[index + 1], walls[index + 2]
        if x > left and x < right then
            local can_clear_above = math.max(0, source_y - top) <= max_rise
            local can_pass_below = math.min(source_y, target_y) - model.stand_height >= bottom
            if not can_clear_above and not can_pass_below then return nil end
        end
    end
    return launch, destination, rise
end

function M.plan(graph, from_index, to_index, options)
    if type(graph) ~= "table" or type(graph.model) ~= "table"
        or not finite_number(graph.model.jump_rise)
        or not finite_number(graph.model.drop_min)
        or not finite_number(graph.model.drop_max)
        or not finite_number(graph.model.rope_grab) then
        return nil, "model_unavailable"
    end

    local platforms, candidates = graph.platforms, graph.candidates
    if type(platforms) ~= "table" or type(candidates) ~= "table" then
        return nil, "model_unavailable"
    end
    local platform_count = #platforms
    local function valid_platform(index)
        return finite_number(index) and index % 1 == 0 and index >= 1 and index <= platform_count
    end
    if not valid_platform(from_index) or not valid_platform(to_index) then
        return nil, "invalid_platform"
    end
    if from_index == to_index then return {}, "same_platform" end

    options = type(options) == "table" and options or {}
    local speed = finite_number(options.speed) and options.speed or 100
    local max_jump_height = finite_number(options.max_jump_height) and options.max_jump_height
        or graph.model.jump_rise
    local blocked = type(options.blocked) == "table" and options.blocked or {}
    local effective_speed = math.max(1, speed)
    local model = graph.model
    local platform_x = {}
    for index, platform in ipairs(platforms) do
        platform_x[index] = (platform.left + platform.right) / 2
    end

    local adjacency, edges = {}, {}
    local edge_kinds = {"walk", "step", "jumpup", "drop", "rope"}
    local tuple_sizes = {walk = 5, step = 5, jumpup = 5, drop = 5, rope = 6}
    for _, kind in ipairs(edge_kinds) do
        local values, tuple_size = candidates[kind], tuple_sizes[kind]
        if type(values) == "table" then
            for offset = 1, #values, tuple_size do
                local from, to = values[offset], values[offset + 1]
                local x, destination, rise = values[offset + 2], values[offset + 3], values[offset + 4]
                local rope_index = kind == "rope" and values[offset + 5] or nil
                local valid = valid_platform(from) and valid_platform(to)
                    and finite_number(x) and finite_number(destination) and finite_number(rise)
                    and not blocked[tostring(from) .. ":" .. tostring(to)]
                if valid then
                    if kind == "jumpup" then
                        local max_rise = math.min(model.jump_rise, max_jump_height)
                        valid = rise <= max_rise
                        if valid and x == destination then
                            x, rise = vertical_launch(platforms, from, to, x, max_rise, max_jump_height)
                            valid, destination = x ~= nil, x
                        end
                    elseif kind == "drop" then
                        valid = rise >= model.drop_min and rise <= model.drop_max
                    elseif kind == "rope" then
                        valid = rise ~= 0
                    end
                end
                if valid then
                    local dx = math.abs(platform_x[to] - platform_x[from])
                    local cost
                    if kind == "walk" then
                        cost = dx / effective_speed
                    elseif kind == "step" then
                        cost = 0.05 + dx / effective_speed
                    elseif kind == "jumpup" then
                        cost = 0.6 + dx / effective_speed
                    elseif kind == "drop" then
                        cost = 0.4 + dx / effective_speed
                    else
                        cost = 0.8 + math.abs(rise) / 100
                    end
                    local edge = {
                        kind = kind,
                        from = from,
                        to = to,
                        x = x,
                        destination = destination,
                        rise = rise,
                        cost = cost,
                    }
                    if kind == "rope" then edge.rope_index = rope_index end
                    adjacency[from] = adjacency[from] or {}
                    adjacency[from][#adjacency[from] + 1] = edge
                    edges[#edges + 1] = edge
                end
            end
        end
    end

    -- Derive horizontal jumps from supported platform strips; reject ceilings and walls.
    local walls = type(graph.walls) == "table" and graph.walls or {}
    for from, source in ipairs(platforms) do
        for to, target in ipairs(platforms) do
            if from ~= to and not blocked[tostring(from) .. ":" .. tostring(to)] then
                local x, destination, rise = horizontal_launch(source, target, from, to, platforms, walls,
                    model, math.min(model.jump_rise, max_jump_height))
                if x then
                    local edge = {kind="horizontal_jump", from=from, to=to, x=x, destination=destination,
                        rise=rise, cost=0.8 + math.abs(destination - x) / effective_speed}
                    adjacency[from] = adjacency[from] or {}
                    adjacency[from][#adjacency[from] + 1] = edge
                    edges[#edges + 1] = edge
                end
            end
        end
    end

    -- Derive vertical platform-through relations without changing the native snapshot.
    for from, source in ipairs(platforms) do
        for to, target in ipairs(platforms) do
            if from ~= to and not blocked[tostring(from) .. ":" .. tostring(to)] then
                local left = math.max(source.left, target.left) + 8
                local right = math.min(source.right, target.right) - 8
                if left <= right and target.right - target.left >= model.min_platform_width then
                    local x = (left + right) / 2
                    local lo, hi = x - 8, x + 8
                    local source_top, source_bottom = height_range(source, lo, hi, true)
                    local target_top, target_bottom = height_range(target, lo, hi, true)
                    local clear = source_top and target_top and target_top > source_bottom
                    if clear then
                        for i, platform in ipairs(platforms) do
                            if i ~= from and i ~= to then
                                local top, bottom = height_range(platform, lo, hi)
                                if top and top <= target_bottom and bottom >= source_top - model.stand_height then
                                    clear = false
                                    break
                                end
                            end
                        end
                    end
                    if clear then
                        for i = 1, #graph.walls, 3 do
                            local wx, top, bottom = graph.walls[i], graph.walls[i+1], graph.walls[i+2]
                            if wx >= lo - model.wall_margin and wx <= hi + model.wall_margin
                                and top <= target_bottom and bottom >= source_top - model.stand_height then
                                clear = false
                                break
                            end
                        end
                    end
                    if clear then
                        local edge = {kind="downjump", from=from, to=to, x=x, destination=x,
                            rise=height_range(target, x, x) - height_range(source, x, x),
                            cost=0.6 + math.abs(platform_x[to] - platform_x[from]) / effective_speed}
                        adjacency[from] = adjacency[from] or {}
                        adjacency[from][#adjacency[from] + 1] = edge
                        edges[#edges + 1] = edge
                    end
                end
            end
        end
    end

    for _, outgoing in pairs(adjacency) do
        table.sort(outgoing, function(left, right)
            if left.to ~= right.to then return left.to < right.to end
            return left.kind < right.kind
        end)
    end

    local minimum_cost_per_x = math.huge
    for _, edge in ipairs(edges) do
        local dx = math.abs(platform_x[edge.to] - platform_x[edge.from])
        if dx > 0 then minimum_cost_per_x = math.min(minimum_cost_per_x, edge.cost / dx) end
    end
    if minimum_cost_per_x == math.huge then minimum_cost_per_x = 0 end
    local function heuristic(index)
        return minimum_cost_per_x * math.abs(platform_x[to_index] - platform_x[index])
    end
    local function entry_before(left, right)
        if left.estimate ~= right.estimate then return left.estimate < right.estimate end
        if left.from ~= right.from then return left.from < right.from end
        if left.to ~= right.to then return left.to < right.to end
        if left.kind ~= right.kind then return left.kind < right.kind end
        return left.index < right.index
    end

    local distances = {[from_index] = 0}
    local previous = {}
    local open = {{index = from_index, from = from_index, to = from_index, kind = "", cost = 0,
        estimate = heuristic(from_index)}}
    local closed = {}
    while #open > 0 do
        table.sort(open, entry_before)
        local current = table.remove(open, 1)
        if not closed[current.index] and current.cost == distances[current.index] then
            if current.index == to_index then
                local path, index = {}, to_index
                while index ~= from_index do
                    local parent = previous[index]
                    table.insert(path, 1, parent.edge)
                    index = parent.from
                end
                for _, edge in ipairs(path) do edge.cost = nil end
                return path
            end
            closed[current.index] = true
            for _, edge in ipairs(adjacency[current.index] or {}) do
                if not closed[edge.to] then
                    local distance = current.cost + edge.cost
                    if distances[edge.to] == nil or distance < distances[edge.to] then
                        distances[edge.to] = distance
                        previous[edge.to] = {from = current.index, edge = edge}
                        open[#open + 1] = {
                            index = edge.to,
                            from = edge.from,
                            to = edge.to,
                            kind = edge.kind,
                            cost = distance,
                            estimate = distance + heuristic(edge.to),
                        }
                    end
                end
            end
        end
    end
    return nil, "no_path"
end

return M
