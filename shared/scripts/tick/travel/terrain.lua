-- tick 旅行脚本包：静态导航拓扑适配层。
--
-- 消费 context.scene.terrain.navigation：原生共享 C++ 在稳定场景读取时按客户端
-- 导航模型常量派生 platforms/walls/ropes/candidates（候选为 walk/step/jumpup/drop
-- 每 5 个数 from,to,x,destination,rise，rope 每 6 个数追加 rope_index 的扁平数组）。
-- 本模块只按角色当前有效运动能力过滤候选、生成可执行边与相对代价、按场景代次
-- 缓存平台图并做最短路，不重建平台图，也不写任何 player/game 动作。
local terrain = {}

-- 候选关系已按客户端导航模型常量派生（jump_rise=75 等）；这里只用角色当前有效
-- 跳高复核可执行性，并留出保守余量，不重新推导几何。
local JUMP_MARGIN = 4
-- 边的相对代价只用于最短路比较，不表示真实耗时；沿用已验证的单图执行器数值。
local EDGE_COST = { walk = 1, drop = 2, jumpup = 3, step = 4, rope = 4 }
-- 候选扁平数组的步长与字段：from,to,x,destination,rise[,rope_index]。
local CANDIDATE_KINDS = {
    { name = "walk", stride = 5 },
    { name = "step", stride = 5 },
    { name = "jumpup", stride = 5 },
    { name = "drop", stride = 5 },
    { name = "rope", stride = 6 },
}
-- navigation.model.wall_margin 缺失时的保守值（客户端导航模型常量为 12）。
local DEFAULT_WALL_MARGIN = 12

local function finite(value)
    return type(value) == "number" and value == value and value ~= math.huge and value ~= -math.huge
end

-- 平台在 x 处的地面高度；segments 是每 4 个数 left,right,y1,y2 的扁平数组，
-- 段内按线性插值，与原生 PlatformHeight 语义一致。
function terrain.platform_height(platform, x)
    local segments = platform.segments
    if type(segments) ~= "table" then return nil end
    local count = #segments
    if count < 4 then return nil end
    local index = 1
    while index + 3 <= count do
        local left, right = segments[index], segments[index + 1]
        local y1, y2 = segments[index + 2], segments[index + 3]
        if x <= right then
            if right == left then return y1 end
            return y1 + (y2 - y1) * (x - left) / (right - left)
        end
        index = index + 4
    end
    local left, right = segments[count - 3], segments[count - 2]
    local y1, y2 = segments[count - 1], segments[count]
    if right == left then return y1 end
    return y1 + (y2 - y1) * (x - left) / (right - left)
end

function terrain.platform_inside(platform, x)
    if x < platform.left then return platform.left end
    if x > platform.right then return platform.right end
    return x
end

-- 角色当前有效跳高参考：优先 context.game.character.movement.max_jump_height，
-- 缺失时回退到同一份静态导航模型常量（不是另一后端或静态模板）。
local function jump_reference(navigation, movement)
    if type(movement) == "table" then
        local height = movement.max_jump_height
        if finite(height) and height > 0 then return height, "character" end
    end
    local model = navigation.model
    if type(model) == "table" and finite(model.jump_rise) and model.jump_rise > 0 then
        return model.jump_rise, "model"
    end
    return nil, "unknown"
end

local function rope_lookup(navigation)
    local lookup = {}
    if type(navigation.ropes) ~= "table" then return lookup end
    for _, rope in ipairs(navigation.ropes) do
        if type(rope) == "table" and finite(rope.index) then lookup[rope.index] = rope end
    end
    return lookup
end

-- 绳各层平台高度：rope.platforms 是每 2 个数「平台 index, 该平台在绳 x 处高度」。
local function rope_layer_height(rope, platform_index)
    if type(rope) ~= "table" or type(rope.platforms) ~= "table" then return nil end
    local layers = rope.platforms
    for index = 1, #layers - 1, 2 do
        if layers[index] == platform_index then return layers[index + 1] end
    end
    return nil
end

-- 绳索向上攀爬且起点平台在绳底之下时，需要先跳起抓绳；所需跳高不得超过角色跳高。
local function rope_edge_allowed(rope, platform_index, jump_height)
    if type(rope) ~= "table" then return true end
    local source_y = rope_layer_height(rope, platform_index)
    if not finite(source_y) or not finite(rope.y2) then return true end
    local bottom = rope.y2
    if source_y <= bottom then return true end
    if not finite(jump_height) then return true end
    return source_y - bottom <= jump_height
end

local function add_edge(graph, kind, from, to, x, destination, rise, climb, rope_index)
    local edges = graph.edges[from]
    if edges == nil then return end
    edges[#edges + 1] = {
        kind = kind,
        from = from,
        to = to,
        x = x,
        destination = destination,
        rise = rise,
        climb = climb,
        cost = EDGE_COST[kind] or 1,
        rope = rope_index,
        rope_x = kind == "rope" and x or nil,
    }
    graph.edge_count = graph.edge_count + 1
end

-- 用原生候选关系生成可执行边。walk 不需要能力；step/jumpup 的上行高度必须
-- 在角色有效跳高内；drop 只接受确实向下的落层；rope 上行只复核抓绳起跳高度。
local function build_edges(graph, navigation, jump_height, jump_limit)
    local candidates = navigation.candidates
    if type(candidates) ~= "table" then return end
    local platforms = graph.platforms
    local count = #platforms
    local ropes = rope_lookup(navigation)
    for _, kind in ipairs(CANDIDATE_KINDS) do
        local values = candidates[kind.name]
        if type(values) == "table" then
            local stride = kind.stride
            for index = 1, #values - stride + 1, stride do
                local from, to = values[index], values[index + 1]
                if
                    finite(from)
                    and finite(to)
                    and from % 1 == 0
                    and to % 1 == 0
                    and from >= 1
                    and from <= count
                    and to >= 1
                    and to <= count
                    and from ~= to
                then
                    local x, destination, rise = values[index + 2], values[index + 3], values[index + 4]
                    local rope_index = stride == 6 and values[index + 5] or nil
                    if finite(x) and finite(destination) then
                        local from_platform, to_platform = platforms[from], platforms[to]
                        local from_height = terrain.platform_height(from_platform, x)
                        local to_height = terrain.platform_height(to_platform, destination)
                        if finite(from_height) and finite(to_height) then
                            -- 正数表示目标平台更高（地图像素 y 向下为正）。
                            local climb = from_height - to_height
                            local allowed = true
                            if kind.name == "step" or kind.name == "jumpup" then
                                -- step/jumpup 的候选 rise 是源减目标高度（正数上行）。
                                local up = finite(rise) and rise or climb
                                allowed = jump_limit ~= nil and up > 0 and up <= jump_limit
                            elseif kind.name == "drop" then
                                -- 共享 C++ 的 drop 候选 rise 是目标减源高度（正数下行），
                                -- 与 docs/LUA_TICK_API.md 的「源减目标」表述不一致；
                                -- 这里以已核对的 C++/合同测试语义为准，文档差异见交付报告。
                                local fall = finite(rise) and rise or -climb
                                allowed = fall > 6
                            elseif kind.name == "rope" then
                                -- rope 的候选 rise 是目标减源高度：负数表示沿绳向上。
                                local upward = finite(rise) and rise < 0 or to_height < from_height
                                if upward then
                                    local rope = rope_index and ropes[rope_index] or nil
                                    allowed = rope_edge_allowed(rope, from, jump_height)
                                end
                            end
                            if allowed then
                                add_edge(graph, kind.name, from, to, x, destination, rise, climb, rope_index)
                            end
                        end
                    end
                end
            end
        end
    end
end

-- 纯函数：由 navigation 与角色运动能力生成平台图。generation/map_id 由 ensure 写入。
function terrain.build(navigation, movement)
    local platforms = type(navigation.platforms) == "table" and navigation.platforms or {}
    local jump_height, jump_source = jump_reference(navigation, movement)
    local model = type(navigation.model) == "table" and navigation.model or {}
    local graph = {
        platforms = platforms,
        edges = {},
        edge_count = 0,
        model = model,
        wall_margin = finite(model.wall_margin) and model.wall_margin or DEFAULT_WALL_MARGIN,
        jump_height = jump_height,
        jump_source = jump_source,
        jump_limit = jump_height ~= nil and math.max(1, jump_height - JUMP_MARGIN) or nil,
    }
    for index = 1, #platforms do
        graph.edges[index] = {}
    end
    build_edges(graph, navigation, jump_height, graph.jump_limit)
    return graph
end

-- 运行期禁边键；同一条边在不同代次重新生成时仍可对应（代次变化会清空 blocked）。
function terrain.edge_key(edge)
    return string.format("%d>%d:%s:%.1f:%.1f", edge.from, edge.to, edge.kind, edge.x, edge.destination)
end

local function search(graph, from, blocked)
    local count = #graph.platforms
    local distances, parents, visited = { [from] = 0 }, {}, {}
    for _ = 1, count do
        local current, best = nil, math.huge
        for index = 1, count do
            local distance = distances[index]
            if distance ~= nil and not visited[index] and distance < best then
                current, best = index, distance
            end
        end
        if current == nil then break end
        visited[current] = true
        for _, edge in ipairs(graph.edges[current] or {}) do
            if blocked == nil or not blocked[terrain.edge_key(edge)] then
                local candidate = distances[current] + edge.cost
                if distances[edge.to] == nil or candidate < distances[edge.to] then
                    distances[edge.to], parents[edge.to] = candidate, edge
                end
            end
        end
    end
    return distances, parents
end

-- 最短路：返回从 from 平台到 target 平台的可执行边数组；没有路径返回 nil。
-- blocked 是 state.loco 维护的运行期禁边表（边键 -> true）。
function terrain.plan(graph, from, target, blocked)
    if from == target then return {} end
    local distances, parents = search(graph, from, blocked)
    if distances[target] == nil then return nil end
    local path, node = {}, target
    while node ~= from do
        local edge = parents[node]
        if edge == nil then return nil end
        table.insert(path, 1, edge)
        node = edge.from
    end
    return path
end

-- 角色所在平台：x 在平台水平范围（允许角色半宽与墙切分余量）内且高度差在容差内。
function terrain.platform_at(graph, x, y, tolerance)
    if not finite(x) or not finite(y) then return nil end
    local margin = graph.wall_margin or DEFAULT_WALL_MARGIN
    local nearest = tolerance or 25
    local selected = nil
    for _, platform in ipairs(graph.platforms) do
        if x >= platform.left - margin and x <= platform.right + margin then
            local height = terrain.platform_height(platform, x)
            if finite(height) then
                local distance = math.abs(height - y)
                if distance <= nearest then
                    selected, nearest = platform, distance
                end
            end
        end
    end
    return selected
end

-- 平台定位兜底：目标坐标落在平台边缘/墙切分残段附近时按高度差取最近平台。
function terrain.nearest_platform(graph, x, y, max_distance)
    return terrain.platform_at(graph, x, y, max_distance or 120)
end

-- 按 scene_generation + map_id 缓存平台图；场景代次变化后自动重建。
-- 返回值：graph；或 nil, "scene_pending"；或 nil, "terrain_unavailable", 明细。
function terrain.ensure(context)
    local scene = context.scene
    local data = scene and scene.terrain
    if type(data) ~= "table" then return nil, "scene_pending" end
    if data.status ~= "available" then
        -- 转场期间的不可用是预期状态：等首次稳定帧重新读取本图。
        if data.status == "unavailable" and data.error == "scene_transition" then return nil, "scene_pending" end
        local detail = data.error or data.message or data.status
        return nil, "terrain_unavailable", tostring(detail)
    end
    local generation = scene.scene_generation
    local map_id = scene.map_id
    local state = context.state
    local cached = state.terrain_cache
    if type(cached) == "table" and cached.generation == generation and cached.map_id == map_id and cached.graph then
        return cached.graph
    end
    local navigation = data.navigation
    if type(navigation) ~= "table" or type(navigation.platforms) ~= "table" or type(navigation.model) ~= "table" then
        return nil, "terrain_unavailable", "navigation_missing"
    end
    local character = context.game.character
    local graph = terrain.build(navigation, character and character.movement)
    graph.generation = generation
    graph.map_id = map_id
    state.terrain_cache = { generation = generation, map_id = map_id, graph = graph }
    context.game.log(
        string.format(
            "travel_terrain map=%s generation=%s platforms=%d edges=%d jump=%s(%s) source=%s",
            tostring(map_id),
            tostring(generation),
            #graph.platforms,
            graph.edge_count,
            graph.jump_height ~= nil and string.format("%.1f", graph.jump_height) or "unknown",
            graph.jump_source,
            tostring(data.source)
        )
    )
    return graph
end

function terrain.cached(state)
    local cached = state.terrain_cache
    if type(cached) == "table" then return cached.graph end
    return nil
end

return terrain
