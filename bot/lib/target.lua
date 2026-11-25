-- One-shot scene navigation for follow's npc:, portal: and point: selectors.
local terrain = require("lib.terrain")
local move = require("lib.move")
local events = require("lib.io")

local function locate(ctx, world, nav, kind, name)
    local c = world.character
    local nearest, distance
    local function consider(entity)
        local dx, dy = entity.x - c.x, entity.y - c.y
        local d = dx * dx + dy * dy
        if not distance or d < distance then nearest, distance = entity, d end
    end
    if kind == "npc" then
        local npcs = ctx.game.scene.npcs
        if not npcs then return nil, "npcs_unavailable" end
        for _, npc in ipairs(npcs) do
            if (npc.name == name or (npc.template_id and npc.template_id == tonumber(name))) and npc.object_id
                and (not nav.object_id or nav.object_id == npc.object_id) then
                if npc.x == nil or npc.y == nil then return nil, "target_position_unknown" end
                consider(npc)
            end
        end
        if nearest then nav.object_id = nearest.object_id end
    elseif nav.point then
        return nav.point
    else
        -- Portal rows are exported from this client's `inspect map MAP`;
        -- named training points use the same map-scoped, read-only format.
        local file = io.open((ctx.state.bot_root or "/work/bot") .. "/targets.conf", "r")
        if not file then return nil, "targets_unavailable" end
        local key = ("%d:%s:%s"):format(world.map_id, kind, name)
        if kind == "portal" then
            if not ctx.scene.instance_id or not nav.generation then
                file:close()
                return nil, "scene_identity_unknown"
            end
            key = ("%d:%s:%d:portal:%s"):format(world.map_id, ctx.scene.instance_id, nav.generation, name)
        end
        for line in file:lines() do
            local id, value = line:match("^([^=]+)=(.*)$")
            if id == key then
                if nearest then file:close(); return nil, "ambiguous_target" end
                local x, y = value:match("^(%-?%d+),(%-?%d+)$")
                if not x then file:close(); return nil, "invalid_target_position" end
                consider({x = tonumber(x), y = tonumber(y)})
            end
        end
        file:close()
        nav.point = nearest
    end
    return nearest, nav.object_id and "target_disappeared" or "no_target"
end

local function selector(target)
    if not target then return end
    local kind, name = target:match("^(%a+):(.*)$")
    if kind == "npc" or kind == "portal" or kind == "point" then return kind, name end
end

local function step(ctx, world, nav, kind, name, ensure_mover)
    local memory, c = ctx.state, world.character
    if not world.map_id or not world.scene_generation then return "wait", "scene_identity_unknown" end
    if nav.generation ~= world.scene_generation or nav.map_id ~= world.map_id
        or nav.instance_id ~= ctx.scene.instance_id then return "wait", "scene_changed" end
    if not c or not c.x or not c.y then return "wait", "character_unavailable" end
    local goal, missing = locate(ctx, world, nav, kind, name)
    if not goal then return "wait", missing end
    local graph = memory.graph
    local to = terrain.platform_at(graph, goal.x, goal.y, graph.model.stand_height)
    nav.goal_platform, nav.goal_x, nav.goal_y = to, goal.x, goal.y
    if not to then return "wait", "target_platform_unknown" end
    local dx, dy = c.x - goal.x, c.y - goal.y
    -- Portal::bounds uses x +/-25 and y -100..+25. Never press up.
    local in_range
    if kind == "portal" then
        in_range = math.abs(dx) < 25 and dy > -100 and dy < 25
    else
        local radius = require("defaults").stop_distance
        in_range = dx * dx + dy * dy <= radius * radius
    end
    if c.on_ground == true and c.platform == to and in_range then return "arrived", "arrived" end
    if nav.to and nav.to ~= to then return "wait", "target_platform_changed" end
    if not nav.moving then
        if not c.platform or c.on_ground ~= true then return "wait", "character_platform_unknown" end
        if nav.to and c.platform ~= to then return "wait", "landing_mismatch" end
        local movement = ctx.game.character.movement
        if not movement or not movement.max_speed or not movement.max_jump_height then
            return "wait", "movement_unavailable"
        end
        local edges, reason = terrain.plan(graph, c.platform, to, {speed = movement.max_speed,
            max_jump_height = movement.max_jump_height, blocked = memory.blocked})
        if not edges or (#edges == 0 and c.platform ~= to) then return "wait", reason or "no_path" end
        if c.platform == to then
            edges = {{kind = "walk", from = to, to = to, x = c.x, destination = goal.x, rise = 0}}
        end
        local mover = ensure_mover()
        if not mover then return "wait", "mover_unavailable" end
        local ok, err = move.set_path(mover, edges)
        if not ok then return "wait", err end
        nav.to, nav.moving, nav.final_walk = to, true, c.platform == to
        events.event(ctx, "target/plan", {target = memory.bot.target, scene_generation = nav.generation,
            from = c.platform, to = to, x = c.x, y = c.y, target_x = goal.x, target_y = goal.y, edges = edges})
    end
    local index = memory.mover.index
    local status, reason = move.step(memory.mover, ctx, world)
    if memory.mover.index ~= index then
        events.event(ctx, "target/edge", {target = memory.bot.target, edge = memory.mover.edges[index],
            platform = c.platform, x = c.x, y = c.y, elapsed = world.now - nav.started, status = status,
            vx = ctx.game.character.velocity and ctx.game.character.velocity.x})
    end
    if status == "failed" then return "wait", reason end
    if status == "done" then
        if nav.final_walk then
            if not c.on_ground and in_range then
                nav.settle_since = nav.settle_since or world.now
                if world.now - nav.settle_since < 1 then return "moving" end
            end
            return "wait", "outside_interaction_range"
        end
        nav.moving = false -- verify landing, then plan the walk on the destination platform
    end
    return "moving"
end

return {selector = selector, step = step}
