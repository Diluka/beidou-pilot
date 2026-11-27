package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local io_module, supply = require("lib.io"), require("lib.supply")
local old_poll, old_publish, old_event, old_check = io_module.poll, io_module.publish, io_module.event, supply.check
local events, stops = {}, 0
io_module.poll = function() return {} end
io_module.publish = function() return true end
io_module.event = function(_, kind, data) events[#events + 1] = {kind=kind, data=data}; return true end
supply.check = function() return {reason="low", items={{kind="arrow", quantity=3}}} end
local ctx = {tick = {time=0, script_id="session-1"}, state={bot_root="/test", bot={mode="hunt", config={}}},
    scene={terrain={status="unavailable"}}, game={character={hp=10, max_hp=10, mp=10, max_mp=10},
    world={ready=true, map_id=1, scene_generation=1}, scene={}, inventory={items={}},
    player={stop=function() stops=stops+1 end}}}
ctx.state.bot.player = ctx.game.player
local file = assert(io.open("bot/main.lua")); local tick = assert(load(file:read("*a") .. "\nreturn main"))(); file:close()
assert(tick(ctx) == "done" and stops > 0)
assert(events[#events].kind == "supply/low" and events[#events].data.session_id == "session-1")
assert(ctx.state.bot.last_error == "supply_low")
io_module.poll, io_module.publish, io_module.event, supply.check = old_poll, old_publish, old_event, old_check
print("supply stop tests passed")
