package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local io_module, supply, travel, sustain = require("lib.io"), require("lib.supply"), require("lib.travel"), require("lib.sustain")
local old_open, old_poll, old_publish, old_event = io.open, io_module.poll, io_module.publish, io_module.event
local old_check, old_load, old_new, old_step, old_sustain = supply.check, travel.load_route, travel.new, travel.step, sustain.step
local events, stops, check_result, checks = {}, 0, nil, 0
io.open = function(path, mode)
    if path == "/guard/plan.conf" then return {read=function() return "hunt_map=2\n" end, close=function() end} end
    return old_open(path, mode)
end
io_module.poll = function() return {} end
io_module.publish = function() return true end
io_module.event = function(_, kind, data) events[#events+1] = {kind=kind,data=data}; return true end
supply.check = function(_, inventory)
    checks = checks + 1
    if inventory == nil then return {reason="inventory_unavailable"} end
    return check_result
end
sustain.step = function() return false end
travel.load_route = function() return {{map=1}}, 2 end
travel.new = function(legs, goal) return {legs=legs,goal=goal} end
travel.step = function() return "running" end
local ctx = {tick={time=0,script_id="guard"}, state={bot_root="/guard",bot={mode="idle",config={}}},
    scene={terrain={status="available", navigation=dofile("bot/test/fixtures/synthetic.lua").navigation}},
    game={character={x=50,y=100,on_ground=true,hp=100,max_hp=100,mp=100,max_mp=100},
        world={ready=true,map_id=1,scene_generation=1}, scene={}, inventory={status="ok",items={}},
        player={stop=function() stops=stops+1 end, move=function() end, skill=function() end}}}
ctx.state.bot.player=ctx.game.player
local file=assert(old_open("bot/main.lua")); local tick=assert(load(file:read("*a") .. "\nreturn main"))(); file:close()
check_result={reason="low",items={{kind="red",item_id=2000000,quantity=2,threshold=5}}}
tick(ctx)
assert(not ctx.state.travel and stops > 0 and ctx.state.bot.mode == "idle")
assert(events[#events-1].kind == "supply/low" and events[#events-1].data.travel_blocked == "supply_low")
assert(events[#events].kind == "travel/wait" and events[#events].data.reason == "supply_low")
local count=#events; ctx.tick.time=1; tick(ctx); assert(#events == count, "events must be rate limited")
ctx.tick.time=11; tick(ctx); assert(#events == count+2)
check_result={reason="invalid_config"}; ctx.tick.time=12; tick(ctx)
assert(events[#events].kind == "supply/error" and not ctx.state.travel)
ctx.game.inventory.status="unavailable"; ctx.tick.time=13; tick(ctx)
assert(events[#events].kind == "supply/error" and events[#events].data.reason == "inventory_unavailable")
ctx.game.inventory.status="ok"; check_result=nil; ctx.tick.time=14; tick(ctx)
assert(ctx.state.travel, "restored supplies must start travel on next tick")
ctx.state.travel=nil; ctx.tick.time=15; tick(ctx)
assert(ctx.state.travel, "no supply config remains compatible")
io.open, io_module.poll, io_module.publish, io_module.event = old_open, old_poll, old_publish, old_event
supply.check, travel.load_route, travel.new, travel.step, sustain.step = old_check, old_load, old_new, old_step, old_sustain
print("travel supply guard tests passed")
