package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local io_module, supply = require("lib.io"), require("lib.supply")
local sustain, travel = require("lib.sustain"), require("lib.travel")
local old_sustain, old_open, old_load, old_new, old_step, old_stop = sustain.step, io.open, travel.load_route, travel.new, travel.step, travel.stop
local plan, route, travel_result, heals, potion = "", false, "running", 0, false
io.open = function(path, mode)
    if path == "/test/plan.conf" then return {read=function() return plan end, close=function() end} end
    return old_open(path, mode)
end
sustain.step = function() heals = heals + 1; if potion then return true, "hp_potion" end; return false end
travel.load_route = function() if route then return {{map=1}}, 2 end end
travel.new = function() return {} end
travel.step = function() return travel_result, "blocked" end
travel.stop = function(_, context) context.game.player.stop() end
local old_poll, old_publish, old_event, old_check = io_module.poll, io_module.publish, io_module.event, supply.check
local events, stops = {}, 0
io_module.poll = function() return {} end
io_module.publish = function() return true end
io_module.event = function(_, kind, data) events[#events + 1] = {kind=kind, data=data}; return true end
supply.check = function(_, inventory)
    assert(inventory == nil, "unavailable inventory must not be interpreted as empty")
    return {reason="low", items={{kind="arrow", quantity=3}}}
end
local ctx = {tick = {time=0, script_id="session-1"}, state={bot_root="/test", bot={mode="hunt", config={}}},
    scene={terrain={status="unavailable"}}, game={character={hp=10, max_hp=10, mp=10, max_mp=10},
    world={ready=true, map_id=1, scene_generation=1}, scene={}, inventory={items={}},
    player={stop=function() stops=stops+1 end, move=function() end}}}
ctx.state.bot.player = ctx.game.player
local file = assert(io.open("bot/main.lua")); local tick = assert(load(file:read("*a") .. "\nreturn main"))(); file:close()
assert(tick(ctx) == nil and stops > 0 and heals == 1)
assert(events[1].kind == "supply/low" and events[1].data.session_id == "session-1")
assert(events[#events].data.reason == "safe_map_unavailable")
ctx.tick.time = 1; tick(ctx); assert(heals == 2, "failed retreat must continue sustain")
ctx.state.supply_retreat = nil; ctx.tick.time = 2; plan = "safe_map=2\n"; tick(ctx)
assert(events[#events].data.reason == "route_unavailable")
ctx.state.supply_retreat = nil; ctx.tick.time = 3; route = true; tick(ctx)
assert(ctx.state.travel and events[#events].data.result == "started")
potion = true; travel_result = "failed"; ctx.tick.time = 3.5; tick(ctx)
assert(ctx.state.travel and heals == 5, "potion handling must precede retreat movement")
potion = false; ctx.tick.time = 4; tick(ctx)
assert(events[#events].data.result == "failed" and events[#events].data.reason == "blocked")
ctx.state.supply_retreat = nil; ctx.tick.time = 5; travel_result = "running"; tick(ctx)
ctx.game.world.map_id = 2; ctx.tick.time = 6
assert(tick(ctx) == "done" and events[#events].data.result == "arrived")
io_module.poll, io_module.publish, io_module.event, supply.check = old_poll, old_publish, old_event, old_check
sustain.step, io.open, travel.load_route, travel.new, travel.step, travel.stop = old_sustain, old_open, old_load, old_new, old_step, old_stop
print("supply stop tests passed")
