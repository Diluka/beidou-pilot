local terrain = require("lib.terrain")
local move = require("lib.move")
local M = {}

function M.load_route(path)
    local file = io.open(path, "r")
    if not file then return nil end
    local text = file:read("*a")
    file:close()
    local goal = tonumber(text:match('"goal"%s*:%s*(%d+)'))
    local legs = {}
    for map, portal, x, y in text:gmatch('"map"%s*:%s*(%d+),%s*"portal"%s*:%s*"([^"]*)",%s*"x"%s*:%s*(-?%d+%.?%d*),%s*"y"%s*:%s*(-?%d+%.?%d*)') do
        legs[#legs + 1] = {map = tonumber(map), portal = portal, x = tonumber(x), y = tonumber(y)}
    end
    local count = 0
    for _ in text:gmatch('"map"%s*:') do count = count + 1 end
    local start = tonumber(text:match('"from"%s*:%s*(%d+)'))
    if #legs == 0 or #legs ~= count or not goal or start ~= legs[1].map then return nil end
    return legs, goal
end

function M.new(legs, goal)
    return {legs = legs, goal = goal, index = 1}
end

function M.stop(s, context)
    context.game.player.stop()
    s.graph, s.mover, s.path, s.portal_wait, s.platform_wait, s.generation, s.blocked = nil, nil, nil, nil, nil, nil, nil
end

-- Route state is owned by the caller and persists across ticks.
function M.step(s, context, world)
    local p = context.game.player
    local function fail(reason)
        p.stop()
        context.game.log("travel failed: " .. reason)
        return "failed", reason, {kind = "failed", reason = reason, index = s.index}
    end
    s.index = s.index or 1
    local leg = s.legs[s.index]
    if not leg then p.stop(); context.game.log("route complete"); return "done", nil, {kind = "done", index = s.index} end
    if not world.ready or not world.character or world.map_id == nil then
        return fail("world_unavailable")
    end
    local now = context.tick.time
    s.started = s.started or now
    local expected = s.legs[s.index + 1] and s.legs[s.index + 1].map or s.goal
    if world.map_id ~= leg.map then
        if s.portal_wait and world.map_id == expected then
            p.stop()
            context.game.log(string.format("portal %s confirmed, leg %d/%d", tostring(leg.portal), s.index, #s.legs))
            local event = {kind = "portal/confirmed", index = s.index, map = world.map_id, portal = leg.portal}
            s.index, s.retries, s.started = s.index + 1, 0, now
            s.graph, s.mover, s.path, s.portal_wait, s.generation, s.blocked = nil, nil, nil, nil, nil, nil
            s.platform_wait = nil
            return "running", nil, event
        end
        return fail("unexpected_map")
    end
    local function retry(reason)
        p.stop()
        if (s.retries or 0) >= 1 then return fail(reason) end
        local edge = s.path and s.mover and s.mover.edges[s.mover.index]
        if edge and edge.from and edge.to then
            s.blocked = s.blocked or {}
            local key = tostring(edge.from) .. ":" .. tostring(edge.to)
            s.blocked[key] = true
            context.game.log("retry blocking edge " .. key)
        end
        s.retries, s.started = (s.retries or 0) + 1, now
        s.graph, s.mover, s.path, s.portal_wait, s.platform_wait = nil, nil, nil, nil, nil
        context.game.log(string.format("leg %d retry: %s", s.index, reason))
        return "running", nil, {kind = "retry", index = s.index, reason = reason}
    end
    if now - s.started > 120 then return retry("timeout") end
    if s.portal_wait then
        if now - s.portal_wait >= 0.2 then p.stop() end
        if now - s.portal_wait >= 3 then return retry("portal_timeout") end
        return "running"
    end
    if s.generation and s.generation ~= world.scene_generation then
        s.graph, s.mover, s.path, s.blocked = nil, nil, nil, nil
    end
    if not s.graph then
        if context.scene.terrain.status ~= "available" then return retry("terrain_unavailable") end
        local graph, reason = terrain.build(context.scene.terrain.navigation)
        if not graph then return retry(reason or "terrain_unavailable") end
        s.graph, s.mover, s.generation = graph, move.new(graph), world.scene_generation
    end
    -- 已规划的跳跃、下落和攀绳途中可能不命中任何平台；继续由移动器完成该边。
    if s.path then
        local status, reason = move.step(s.mover, context, world)
        if status == "failed" then return retry(reason or "move_failed") end
        if status == "done" then s.path = nil end
        return "running"
    end
    local c = world.character
    local platform = terrain.platform_at(s.graph, c.x, c.y, s.graph.model.stand_height)
    local target = terrain.platform_at(s.graph, leg.x, leg.y, s.graph.model.stand_height)
    if not target then return retry("platform_unavailable") end
    if not platform then
        p.stop()
        s.platform_wait = s.platform_wait or now
        if now - s.platform_wait >= 3 then
            s.platform_wait = nil
            return retry("platform_unavailable")
        end
        return "running"
    end
    s.platform_wait = nil
    local dx = leg.x - c.x
    if platform == target and math.abs(dx) <= 6 then
        p.stop()
        p.move("up")
        s.portal_wait = now
        return "running"
    end
    if platform == target then
        s.path = nil
        p.skill(nil)
        p.move(dx > 0 and "right" or "left")
        return "running"
    end
    if not s.path then
        local movement = context.game.character.movement or { max_speed = 125, max_jump_height = 77 }
        local edges, reason = terrain.plan(s.graph, platform, target,
            { speed = movement.max_speed, max_jump_height = movement.max_jump_height, blocked = s.blocked or {} })
        if not edges or #edges == 0 then return retry(reason or "no_path") end
        local ok, set_reason = move.set_path(s.mover, edges)
        if not ok then return retry(set_reason or "no_path") end
        s.path = true
        context.game.log(string.format("leg %d/%d map=%d plan %d edge(s) -> portal %s", s.index, #s.legs,
            leg.map, #edges, tostring(leg.portal)))
        return "running", nil, {kind = "plan", index = s.index, map = leg.map, portal = leg.portal, edges = #edges}
    end
    local status, reason = move.step(s.mover, context, world)
    if status == "failed" then return retry(reason or "move_failed") end
    if status == "done" then s.path = nil end
    return "running"
end


return M
