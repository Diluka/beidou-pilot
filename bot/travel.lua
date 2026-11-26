-- 跨图寻路：按 /work/bot/route.json 的 {legs=[{map,x,y,portal}]} 逐图走到传送门并按上。
-- 每个航点用 terrain.plan 一次性规划 + move.step 执行；到点后按上等换图，换图成功进入下一航点。
package.path = "/work/scripts/bot/?.lua;/work/scripts/bot/?/init.lua;" .. package.path
local terrain = require("lib.terrain")
local move = require("lib.move")
local world_mod = require("lib.world")

local function load_route()
    local file = io.open("/work/bot/route.json", "r")
    if not file then return nil end
    local text = file:read("*a")
    file:close()
    local ok, decoded = pcall(function() return text end)
    if not ok then return nil end
    -- 极简 JSON 解析：只支持本工具生成的固定结构。
    local legs = {}
    -- 标准顺序：map, portal, x, y（与 tools/bot_route.py 输出一致）
    for map, portal, x, y in text:gmatch('"map"%s*:%s*(%d+),%s*"portal"%s*:%s*"([^"]*)",%s*"x"%s*:%s*(-?%d+%.?%d*),%s*"y"%s*:%s*(-?%d+%.?%d*)') do
        legs[#legs + 1] = { map = tonumber(map), portal = portal, x = tonumber(x), y = tonumber(y) }
    end
    if #legs == 0 then
        for map, x, y in text:gmatch('"map"%s*:%s*(%d+)[^}]-"x"%s*:%s*(-?%d+%.?%d*)[^}]-"y"%s*:%s*(-?%d+%.?%d*)') do
            legs[#legs + 1] = { map = tonumber(map), x = tonumber(x), y = tonumber(y) }
        end
    end
    if #legs == 0 then return nil end
    return legs
end

local function main(context)
    local s, p = context.state, context.game.player
    local world = world_mod.observe(context)
    if not world then return "failed", "world_unavailable" end
    s.legs = s.legs or load_route()
    if not s.legs then return "failed", "route_missing" end
    s.index = s.index or 1
    s.t = s.t or context.tick.time
    local leg = s.legs[s.index]
    if not leg then p.stop(); context.game.log("route complete"); return "done" end
    if world.map_id ~= leg.map then
        -- 已经在下一张图（上一个传送门生效），前进
        s.index = s.index + 1
        s.path = nil
        return
    end
    local c = world.character
    if not s.graph then
        s.graph = assert(terrain.build(context.scene.terrain.navigation))
        s.mover = move.new(s.graph)
    end
    local platform = terrain.platform_at(s.graph, c.x, c.y, s.graph.model.stand_height)
    local target_platform = terrain.platform_at(s.graph, leg.x, leg.y, s.graph.model.stand_height)
    if platform == nil or target_platform == nil then
        p.move(leg.x > c.x and "right" or "left")
        return
    end
    local dx = leg.x - c.x
    if platform == target_platform and math.abs(dx) <= 6 then
        if not s.up then s.up, s.up_time = true, context.tick.time end
        if context.tick.time - s.up_time < 0.2 then
            p.move(nil)
            p.move("up")
        else
            p.move(nil)
            s.up = nil
            s.path = nil
            s.index = s.index + 1
            context.game.log(string.format("portal %s used, leg %d/%d", tostring(leg.portal), s.index - 1, #s.legs))
        end
        return
    end
    if not s.path then
        local movement = context.game.character.movement or { max_speed = 125, max_jump_height = 77 }
        local edges, reason = terrain.plan(s.graph, platform, target_platform,
            { speed = movement.max_speed, max_jump_height = movement.max_jump_height, blocked = {} })
        if not edges or #edges == 0 then
            p.move(dx > 0 and "right" or "left")
            context.game.log("plan fallback reason=" .. tostring(reason))
            return
        end
        assert(move.set_path(s.mover, edges))
        s.path = true
        context.game.log(string.format("leg %d/%d map=%d plan %d edge(s) -> portal %s", s.index, #s.legs,
            leg.map, #edges, tostring(leg.portal)))
    end
    local status, reason = move.step(s.mover, context, world)
    if status == "failed" then
        s.path = nil
        p.stop()
        context.game.log("leg failed: " .. tostring(reason))
        return "failed", reason
    end
    if status == "done" then
        s.path = nil
    end
    if context.tick.index % 90 == 0 then
        context.game.log(string.format("t=%.0f map=%d x=%.0f y=%.0f", context.tick.time - s.t, world.map_id, c.x, c.y))
    end
    if context.tick.time - s.t > 240 then p.stop(); return "failed", "timeout" end
end
