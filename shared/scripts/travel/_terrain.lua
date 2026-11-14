-- 单地图静态地形图：由 footholds/ropes 构建可站立区间、竖直墙、可执行边与最短路径。
-- 由策略装载器拼接在消费者之前，只做静态计算，不调用原生动作。
--
-- 模型事实：
-- - foothold 的 x1 == x2 段是竖直墙；与角色站立高度重叠的墙把平台切成不同区间。
-- - 平台内部按墙切分后，两端只有落在原平台物理边缘上时才可走出去。
-- - 客户端没有空中主动横向控制；起跳后的水平位移由起跳瞬间速度决定。
-- - 绳索与沿途每层平台都可以连接，绳底高于平台时按跳跃可及范围处理。
-- - 跳跃高度实测约 78px；地面速度约 130px/s；跳跃水平惯性位移约 58px。

-- 角色站立时占据的竖直范围，用于判断墙体是否挡住站在平台上的角色。
local TERRAIN_BODY_HEIGHT = 70
-- 角色半宽；墙切分平台时在墙两侧留出的可站立边界。
local TERRAIN_WALL_MARGIN = 12
-- 平台切分后保留的最短可站立宽度，更窄的残段不作为节点。
local TERRAIN_MIN_WIDTH = 16
-- 跳跃高度实测约 78px，规划取保守值。
local TERRAIN_JUMP_RISE = 75
-- 走出平台边缘后可能的水平落点范围。
local TERRAIN_DROP_MIN = 4
local TERRAIN_DROP_MAX = 65
-- 绳底高于平台时的跳跃抓绳上限（跳跃高度 + 抓取容差）。
local TERRAIN_ROPE_GRAB = 95

local function terrain_sort(list, less)
    -- 手工归并排序：table.sort 的比较回调由 C 调用，命中指令预算时不可让出。
    local width = 1
    while width < #list do
        local merged, index = {}, 1
        while index <= #list do
            local left_end = math.min(index + width - 1, #list)
            local right_end = math.min(index + 2 * width - 1, #list)
            local left, right = index, left_end + 1
            while left <= left_end or right <= right_end do
                if right > right_end or (left <= left_end and not less(list[right], list[left])) then
                    merged[#merged + 1], left = list[left], left + 1
                else
                    merged[#merged + 1], right = list[right], right + 1
                end
            end
            index = right_end + 1
        end
        list, width = merged, width * 2
        game.sleep(0)
    end
    return list
end

local function terrain_segment_height(segment, x)
    if segment.right == segment.left then return segment.y1 end
    return segment.y1 + (segment.y2 - segment.y1) * (x - segment.left) / (segment.right - segment.left)
end

local function terrain_height(platform, x)
    for _, segment in ipairs(platform.segments) do
        if x <= segment.right then return terrain_segment_height(segment, x) end
    end
    return terrain_segment_height(platform.segments[#platform.segments], x)
end

local function terrain_inside(platform, x) return math.max(platform.left, math.min(platform.right, x)) end

-- 竖直墙按 x 归并成完整墙面；同一 x 上相邻的 y 段属于同一面墙。
local function terrain_walls(footholds)
    local segments = {}
    for _, foothold in ipairs(footholds) do
        if foothold.x1 == foothold.x2 then
            segments[#segments + 1] = {
                x = foothold.x1,
                top = math.min(foothold.y1, foothold.y2),
                bottom = math.max(foothold.y1, foothold.y2),
            }
        end
    end
    segments = terrain_sort(segments, function(a, b) return a.x < b.x or a.x == b.x and a.top < b.top end)
    local walls = {}
    for _, segment in ipairs(segments) do
        local last = walls[#walls]
        if last and last.x == segment.x and segment.top <= last.bottom + 4 then
            if segment.bottom > last.bottom then last.bottom = segment.bottom end
        else
            walls[#walls + 1] = { x = segment.x, top = segment.top, bottom = segment.bottom }
        end
    end
    return walls
end

-- 墙是否挡住站在该平台高度上的角色。
local function terrain_wall_blocks(wall, platform, x)
    local y = terrain_height(platform, x)
    return wall.top <= y and wall.bottom >= y - TERRAIN_BODY_HEIGHT
end

-- 横向移动路径内是否有挡住在给定竖直范围上的墙。
local function terrain_crosses_wall(walls, x1, x2, y_top, y_bottom)
    local left, right = math.min(x1, x2), math.max(x1, x2)
    for _, wall in ipairs(walls) do
        if wall.x > left + 1 and wall.x < right - 1 and wall.top <= y_bottom and wall.bottom >= y_top then
            return wall
        end
    end
    return nil
end

-- 同高接缝合并成平台；接缝不是落边，保留各段高度。
local function terrain_merge_platforms(segments)
    local by_id, assigned, platforms = {}, {}, {}
    for _, segment in ipairs(segments) do
        by_id[segment.id] = segment
    end
    for _, segment in ipairs(segments) do
        if not assigned[segment.id] then
            local parts, cursor = { segment }, 1
            assigned[segment.id] = true
            while cursor <= #parts do
                local part = parts[cursor]
                cursor = cursor + 1
                for _, id in ipairs({ part.prev, part.next }) do
                    local neighbor = by_id[id]
                    if neighbor and not assigned[id] then
                        local joins_right = part.right == neighbor.left and part.y2 == neighbor.y1
                        local joins_left = part.left == neighbor.right and part.y1 == neighbor.y2
                        if joins_right or joins_left then
                            assigned[id], parts[#parts + 1] = true, neighbor
                        end
                    end
                end
            end
            parts = terrain_sort(parts, function(a, b) return a.left < b.left end)
            platforms[#platforms + 1] = {
                left = parts[1].left,
                right = parts[#parts].right,
                y1 = parts[1].y1,
                y2 = parts[#parts].y2,
                segments = parts,
            }
        end
    end
    return platforms
end

local function terrain_slice(platform, left, right)
    local parts = {}
    for _, segment in ipairs(platform.segments) do
        local slice_left, slice_right = math.max(segment.left, left), math.min(segment.right, right)
        if slice_right > slice_left then
            parts[#parts + 1] = {
                left = slice_left,
                right = slice_right,
                y1 = terrain_segment_height(segment, slice_left),
                y2 = terrain_segment_height(segment, slice_right),
            }
        end
    end
    return parts
end

-- 用阻挡墙把平台切成可站立区间；切分边界留出角色半宽。
local function terrain_split_platforms(platforms, walls)
    local result = {}
    for _, platform in ipairs(platforms) do
        local cuts = {}
        for _, wall in ipairs(walls) do
            if
                wall.x > platform.left + TERRAIN_WALL_MARGIN
                and wall.x < platform.right - TERRAIN_WALL_MARGIN
                and terrain_wall_blocks(wall, platform, wall.x)
            then
                cuts[#cuts + 1] = wall.x
            end
        end
        cuts = terrain_sort(cuts, function(a, b) return a < b end)
        if #cuts == 0 then
            local sliced = terrain_slice(platform, platform.left, platform.right)
            if #sliced > 0 then
                result[#result + 1] = {
                    left = platform.left,
                    right = platform.right,
                    y1 = sliced[1].y1,
                    y2 = sliced[#sliced].y2,
                    segments = sliced,
                    left_open = true,
                    right_open = true,
                }
            end
        else
            local bounds, cursor = {}, platform.left
            for _, x in ipairs(cuts) do
                if x - TERRAIN_WALL_MARGIN >= cursor then
                    bounds[#bounds + 1] = cursor
                    bounds[#bounds + 1] = x - TERRAIN_WALL_MARGIN
                    cursor = x + TERRAIN_WALL_MARGIN
                end
            end
            bounds[#bounds + 1] = cursor
            bounds[#bounds + 1] = platform.right
            for index = 1, #bounds, 2 do
                local left, right = bounds[index], bounds[index + 1]
                if right and right - left >= TERRAIN_MIN_WIDTH then
                    local sliced = terrain_slice(platform, left, right)
                    if #sliced > 0 then
                        result[#result + 1] = {
                            left = left,
                            right = right,
                            y1 = sliced[1].y1,
                            y2 = sliced[#sliced].y2,
                            segments = sliced,
                            left_open = left <= platform.left,
                            right_open = right >= platform.right,
                        }
                    end
                end
            end
        end
    end
    return result
end

-- 平台物理边缘紧贴竖直墙时不能走出去。
local function terrain_close_edges(platform, walls)
    for _, wall in ipairs(walls) do
        if
            platform.left_open
            and wall.x >= platform.left - TERRAIN_DROP_MIN
            and wall.x <= platform.left + 3
            and terrain_wall_blocks(wall, platform, math.max(platform.left, wall.x))
        then
            platform.left_open = false
        end
        if
            platform.right_open
            and wall.x <= platform.right + TERRAIN_DROP_MIN
            and wall.x >= platform.right - 3
            and terrain_wall_blocks(wall, platform, math.min(platform.right, wall.x))
        then
            platform.right_open = false
        end
    end
end

local function terrain_connect(graph, ropes)
    local platforms, walls, edges = graph.platforms, graph.walls, graph.edges
    for index = 1, #platforms do
        edges[index] = {}
    end
    local min_x, max_x = graph.splice.min_x, graph.splice.max_x
    local function connect(from, to, kind, x, destination_x, rise, rope, cost)
        if from ~= to then
            edges[from][#edges[from] + 1] = {
                from = from,
                to = to,
                kind = kind,
                x = x,
                destination_x = destination_x,
                rise = rise,
                rope = rope,
                cost = cost,
            }
        end
    end
    for i, a in ipairs(platforms) do
        for j, b in ipairs(platforms) do
            if i ~= j then
                local direction = a.right <= b.left and 1 or -1
                local ax = direction == 1 and a.right or a.left
                local bx = direction == 1 and b.left or b.right
                local gap, rise = (bx - ax) * direction, terrain_height(a, ax) - terrain_height(b, bx)
                if gap >= 0 and gap <= 2 and math.abs(rise) <= 6 then
                    local from_x, to_x = terrain_inside(a, ax - direction * 8), terrain_inside(b, bx + direction * 14)
                    local from_y, to_y = terrain_height(a, from_x), terrain_height(b, to_x)
                    if
                        not terrain_crosses_wall(
                            walls,
                            ax,
                            bx,
                            math.min(from_y, to_y) - TERRAIN_BODY_HEIGHT,
                            math.max(from_y, to_y)
                        )
                    then
                        connect(i, j, "walk", from_x, to_x, rise, nil, 1)
                    end
                end
                -- 相邻窄台：起跳高度在跳跃可及范围内，靠短助跑保持水平惯性跳上。
                -- 水平间隙过大或跨越竖直墙的台阶链不生成。
                if gap > 2 and gap <= 40 and rise > 6 and rise <= TERRAIN_JUMP_RISE then
                    local from_x, to_x = terrain_inside(a, ax - direction * 6), terrain_inside(b, bx + direction * 10)
                    local from_y, to_y = terrain_height(a, from_x), terrain_height(b, to_x)
                    if
                        not terrain_crosses_wall(
                            walls,
                            ax,
                            bx,
                            math.min(from_y, to_y) - TERRAIN_BODY_HEIGHT,
                            math.max(from_y, to_y)
                        )
                    then
                        connect(i, j, "step", from_x, to_x, rise, nil, 4)
                    end
                end
            end
        end
        -- 落层：从平台物理边缘走出去，落点由起跳/走出瞬间的水平速度决定。
        for _, direction in ipairs({ -1, 1 }) do
            local open = direction == -1 and a.left_open or a.right_open
            if open then
                local edge_x = direction == -1 and a.left or a.right
                local window_left = direction == -1 and (edge_x - TERRAIN_DROP_MAX) or (edge_x + TERRAIN_DROP_MIN)
                local window_right = direction == -1 and (edge_x - TERRAIN_DROP_MIN) or (edge_x + TERRAIN_DROP_MAX)
                -- 地图原始边缘附近不生成落点，避免把角色送离地图。
                window_left = math.max(window_left, graph.left + 30)
                window_right = math.min(window_right, graph.right - 30)
                if min_x then window_left = math.max(window_left, min_x) end
                if max_x then window_right = math.min(window_right, max_x) end
                if window_right >= window_left then
                    local edge_y = terrain_height(a, edge_x)
                    for j, b in ipairs(platforms) do
                        if j ~= i then
                            local overlap_left, overlap_right =
                                math.max(window_left, b.left), math.min(window_right, b.right)
                            if overlap_right >= overlap_left then
                                local landing_x = (overlap_left + overlap_right) / 2
                                local landing_y = terrain_height(b, landing_x)
                                if
                                    landing_y > edge_y + 6
                                    and not terrain_crosses_wall(
                                        walls,
                                        edge_x,
                                        landing_x,
                                        landing_y - TERRAIN_BODY_HEIGHT,
                                        edge_y
                                    )
                                then
                                    connect(
                                        i,
                                        j,
                                        "drop",
                                        terrain_inside(a, edge_x - direction * 8),
                                        landing_x,
                                        landing_y - edge_y,
                                        nil,
                                        2
                                    )
                                end
                            end
                        end
                    end
                end
            end
        end
        -- 跳台上行：站在目标平台正下方原地起跳，落到正上方重叠的平台。
        for j, b in ipairs(platforms) do
            if i ~= j then
                local overlap_left, overlap_right = math.max(a.left, b.left), math.min(a.right, b.right)
                if overlap_right - overlap_left >= 10 then
                    local probe = (overlap_left + overlap_right) / 2
                    local rise = terrain_height(a, probe) - terrain_height(b, probe)
                    if rise > 6 and rise <= TERRAIN_JUMP_RISE then
                        local blocked = false
                        for _, wall in ipairs(walls) do
                            if
                                wall.x > overlap_left - TERRAIN_WALL_MARGIN
                                and wall.x < overlap_right + TERRAIN_WALL_MARGIN
                                and wall.top <= terrain_height(b, probe)
                                and wall.bottom >= terrain_height(a, probe) - TERRAIN_BODY_HEIGHT
                            then
                                blocked = true
                                break
                            end
                        end
                        if not blocked then
                            connect(i, j, "jumpup", terrain_inside(a, probe), terrain_inside(b, probe), rise, nil, 3)
                        end
                    end
                end
            end
        end
    end
    -- 绳索：与绳相交的每层平台都可以上下连接，绳底高于平台时按跳抓范围放宽。
    for _, rope in ipairs(ropes) do
        local touching = {}
        for i, platform in ipairs(platforms) do
            if rope.x >= platform.left and rope.x <= platform.right then
                local y = terrain_height(platform, rope.x)
                if y >= rope.y1 - 12 and y <= rope.y2 + TERRAIN_ROPE_GRAB then
                    touching[#touching + 1] = { index = i, y = y }
                end
            end
        end
        if #touching >= 2 then
            touching = terrain_sort(touching, function(a, b) return a.y < b.y end)
            local layers = {}
            for _, entry in ipairs(touching) do
                local last = layers[#layers]
                if last and math.abs(last.y - entry.y) <= 6 then
                    if entry.index < last.index then last.index = entry.index end
                else
                    layers[#layers + 1] = { index = entry.index, y = entry.y }
                end
            end
            for index = 1, #layers - 1 do
                local upper, lower = layers[index], layers[index + 1]
                connect(lower.index, upper.index, "rope", rope.x, rope.x, upper.y - lower.y, rope, 4)
                connect(upper.index, lower.index, "rope", rope.x, rope.x, lower.y - upper.y, rope, 4)
            end
        end
    end
end

local function terrain_build(data, options)
    options = options or {}
    local min_x, max_x = options.min_x, options.max_x
    local segments, terrain_left, terrain_right = {}, math.huge, -math.huge
    for _, foothold in ipairs(data.footholds or {}) do
        terrain_left = math.min(terrain_left, foothold.x1, foothold.x2)
        terrain_right = math.max(terrain_right, foothold.x1, foothold.x2)
        if foothold.x1 ~= foothold.x2 then
            local left, right = math.min(foothold.x1, foothold.x2), math.max(foothold.x1, foothold.x2)
            local y1, y2 = foothold.y1, foothold.y2
            if foothold.x1 > foothold.x2 then
                y1, y2 = y2, y1
            end
            local raw = { left = left, right = right, y1 = y1, y2 = y2 }
            if min_x then left = math.max(left, min_x) end
            if max_x then right = math.min(right, max_x) end
            if left < right then
                segments[#segments + 1] = {
                    id = foothold.id,
                    prev = foothold.prev,
                    next = foothold.next,
                    left = left,
                    right = right,
                    y1 = terrain_segment_height(raw, left),
                    y2 = terrain_segment_height(raw, right),
                }
            end
        end
    end
    local walls = terrain_walls(data.footholds or {})
    local platforms = terrain_split_platforms(terrain_merge_platforms(segments), walls)
    for _, platform in ipairs(platforms) do
        terrain_close_edges(platform, walls)
    end
    for index, platform in ipairs(platforms) do
        platform.index = index
    end
    local graph = {
        platforms = platforms,
        edges = {},
        walls = walls,
        left = terrain_left,
        right = terrain_right,
        splice = { min_x = min_x, max_x = max_x },
    }
    terrain_connect(graph, data.ropes or {})
    return graph
end

-- 平台图未覆盖但角色高度稳定时使用：取水平范围内高度最接近的平台。
local function terrain_nearest_platform(graph, x, y, max_distance)
    local selected, nearest = nil, max_distance or 100
    for _, platform in ipairs(graph.platforms) do
        if x >= platform.left - TERRAIN_WALL_MARGIN and x <= platform.right + TERRAIN_WALL_MARGIN then
            local distance = math.abs(terrain_height(platform, x) - y)
            if distance <= nearest then
                selected, nearest = platform, distance
            end
        end
    end
    return selected
end

local function terrain_platform_at(graph, x, y, tolerance)
    local selected, nearest = nil, tolerance
    for _, platform in ipairs(graph.platforms) do
        -- 角色可以站在平台边缘，身体半宽允许超出端点；墙切分留下的边界也在此范围。
        if x >= platform.left - TERRAIN_WALL_MARGIN and x <= platform.right + TERRAIN_WALL_MARGIN then
            local distance = math.abs(terrain_height(platform, x) - y)
            if distance <= nearest then
                selected, nearest = platform, distance
            end
        end
    end
    return selected
end

-- 从当前平台出发的最短代价搜索；返回距离表和父边表，供策略选择目标与边。
local function terrain_search(graph, from)
    local count = #graph.platforms
    local distances, parents, visited = { [from] = 0 }, {}, {}
    for _ = 1, count do
        local current, best = nil, math.huge
        for index = 1, count do
            local distance = distances[index]
            if distance and not visited[index] and distance < best then
                current, best = index, distance
            end
        end
        if not current then break end
        visited[current] = true
        for _, edge in ipairs(graph.edges[current]) do
            if not edge.blocked then
                local candidate = distances[current] + (edge.cost or 1)
                if distances[edge.to] == nil or candidate < distances[edge.to] then
                    distances[edge.to], parents[edge.to] = candidate, edge
                end
            end
        end
        if count > 64 and current % 32 == 0 then game.sleep(0) end
    end
    return distances, parents
end

local function terrain_plan(graph, from, goal)
    local distances, parents = terrain_search(graph, from)
    if distances[goal] == nil then return nil end
    local path, node = {}, goal
    while parents[node] do
        table.insert(path, 1, parents[node])
        node = parents[node].from
    end
    return path
end
