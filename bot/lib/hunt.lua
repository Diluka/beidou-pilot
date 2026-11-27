-- Incremental platform coverage. The caller owns the mover and interrupts this
-- controller before combat or loot takes the action slot.
local terrain = require("lib.terrain")
local move = require("lib.move")
local io_module = require("lib.io")
local M = {}

function M.step(ctx, world, graph, mover)
    local memory, character, now = ctx.state, world.character, ctx.tick.time
    local scope = tostring(world.map_id) .. ":" .. tostring(world.scene_generation)
    local patrol = memory.hunt_patrol
    if not patrol or patrol.scope ~= scope then
        patrol = {scope = scope, visited = {}, skipped = {}, index = 1}
        memory.hunt_patrol = patrol
    end
    if patrol.target and mover.status == "running" and not character.on_ground then
        return move.step(mover, ctx, world)
    end
    if not character.on_ground or not character.platform then return "waiting", "platform_unknown" end
    if not patrol.order then
        local adjacent, seen, order = {}, {[character.platform] = true}, {character.platform}
        for kind, values in pairs(graph.candidates) do
            local width = kind == "rope" and 6 or 5
            for i = 1, #values, width do
                local from, to = values[i], values[i + 1]
                adjacent[from] = adjacent[from] or {}
                adjacent[from][#adjacent[from] + 1] = to
            end
        end
        for _, neighbors in pairs(adjacent) do table.sort(neighbors) end
        local cursor = 1
        while cursor <= #order do
            for _, to in ipairs(adjacent[order[cursor]] or {}) do
                if not seen[to] then seen[to] = true; order[#order + 1] = to end
            end
            cursor = cursor + 1
        end
        -- Derived edges are checked by plan, not represented by the static candidates.
        for index in ipairs(graph.platforms) do if not seen[index] then order[#order + 1] = index end end
        patrol.order = order
    end
    if patrol.wait_until then
        if now < patrol.wait_until then return "waiting", "refresh" end
        patrol.visited, patrol.index, patrol.wait_until = {}, 1, nil
    end
    if patrol.target then
        if character.platform == patrol.target then
            if mover.status == "running" then move.stop(mover) end
            patrol.visited[patrol.target] = true
            io_module.event(ctx, "hunt/platform", {platform = patrol.target, map_id = world.map_id})
            patrol.target, patrol.failures, patrol.route_started = nil, nil, nil
            return "waiting", "arrived"
        end
        local edge = mover.status == "running" and mover.edges and mover.edges[mover.index or 1]
        if edge and character.platform ~= edge.from and character.platform ~= edge.to then
            move.stop(mover)
            io_module.event(ctx, "hunt/recover", {from = character.platform, to = patrol.target, reason = "displaced"})
        end
        if mover.status == "running" then
            local status, reason = move.step(mover, ctx, world)
            if status == "running" then return status, reason end
            if status == "failed" then
                patrol.failures = (patrol.failures or 0) + 1
                if patrol.failures >= 2 then
                    io_module.event(ctx, "hunt/skip", {from = character.platform, to = patrol.target, reason = reason})
                    patrol.skipped[patrol.target], patrol.target, patrol.failures = true, nil, nil
                    return "waiting", reason
                end
                io_module.event(ctx, "hunt/recover", {from = character.platform, to = patrol.target, reason = reason})
            end
        end
        -- A knockback or failed edge invalidates the old route; replan on the next tick.
        patrol.recovering = patrol.route_started or nil
    else
        patrol.visited[character.platform] = true
        local target
        while patrol.index <= #patrol.order do
            local index = patrol.order[patrol.index]
            patrol.index = patrol.index + 1
            if not patrol.visited[index] and not patrol.skipped[index] then target = index; break end
        end
        if not target then
            patrol.wait_until = now + 5
            io_module.event(ctx, "hunt/cycle", {map_id = world.map_id})
            return "waiting", "refresh"
        end
        patrol.target = target
    end
    local from, target = character.platform, patrol.target
    if patrol.last_plan and now - patrol.last_plan < (patrol.slow_plan and 5 or 1) then
        return "waiting", "plan_throttled"
    end
    patrol.last_plan = now
    local clock = os and os.clock
    local started = clock and clock()
    local path, reason = terrain.plan(graph, from, target, {blocked = memory.blocked or {}})
    local elapsed = started and (clock() - started) * 1000
    if elapsed and elapsed > 5 then patrol.slow_plan = true end
    if not path or #path == 0 then
        if not patrol.skipped[target] then
            io_module.event(ctx, "hunt/skip", {from = from, to = target, reason = reason or "no_path", plan_ms = elapsed})
        end
        patrol.skipped[target], patrol.target, patrol.recovering, patrol.route_started = true, nil, nil, nil
        return "waiting", reason or "no_path"
    end
    local ok, err = move.set_path(mover, path)
    if not ok then
        io_module.event(ctx, "hunt/skip", {from = from, to = target, reason = err})
        patrol.skipped[target], patrol.target, patrol.recovering, patrol.route_started = true, nil, nil, nil
        return "waiting", err
    end
    if patrol.recovering then
        io_module.event(ctx, "hunt/recover", {from = from, to = target, reason = "replanned"})
    end
    io_module.event(ctx, "hunt/patrol", {from = from, to = target, edges = #path, plan_ms = elapsed})
    patrol.recovering, patrol.route_started = nil, true
    return "running", "planned"
end

return M
