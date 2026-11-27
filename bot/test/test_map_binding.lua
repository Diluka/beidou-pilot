package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local io_module, travel = require("lib.io"), require("lib.travel")
local old_open, old_poll, old_publish, old_event = io.open, io_module.poll, io_module.publish, io_module.event
local old_load, old_new, old_step, old_stop = travel.load_route, travel.new, travel.step, travel.stop
local events, commands, stops, route, plan = {}, {}, 0, false, "hunt_map=2\n"
io.open = function(path, mode)
    if path == "/test/plan.conf" then
        return {read = function() return plan end, close = function() end}
    end
    return old_open(path, mode)
end
io_module.poll = function() local result = commands; commands = {}; return result end
io_module.publish = function() return true end
io_module.event = function(_, kind, data) events[#events + 1] = {kind = kind, data = data}; return true end
travel.load_route = function() if route then return {{map = 1, x = 50, y = 100}}, 2 end end
travel.new = function(legs, goal) return {legs = legs, goal = goal} end
travel.step = function(_, _, world)
    if world.map_id == 2 then return "done", nil, {kind = "done"} end
    return "running"
end
travel.stop = function(_, ctx) ctx.game.player.stop() end
local ctx = {tick = {time = 0}, state = {bot_root = "/test", bot = {mode = "hunt", config = {}}},
    scene = {terrain = {status = "available", navigation = dofile("bot/test/fixtures/synthetic.lua").navigation}},
    game = {character = {x = 50, y = 100, on_ground = true, hp = 50, max_hp = 50, mp = 10, max_mp = 10},
        world = {ready = true, map_id = 1, scene_generation = 1}, scene = {players = {}, mobs = {}, drops = {}},
        inventory = {items = {}}, player = {stop = function() stops = stops + 1; return true end,
            move = function() end, skill = function() end}}}
ctx.state.bot.player = ctx.game.player
local file = assert(old_open("bot/main.lua")); local tick = assert(load(file:read("*a") .. "\nreturn main"))(); file:close()
tick(ctx)
assert(events[#events].kind == "travel/wait" and events[#events].data.reason == "route_unavailable")
assert(stops > 0 and not ctx.state.hunt_action)
route = true; ctx.tick.time = 1; tick(ctx)
assert(ctx.state.travel and events[#events].kind == "travel/start")
ctx.game.world.map_id = 2; ctx.game.world.scene_generation = 2; ctx.tick.time = 2; tick(ctx)
assert(not ctx.state.travel and events[#events].kind == "travel/done")
ctx.game.world.map_id = 1; ctx.game.world.scene_generation = 3; ctx.tick.time = 3; tick(ctx)
assert(ctx.state.travel)
commands = {{_ok = true, kind = "stop", id = "stop", source = "host"}}
ctx.tick.time = 4; local before = stops; tick(ctx)
assert(not ctx.state.travel and stops > before, "stop releases travel input")
ctx.tick.time = 5; tick(ctx)
assert(not ctx.state.travel, "explicit stop must not restart travel")
ctx.state.travel_suspended = nil
ctx.state.bot.mode = "idle"
ctx.tick.time = 6; tick(ctx)
assert(ctx.state.travel, "idle resumes travel to bound map")
local count = #events
ctx.tick.time = 7; tick(ctx)
assert(ctx.state.travel and #events == count, "running travel must not restart")
ctx.game.world.map_id = 2; ctx.game.world.scene_generation = 4; ctx.tick.time = 8; tick(ctx)
assert(not ctx.state.travel and ctx.state.bot.mode == "idle", "idle remains idle after travel")
plan = ""; ctx.game.world.map_id = 1; ctx.game.world.scene_generation = 5; ctx.tick.time = 9; tick(ctx)
assert(not ctx.state.travel, "missing plan must not start travel")
io.open, io_module.poll, io_module.publish, io_module.event = old_open, old_poll, old_publish, old_event
travel.load_route, travel.new, travel.step, travel.stop = old_load, old_new, old_step, old_stop
print("map binding tests passed")
