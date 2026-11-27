-- @tick.gear 2
-- @tick.budget_ms 100
--
-- 在当前位置所在场景内计算安全平台，并移动到最近的玩家可达安全平台。
-- 安全定义与宿主工具 tools/safe_platforms.py 一致：平台内没有当前怪物，
-- 且怪物从这些平台出发只能同平台行走或向下掉落，无法到达目标平台。
-- 本脚本使用场景中的当前怪物位置（不是静态刷怪点）；刷怪点分析请用宿主
-- 工具 safe_platforms.py。脚本到达安全平台或确认当前平台安全后结束。

local terrain = require("lib.terrain")
local move = require("lib.move")

local function height_at(platform, x)
    x = math.max(platform.left, math.min(platform.right, x))
    local segments = platform.segments
    for index = 1, #segments, 4 do
        local left, right, y1, y2 = segments[index], segments[index + 1], segments[index + 2], segments[index + 3]
        if x <= right then
            if right == left then return y1 end
            return y1 + (x - left) / (right - left) * (y2 - y1)
        end
    end
    local count = #segments
    local left, right, y1, y2 = segments[count - 3], segments[count - 2], segments[count - 1], segments[count]
    if right == left then return y1 end
    return y1 + (x - left) / (right - left) * (y2 - y1)
end

local function drops_to(source, target, model)
    local overlap_left = math.max(source.left, target.left)
    local overlap_right = math.min(source.right, target.right)
    if overlap_right > overlap_left then
        for _, x in ipairs({source.left, source.right}) do
            if x >= target.left and x <= target.right
                and height_at(source, x) - height_at(target, x) < -model.drop_min then
                return true
            end
        end
        if overlap_right - overlap_left >= 10 then
            local x = (overlap_left + overlap_right) / 2
            return height_at(source, x) - height_at(target, x) < -model.drop_min
        end
        return false
    end
    local gap, source_x, target_x
    if source.right < target.left then
        gap, source_x, target_x = target.left - source.right, source.right - 8, target.left + 8
    elseif target.right < source.left then
        gap, source_x, target_x = source.left - target.right, source.left + 8, target.right - 8
    else
        gap, source_x, target_x = 0, source.right, target.left
    end
    return gap <= model.drop_max and height_at(source, source_x) - height_at(target, target_x) < -model.drop_min
end

local function drop_adjacency(graph)
    local adjacency = {}
    for from, source in ipairs(graph.platforms) do
        adjacency[from] = {}
        for to, target in ipairs(graph.platforms) do
            if from ~= to and drops_to(source, target, graph.model) then
                adjacency[from][#adjacency[from] + 1] = to
            end
        end
    end
    return adjacency
end

local function monster_spawns(graph, scene)
    local spawns = {}
    for _, monster in ipairs(scene and scene.monsters or {}) do
        if type(monster.x) == "number" and type(monster.y) == "number" then
            local platform = terrain.platform_at(graph, monster.x, monster.y, graph.model.stand_height)
            if platform then spawns[platform] = true end
        end
    end
    return spawns
end

local function monster_reachable(spawns, adjacency)
    local reachable, queue = {}, {}
    for platform in pairs(spawns) do
        reachable[platform] = true
        queue[#queue + 1] = platform
    end
    local cursor = 1
    while cursor <= #queue do
        local platform = queue[cursor]
        cursor = cursor + 1
        for _, target in ipairs(adjacency[platform] or {}) do
            if not reachable[target] then
                reachable[target] = true
                queue[#queue + 1] = target
            end
        end
    end
    return reachable
end

local function safe_platform_list(graph, scene)
    local spawns = monster_spawns(graph, scene)
    local reachable = monster_reachable(spawns, drop_adjacency(graph))
    local safe = {}
    for _, platform in ipairs(graph.platforms) do
        if not reachable[platform.index] then safe[#safe + 1] = platform.index end
    end
    return safe
end

local function center(platform)
    return (platform.left + platform.right) / 2
end

local function plan_to(graph, context, from, targets)
    local character = context.game and context.game.character or {}
    local movement = type(character.movement) == "table" and character.movement or {}
    local movement_model = type(movement.model) == "table" and movement.model or {}
    local speed = movement.max_speed or movement_model.max_speed or 100
    local max_jump = movement.max_jump_height or movement_model.max_jump_height or graph.model.jump_rise
    local ordered = {}
    for _, target in ipairs(targets) do
        ordered[#ordered + 1] = {
            target = target,
            distance = math.abs(center(graph.platforms[target]) - character.x),
        }
    end
    table.sort(ordered, function(left, right) return left.distance < right.distance end)
    for _, item in ipairs(ordered) do
        local path = terrain.plan(graph, from, item.target, {speed = speed, max_jump_height = max_jump})
        if path then return item.target, path end
    end
end

local function world_character(context)
    local character = context.game and context.game.character or {}
    local physics = character.physics or {}
    local on_ground = character.on_ground
    if on_ground == nil then on_ground = physics.on_ground end
    return {x = character.x, y = character.y, on_ground = on_ground}
end

local function log_info(message)
    if game and game.log then game.log("safe_spot:" .. message) end
end

local function main(context)
    local scene = context.scene
    local terrain_scene = scene and scene.terrain
    if not terrain_scene or terrain_scene.status ~= "available" then return end
    if not context.game or type(context.game.scene) ~= "table" or type(context.game.scene.monsters) ~= "table" then
        return
    end
    local character = context.game and context.game.character
    if not character or type(character.x) ~= "number" or type(character.y) ~= "number" then return end

    local memory = context.state
    local generation = scene.scene_generation
    if memory.safe_spot_generation ~= generation then
        memory.safe_spot_generation = generation
        memory.safe_spot_graph = nil
        memory.safe_spot_mover = nil
        memory.safe_spot_safe = nil
        memory.safe_spot_reported = nil
        memory.safe_spot_status = nil
    end
    if not memory.safe_spot_graph then
        local graph = terrain.build(terrain_scene.navigation)
        if not graph then return end
        memory.safe_spot_graph = graph
        memory.safe_spot_safe = nil
    end
    local graph = memory.safe_spot_graph

    if memory.safe_spot_status == "moving" and memory.safe_spot_mover then
        local status, reason = move.step(memory.safe_spot_mover, context, {character = world_character(context)})
        if status == "running" then return end
        memory.safe_spot_mover = nil
        if status == "failed" then
            local platform = graph.platforms[memory.safe_spot_target]
            log_info(string.format("move_failed target=%d center=%.1f,%.1f reason=%s",
                memory.safe_spot_target, center(platform), height_at(platform, center(platform)), tostring(reason)))
            return "failed"
        end
        log_info(string.format("arrived platform=%d x=%.1f y=%.1f", memory.safe_spot_target, character.x, character.y))
        return "done"
    end

    local current = terrain.platform_at(graph, character.x, character.y, graph.model.stand_height)
    if not current then return end
    if memory.safe_spot_safe == nil or memory.safe_spot_current ~= current then
        memory.safe_spot_safe = safe_platform_list(graph, context.game.scene)
        memory.safe_spot_current = current
    end
    local safe = memory.safe_spot_safe
    local current_safe = false
    for _, platform in ipairs(safe) do
        if platform == current then
            current_safe = true
            break
        end
    end
    if current_safe then
        if not memory.safe_spot_reported then
            log_info(string.format("already_safe platform=%d x=%.1f y=%.1f", current, character.x, character.y))
            memory.safe_spot_reported = true
        end
        return "done"
    end

    local target, path = plan_to(graph, context, current, safe)
    if not target then
        log_info("no_safe_platform reachable from=" .. tostring(current))
        return "done"
    end
    local mover = move.new(graph)
    local set, set_error = move.set_path(mover, path)
    if not set then
        log_info("set_path_failed reason=" .. tostring(set_error))
        return "failed"
    end
    memory.safe_spot_mover = mover
    memory.safe_spot_target = target
    memory.safe_spot_status = "moving"
    local platform = graph.platforms[target]
    log_info(string.format("moving from=%d to=%d target_x=%.1f target_y=%.1f edges=%d", current, target,
        center(platform), height_at(platform, center(platform)), #path))
    return nil
end
