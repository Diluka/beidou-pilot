package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local terrain, move = require("lib.terrain"), require("lib.move")
local travel = require("lib.travel")
local original_build, original_at, original_plan = terrain.build, terrain.platform_at, terrain.plan
local original_new, original_set, original_step = move.new, move.set_path, move.step
local io_module
for i=1,math.huge do
    local name,value=debug.getupvalue(travel.step,i)
    if not name then break end
    if name=="io_module" then io_module=value;break end
end
local original_event = io_module.event
local captured_events = {}
io_module.event = function(_,kind,data) captured_events[#captured_events+1]={kind=kind,data=data};return true end
local graph = {model = {stand_height = 20}}
local plans, steps, commands = 0, 0, {}
terrain.build = function() return graph end
terrain.platform_at = function(_, x) return x < 50 and 1 or 2 end
terrain.plan = function(_, _, _, options)
    assert(options.drop_policy == "conservative", "portal travel opts into conservative drop policy")
    plans = plans + 1
    if options.blocked["1:2"] then return nil, "no_path" end
    return {{from = 1, to = 2}}
end
move.new = function() return {} end
move.set_path = function(mover, edges) mover.edges, mover.index = edges, 1; return true end
move.step = function(mover)
    steps = steps + 1
    mover.last_failure = {kind="drop", from=1, to=2, x=10, destination=20, landing_x=15, landing_y=100}
    return "failed", "move_failed"
end
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
assert(status == "failed" and reason == "move_failed" and event.edge.kind == "drop"
    and event.edge.from == 1 and event.edge.to == 2 and event.edge.landing_x == 15
    and plans == 1 and steps == 1 and commands[#commands] == "stop",
    "a failed mover edge must stop and report details without retrying")

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

local policy_state = {legs={{map=1,portal="out",x=100,y=0}},goal=2}
world.ready,world.map_id = true,1
terrain.plan = function(_,_,_,options)
    assert(options.drop_policy == "conservative")
    options.drop_rejections.count=1
    options.drop_rejections.first={kind="drop",from=1,to=2,x=1,destination=100,rise=30}
    return nil,"no_path"
end
status, reason = travel.step(policy_state,ctx,world)
assert(status=="failed" and reason=="no_path:drop_rejected_unproven" and commands[#commands]=="stop")
assert(captured_events[#captured_events].kind=="drop_rejected_unproven"
    and captured_events[#captured_events].data.first.from==1, "rejected drop event identifies an example")
terrain.build, terrain.platform_at, terrain.plan = original_build, original_at, original_plan
move.new, move.set_path, move.step = original_new, original_set, original_step
io_module.event = original_event
print("travel tests ok")
