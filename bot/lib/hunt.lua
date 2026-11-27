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
        patrol = {scope = scope, visited = {}, skipped = {}, attempts = {}, index = 1}
        memory.hunt_patrol = patrol
    end
    if patrol.target and mover.status == "running" and not character.on_ground then
        return move.step(mover, ctx, world)
    end
    if not character.on_ground or not character.platform then return "waiting", "platform_unknown" end
    if not patrol.fallback_until and (memory.hunt_failures or 0) >= 3 then
        if mover.status == "running" then move.stop(mover) end
        patrol.fallback_until = now + 30
        io_module.event(ctx, "hunt/fallback", {platform = character.platform, reason = "move_failures"})
    end
    if patrol.fallback_until then
        if now < patrol.fallback_until then
            local platform = graph.platforms[character.platform]
            local observed = ctx.game.character or {}
            local direction = math.floor(now / 5) % 2 == 0 and "right" or "left"
            local safe = platform and character.x and (direction == "right" and character.x < platform.right - 40
                or direction == "left" and character.x > platform.left + 40)
            if safe and observed.action_idle and not observed.attacking then
                ctx.game.player.move(direction)
            else
                ctx.game.player.move(nil)
            end
            return "waiting", "fallback"
        end
        ctx.game.player.move(nil)
        patrol.fallback_until, memory.hunt_failures = nil, 0
    end
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
        patrol.visited, patrol.index, patrol.wait_until, patrol.order, patrol.arrivals = {}, 1, nil, nil, 0
        return "waiting", "refresh_complete"
    end
    local config = world.config or memory.bot and memory.bot.config or {}
    local function narrow(index)
        local platform = graph.platforms[index]
        -- Reserve min_range plus 60px for spacing and turning.
        return (config.attack_mode or "melee") ~= "melee" and platform
            and platform.right - platform.left < (tonumber(config.min_range) or 60) + 60
    end
    local function skip_narrow(index)
        if not patrol.skipped[index] then
            io_module.event(ctx, "hunt/skip", {platform = index, reason = "narrow_platform"})
            patrol.skipped[index] = true
        end
    end
    if patrol.target and narrow(patrol.target) then
        if mover.status == "running" then move.stop(mover) end
        skip_narrow(patrol.target)
        patrol.target, patrol.route_started = nil, nil
    end
    if narrow(character.platform) then skip_narrow(character.platform) end
    if patrol.target then
        if character.platform == patrol.target then
            if mover.status == "running" then move.stop(mover) end
            patrol.visited[patrol.target] = true
            patrol.arrivals, memory.hunt_failures = (patrol.arrivals or 0) + 1, 0
            io_module.event(ctx, "hunt/platform", {platform = patrol.target, map_id = world.map_id})
            patrol.target, patrol.failures, patrol.route_started = nil, nil, nil
            return "waiting", "arrived"
        end
        local edge = mover.status == "running" and mover.edges and mover.edges[mover.index or 1]
        if edge and character.platform ~= edge.from and character.platform ~= edge.to then
            move.stop(mover)
            io_module.event(ctx, "hunt/recover", {from = character.platform, to = patrol.target, reason = "displaced"})
        end
        local status, reason = mover.status, mover.reason
        if status == "running" then status, reason = move.step(mover, ctx, world) end
        if status == "running" then return status, reason end
        if status == "failed" then
            local failed = mover.edges and mover.edges[mover.index or 1]
            local structural = reason == "no_path" or reason == "unsupported_edge"
                or reason == "invalid_edge" or reason == "character_unavailable"
            if structural and failed and failed.from and failed.to and failed.from ~= failed.to then
                memory.blocked = memory.blocked or {}
                memory.blocked[tostring(failed.from) .. ":" .. tostring(failed.to)] = true
            end
            local target = patrol.target
            patrol.attempts[target] = (patrol.attempts[target] or 0) + 1
            local attempts = patrol.attempts[target]
            local detail = {from = character.platform, to = target, reason = reason, attempts = attempts,
                edge_kind = failed and failed.kind, edge_from = failed and failed.from,
                edge_to = failed and failed.to, edge_x = failed and failed.x}
            mover.status = "done"
            if structural or attempts >= 3 then
                io_module.event(ctx, "hunt/skip", detail)
                patrol.skipped[target], patrol.target, patrol.route_started = true, nil, nil
                return "waiting", reason
            end
            detail.next_attempt = attempts + 1
            io_module.event(ctx, "hunt/retry", detail)
            patrol.fallback_until = now + 30
            io_module.event(ctx, "hunt/fallback", {platform = character.platform, reason = reason, attempts = attempts})
            return "waiting", "fallback"
        end
        -- A knockback or failed edge invalidates the old route; replan on the next tick.
        patrol.recovering = patrol.route_started or nil
    else
        patrol.visited[character.platform] = true
        local target
        while patrol.index <= #patrol.order do
            local index = patrol.order[patrol.index]
            patrol.index = patrol.index + 1
            if narrow(index) then skip_narrow(index) end
            if not patrol.visited[index] and not patrol.skipped[index] then target = index; break end
        end
        if not target then
            local remaining, skipped = false, false
            for index in ipairs(graph.platforms) do
                if index ~= character.platform then
                    if patrol.skipped[index] then skipped = true else remaining = true end
                end
            end
            io_module.event(ctx, "hunt/cycle", {map_id = world.map_id, arrivals = patrol.arrivals or 0})
            if skipped and not remaining then
                patrol.fallback_until = math.huge
                io_module.event(ctx, "hunt/fallback", {platform = character.platform, reason = "targets_exhausted"})
                return "waiting", "fallback"
            end
            patrol.wait_until = now + ((patrol.arrivals or 0) > 0 and 5 or 30)
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
        if reason == "no_path" and from ~= target then
            memory.blocked = memory.blocked or {}
            memory.blocked[tostring(from) .. ":" .. tostring(target)] = true
        end
        if not patrol.skipped[target] then
            io_module.event(ctx, "hunt/skip", {from = from, to = target, reason = reason or "no_path",
                attempts = patrol.attempts[target] or 0, plan_ms = elapsed})
        end
        patrol.skipped[target], patrol.target, patrol.recovering, patrol.route_started, patrol.failures = true, nil, nil, nil, nil
        return "waiting", reason or "no_path"
    end
    local ok, err = move.set_path(mover, path)
    if not ok then
        io_module.event(ctx, "hunt/skip", {from = from, to = target, reason = err,
            attempts = patrol.attempts[target] or 0})
        patrol.skipped[target], patrol.target, patrol.recovering, patrol.route_started, patrol.failures = true, nil, nil, nil, nil
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
