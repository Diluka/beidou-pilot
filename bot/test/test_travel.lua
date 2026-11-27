package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local terrain, move = require("lib.terrain"), require("lib.move")
local travel = require("lib.travel")
local original_build, original_at, original_plan = terrain.build, terrain.platform_at, terrain.plan
local original_new, original_set, original_step = move.new, move.set_path, move.step
local graph = {model = {stand_height = 20}}
local plans, steps, commands = 0, 0, {}
terrain.build = function() return graph end
terrain.platform_at = function(_, x) return x < 50 and 1 or 2 end
terrain.plan = function(_, _, _, options)
    plans = plans + 1
    if options.blocked["1:2"] then return nil, "no_path" end
    return {{from = 1, to = 2}}
end
move.new = function() return {} end
move.set_path = function(mover, edges) mover.edges, mover.index = edges, 1; return true end
move.step = function() steps = steps + 1; return "failed", "move_failed" end
local p = {
    stop = function() commands[#commands + 1] = "stop" end,
    move = function(dir) commands[#commands + 1] = dir; return true end,
    skill = function() end,
}
local ctx = {tick = {time = 0}, scene = {terrain = {status = "available", navigation = {}}},
    game = {player = p, character = {movement = {}}, log = function() end}}
local world = {ready = true, map_id = 1, scene_generation = 1, character = {x = 0, y = 0}}
local state = {legs = {{map = 1, portal = "out", x = 100, y = 0}}, goal = 2}
local status, reason, event = travel.step(state, ctx, world)
assert(status == "running" and event.kind == "plan")
status, reason, event = travel.step(state, ctx, world)
assert(status == "running" and event.kind == "retry" and state.retries == 1 and state.blocked["1:2"])
status, reason = travel.step(state, ctx, world)
assert(status == "failed" and reason == "no_path" and plans == 2 and steps == 1)

state = {legs = {{map = 1, portal = "out", x = 0, y = 0}}, goal = 2}
assert(travel.step(state, ctx, world) == "running" and state.portal_wait == 0 and commands[#commands] == "up")
ctx.tick.time = 0.3
travel.step(state, ctx, world)
assert(commands[#commands] == "stop" and state.index == 1)
world.map_id = 2
status, reason, event = travel.step(state, ctx, world)
assert(status == "running" and event.kind == "portal/confirmed" and state.index == 2)
status, reason, event = travel.step(state, ctx, world)
assert(status == "done" and event.kind == "done")
state = {legs = {{map = 1, portal = "out", x = 0, y = 0}}, goal = 2}
status, reason = travel.step(state, ctx, world)
assert(status == "failed" and reason == "unexpected_map")
world.ready = false
status, reason = travel.step(state, ctx, world)
assert(status == "failed" and reason == "world_unavailable")
world.ready, world.map_id = true, 1
ctx.tick.time = 10
state = travel.new({{map = 1, portal = "out", x = 0, y = 0}}, 2)
travel.step(state, ctx, world)
ctx.tick.time = 13.1
status, reason, event = travel.step(state, ctx, world)
assert(status == "running" and event.kind == "retry" and event.reason == "portal_timeout")
travel.step(state, ctx, world)
ctx.tick.time = 16.2
status, reason = travel.step(state, ctx, world)
assert(status == "failed" and reason == "portal_timeout")
travel.stop(state, ctx)
assert(commands[#commands] == "stop")

terrain.build, terrain.platform_at, terrain.plan = original_build, original_at, original_plan
move.new, move.set_path, move.step = original_new, original_set, original_step
print("travel tests ok")
