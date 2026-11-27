-- 按 /work/bot/route.json 的航点逐图走到传送门；仅在观察到目标地图后推进。
package.path = "/work/scripts/bot/?.lua;/work/scripts/bot/?/init.lua;" .. package.path
local terrain = require("lib.terrain")
local move = require("lib.move")
local world_mod = require("lib.world")

local function load_route()
    local file = io.open("/work/bot/route.json", "r")
    if not file then return nil end
    local text = file:read("*a")
    file:close()
    local goal = tonumber(text:match('"goal"%s*:%s*(%d+)'))
    local legs = {}
    for map, portal, x, y in text:gmatch('"map"%s*:%s*(%d+),%s*"portal"%s*:%s*"([^"]*)",%s*"x"%s*:%s*(-?%d+%.?%d*),%s*"y"%s*:%s*(-?%d+%.?%d*)') do
        legs[#legs + 1] = { map = tonumber(map), portal = portal, x = tonumber(x), y = tonumber(y) }
    end
    if #legs == 0 or not goal then return nil end
    return legs, goal
end

local function main(context)
    local s, p = context.state, context.game.player
    local world = world_mod.observe(context)
    local function fail(reason)
        p.stop()
        context.game.log("travel failed: " .. reason)
        return "failed", reason
    end
    if not s.legs then
        s.legs, s.goal = load_route()
        if not s.legs then return fail("route_missing") end
    end
    s.index = s.index or 1
    local leg = s.legs[s.index]
    if not leg then p.stop(); context.game.log("route complete"); return "done" end
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
            s.index, s.retries, s.started = s.index + 1, 0, now
            s.graph, s.mover, s.path, s.portal_wait, s.generation = nil, nil, nil, nil, nil
            if s.index > #s.legs then context.game.log("route complete"); return "done" end
            return
        end
        return fail("unexpected_map")
    end
    local function retry(reason)
        p.stop()
        if (s.retries or 0) >= 1 then return fail(reason) end
        s.retries, s.started = (s.retries or 0) + 1, now
        s.graph, s.mover, s.path, s.portal_wait, s.generation = nil, nil, nil, nil, nil
        context.game.log(string.format("leg %d retry: %s", s.index, reason))
    end
    if now - s.started > 120 then return retry("timeout") end
    if s.portal_wait then
        if now - s.portal_wait >= 0.2 then p.stop() end
        if now - s.portal_wait >= 3 then return retry("portal_timeout") end
        return
    end
    if s.generation and s.generation ~= world.scene_generation then
        s.graph, s.mover, s.path = nil, nil, nil
    end
    if not s.graph then
        if context.scene.terrain.status ~= "available" then return retry("terrain_unavailable") end
        local graph, reason = terrain.build(context.scene.terrain.navigation)
        if not graph then return retry(reason or "terrain_unavailable") end
        s.graph, s.mover, s.generation = graph, move.new(graph), world.scene_generation
    end
    local c = world.character
    local platform = terrain.platform_at(s.graph, c.x, c.y, s.graph.model.stand_height)
    local target = terrain.platform_at(s.graph, leg.x, leg.y, s.graph.model.stand_height)
    if not platform or not target then return retry("platform_unavailable") end
    local dx = leg.x - c.x
    if platform == target and math.abs(dx) <= 6 then
        p.stop()
        p.move("up")
        s.portal_wait = now
        return
    end
    if platform == target then
        s.path = nil
        p.skill(nil)
        p.move(dx > 0 and "right" or "left")
        return
    end
    if not s.path then
        local movement = context.game.character.movement or { max_speed = 125, max_jump_height = 77 }
        local edges, reason = terrain.plan(s.graph, platform, target,
            { speed = movement.max_speed, max_jump_height = movement.max_jump_height, blocked = {} })
        if not edges or #edges == 0 then return retry(reason or "no_path") end
        local ok, set_reason = move.set_path(s.mover, edges)
        if not ok then return retry(set_reason or "no_path") end
        s.path = true
        context.game.log(string.format("leg %d/%d map=%d plan %d edge(s) -> portal %s", s.index, #s.legs,
            leg.map, #edges, tostring(leg.portal)))
    end
    local status, reason = move.step(s.mover, context, world)
    if status == "failed" then return retry(reason or "move_failed") end
    if status == "done" then s.path = nil end
end
