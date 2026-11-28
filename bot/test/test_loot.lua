package.path = "bot/?.lua;bot/?/init.lua;" .. package.path

local loot = require("lib.loot")
local move = require("lib.move")
local io_module = require("lib.io")
local saved_set_path, saved_move_step, saved_move_stop = move.set_path, move.step, move.stop
local saved_event = io_module.event
local edges, move_results, events = {}, {}, {}
local pickup_count, cleared_actions, move_stop_count = 0, 0, 0
local directions = {}

move.set_path = function(mover, path)
    edges[#edges + 1] = path[1]
    mover.edges, mover.status = path, "running"
    return true
end
move.step = function(mover)
    local result = table.remove(move_results, 1)
    local status, reason = result and result[1] or "running", result and result[2]
    mover.status = status
    return status, reason
end
move.stop = function(mover)
    move_stop_count = move_stop_count + 1
    mover.status = "done"
end
io_module.event = function(_, kind, data)
    events[#events + 1] = {kind = kind, data = data}
    return true
end

game = {player = {
    move = function(direction) directions[#directions + 1] = direction or "stop"; return true end,
    skill = function(value)
        assert(value == nil, "loot cleanup must clear the action slot")
        cleared_actions = cleared_actions + 1
        return true
    end,
    pickup = function() pickup_count = pickup_count + 1; return true end,
}}

local function drop(object_id, x, platform, landed)
    return {object_id = object_id, item_id = 4001007, x = x, y = 0,
        platform = platform or 1, landed = landed ~= false}
end

local function world_with(drops, x)
    return {
        now = 0,
        character = {x = x or 0, y = 0, hp = 40, max_hp = 100, platform = 1},
        owner = {present = false}, mobs = {}, drops = drops or {},
        inventory = {{item_id = 4001007, quantity = 10}},
    }
end

local function context(time)
    return {tick = {time = time}, game = game}
end

local candidate = drop(3, 150)
local selection_world = world_with({
    drop(3, 20), drop(2, -20), drop(4, 151), drop(5, 0, 2), drop(6, 10, 1, false), candidate,
})
local selected = loot.select(selection_world, {radius = 150})
assert(selected and selected.object_id == 2,
    "selection must filter landed/platform/radius and break distance ties by object_id")
assert(loot.select(selection_world, {radius = 19}) == nil, "custom radius must be honored")
selection_world.owner = {present = true, distance = 100}
local selected, reason = loot.select(selection_world, {owner = selection_world.owner})
assert(selected == nil and reason == "owner_near", "owner at 100px must cause a wait")
selection_world.owner.distance = 101
assert(loot.select(selection_world, {owner = selection_world.owner}) ~= nil,
    "owner outside 100px must not block selection")
selection_world.character.hp = 39
selected, reason = loot.select(selection_world, {})
assert(selected == nil and reason == "unsafe", "HP below 40 percent must block selection")
selection_world.character.hp = 40
selection_world.mobs = {{active = true, x = 80, y = 0}}
selected = loot.select(selection_world, {})
assert(selected and selected.object_id == 2,
    "a close landed drop may be picked while a mob is nearby (opportunistic pickup)")
local far_world = world_with({drop(20, 150)})
far_world.mobs = {{active = true, x = 80, y = 0}}
selected, reason = loot.select(far_world, {})
assert(selected == nil and reason == "unsafe", "a far drop with an active mob within 80px must stay blocked")
selection_world.mobs = {{active = false, x = 0, y = 0}}
assert(loot.select(selection_world, {}) ~= nil, "inactive mobs must not block selection")
selection_world.mobs = {}
selection_world.character.platform = nil
assert(loot.select(selection_world, {}) == nil, "selection needs a known character platform")

local current = drop(10, 25)
local world = world_with({current})
local mover = {status = "done"}
local ctx = context(0)
local status = loot.step(ctx, world, current, mover)
assert(status == "running" and pickup_count == 1, "nearby drop must issue pickup")
world.inventory[1].quantity = 11
world.drops = {}
status, reason = loot.step(ctx, world, current, mover)
assert(status == "done" and reason == "cleared" and mover.loot == nil,
    "a disappeared local drop must complete the sweep")
assert(cleared_actions > 0, "terminal success must clear the action slot")

current = drop(11, 20)
world = world_with({current})
mover = {status = "done"}
ctx = context(1)
assert(loot.step(ctx, world, current, mover) == "running")
world.drops = {}
status, reason = loot.step(ctx, world, current, mover)
assert(status == "done" and reason == "cleared", "disappeared drop must end the sweep")

current = drop(12, 140)
world = world_with({current})
mover = {status = "done"}
move_results = {{"running"}}
ctx = context(2)
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "moving", "far drop must delegate movement")
local edge = edges[#edges]
assert(edge.kind == "walk" and edge.from == 1 and edge.to == 1 and edge.x == 0
    and edge.destination == 140 and edge.rise == 0, "loot movement edge must match the locked contract")
world.character.x = 120
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "sweeping" and move_stop_count == 1,
    "within 25px loot must stop approach and pick up")

current = drop(13, 20, 2)
world = world_with({current})
mover = {status = "done"}
ctx = context(3)
status, reason = loot.step(ctx, world, current, mover)
assert(status == "failed" and reason == "drop_platform_unreachable" and pickup_count == 3,
    "different platform must fail without attempting pickup")
assert(events[#events].kind == "loot" and events[#events].data.object_id == 13,
    "terminal failure must publish a loot event")
current = drop(17, 20, 2)
world = world_with({})
mover = {status = "done"}
status, reason = loot.step(context(3.5), world, current, mover)
assert(status == "failed" and reason == "drop_platform_unreachable",
    "a missing off-platform drop must not be mistaken for a successful pickup")

current = drop(14, 20)
world = world_with({current})
world.owner = {present = true, distance = 75}
mover = {status = "done"}
ctx = context(4)
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "owner_near" and pickup_count == 3,
    "owner proximity during a step must wait without picking")
world.owner.distance = 101
ctx.tick.time = 4.1
assert(loot.step(ctx, world, current, mover) == "running" and pickup_count == 4,
    "pickup may proceed after owner moves away")
world.character.hp = 39
ctx.tick.time = 4.2
status, reason = loot.step(ctx, world, current, mover)
assert(status == "failed" and reason == "hp_low" and pickup_count == 4,
    "low HP during a sweep must stop pickup")
world.character.hp = 40

current = drop(18, 20)
world = world_with({current})
world.mobs = {{active = true, x = 60, y = 0}}
mover = {status = "done"}
local close_pickup_before = pickup_count
assert(loot.step(context(0), world, current, mover) == "running"
    and pickup_count == close_pickup_before + 1,
    "a close drop may be picked while a mob is nearby")
current = drop(19, 150)
world = world_with({current})
world.mobs = {{active = true, x = 60, y = 0}}
mover = {status = "done"}
local status_far, reason_far = loot.step(context(0), world, current, mover)
assert(status_far == "failed" and reason_far == "unsafe",
    "a far drop with nearby mobs must remain unsafe for pickup")

current = drop(15, 20)
world = world_with({current})
mover = {status = "done"}
ctx = context(0)
assert(loot.step(ctx, world, current, mover) == "running")
ctx.tick.time = 5
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "fallback" and mover.loot == nil,
    "sweep timeout must yield to individual pickup")
assert(events[#events].kind == "loot/sweep" and events[#events].data.attempts == 1
    and events[#events].data.initial_drops == 1 and events[#events].data.remaining_drops == 1
    and events[#events].data.accepted == 1 and events[#events].data.rejected == 0
    and events[#events].data.fallback == true, "timeout event must describe the fallback")
ctx.tick.time = 5.1
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "picking", "individual pickup must run on the next tick")
world.drops = {}
assert(select(2, loot.step(ctx, world, current, mover)) == "picked", "fallback confirms the individual object")
world.drops = {current}
ctx.tick.time = 21
assert(select(2, loot.step(ctx, world, current, mover)) == "sweeping", "sweep becomes eligible after the cooldown")

current = drop(16, 140)
world = world_with({current})
mover = {status = "done"}
move_results = {{"failed", "no_progress"}, {"failed", "no_progress"}}
ctx = context(20)
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "retry", "no progress must trigger one retry")
status, reason = loot.step(ctx, world, current, mover)
assert(status == "failed" and reason == "no_progress", "repeated no progress must fail")
assert(events[#events].data.attempts == 2, "no-progress failure must not exceed one retry")

local terrain = require("lib.terrain")
local saved_plan = terrain.plan
local cross = drop(90, 100, 2)
world = world_with({cross, drop(91, 140, 1)})
world.map_id, world.scene_generation = 1, 1
assert(loot.select(world, {graph = {}, radius = 150}).object_id == 91,
    "same-platform drops must precede cross-platform drops")
world.drops = {cross}
ctx = context(30)
ctx.state = {graph = {}}
mover = {status = "done"}
terrain.plan = function(_, from, to)
    assert(from == 1 and to == 2)
    return {{kind = "jumpup", from = 1, to = 2, x = 0, destination = 0, rise = 50}}
end
move_results = {{"running"}}
status, reason = loot.step(ctx, world, cross, mover)
assert(status == "running" and reason == "cross_platform" and edges[#edges].kind == "jumpup")
world.character.platform, world.character.x = 2, 80
status, reason = loot.step(ctx, world, cross, mover)
assert(status == "running" and reason == "sweeping", "sweep follows observed arrival")
world.character.platform = 1
mover = {status = "done"}
terrain.plan = function() return nil, "no_path" end
status, reason = loot.step(ctx, world, cross, mover)
assert(status == "failed" and reason == "no_path" and ctx.state.loot_abandoned[90])
assert(loot.select(world, {graph = {}, abandoned = ctx.state.loot_abandoned}) == nil,
    "unreachable drop must not be selected again")
local blocked_drop = drop(92, 100, 2)
ctx.state.hunt_failures = 0
world.drops = {blocked_drop}
terrain.plan = function() return {{kind = "rope", from = 1, to = 2, x = 17, destination = 17, rise = 40}} end
mover = {status = "done"}
move_results = {{"failed", "rope_mismatch"}}
status, reason = loot.step(ctx, world, blocked_drop, mover)
assert(status == "failed" and ctx.state.blocked["1:2"] and ctx.state.hunt_failures == 1)
assert(events[#events].data.edge_kind == "rope" and events[#events].data.edge_x == 17,
    "loot failure event identifies the failed edge")
assert(loot.select(world, {graph = {}, local_only = true}) == nil, "fallback excludes remote loot")
terrain.plan = saved_plan

-- A cluster keeps one pickup intent until the local drops are observed gone.
local a, b, remote = drop(200, 10), drop(201, 30), drop(202, 10, 2)
world = world_with({a, b, remote})
ctx, mover = context(40), {status = "done"}
ctx.state = {graph = {platforms = {{left = -200, right = 200}}}}
local before = pickup_count
assert(select(2, loot.step(ctx, world, a, mover)) == "sweeping")
assert(directions[#directions] == "right", "sweep must keep moving through the drop cluster")
world.drops = {b, remote}
ctx.tick.time = 40.2
assert(select(2, loot.step(ctx, world, b, mover)) == "sweeping")
assert(mover.loot.count == 1, "the first disappearance must be observed while the sweep continues")
assert(directions[#directions] == "right", "sweep must not stop to pick one object at a time")
world.drops = {remote}
ctx.tick.time = 40.4
status, reason = loot.step(ctx, world, b, mover)
local summary = events[#events]
assert(status == "done" and reason == "cleared" and summary.kind == "loot/sweep"
    and summary.data.count == 2 and #summary.data.items == 2 and summary.data.elapsed > 0)
assert(pickup_count == before + 1, "pickup must not be submitted twice in adjacent ticks")

world = world_with({drop(205, -50), drop(206, 50)})
ctx, mover = context(45), {status = "done"}
ctx.state = {graph = {platforms = {{left = -200, right = 200}}}}
local first_count, first_clears = pickup_count, cleared_actions
for i = 1, 7 do
    ctx.tick.time = 45 + i * 0.04
    assert(select(2, loot.step(ctx, world, world.drops[1], mover)) == "sweeping")
end
assert(pickup_count == first_count + 3 and cleared_actions >= first_clears + 2,
    "three-tick cycle must release and re-submit while sweeping")
assert(directions[#directions] ~= "stop", "pickup pulses must preserve movement intent")

local saved_pickup = game.player.pickup
local attempts = 0
game.player.pickup = function()
    attempts = attempts + 1
    if attempts == 1 then return false, "cooldown" end
    return true
end
world = world_with({drop(210, 10)})
ctx, mover = context(50), {status = "done"}
assert(select(2, loot.step(ctx, world, world.drops[1], mover)) == "sweeping")
ctx.tick.time = 50.2
loot.step(ctx, world, world.drops[1], mover)
assert(attempts == 1, "rejected intent must not be retried every tick")
ctx.tick.time = 50.5
loot.step(ctx, world, world.drops[1], mover)
assert(attempts == 1, "release tick must not submit pickup")
ctx.tick.time = 50.6
loot.step(ctx, world, world.drops[1], mover)
assert(attempts == 2 and mover.loot.pickup_requested)
world.mobs = {{active = true, x = 30, y = 0}}
ctx.tick.time = 50.6
status, reason = loot.step(ctx, world, world.drops[1], mover)
assert(status == "failed" and reason == "unsafe" and not mover.loot
    and events[#events].kind == "loot/sweep" and events[#events].data.reason == "unsafe"
    and events[#events].data.accepted == 1 and events[#events].data.rejected == 1
    and events[#events].data.last_rejection == "cooldown")
game.player.pickup = saved_pickup
for _, hazard in ipairs({"owner", "hp"}) do
    world = world_with({drop(220, 10)})
    ctx, mover = context(60), {status = "done"}
    loot.step(ctx, world, world.drops[1], mover)
    if hazard == "owner" then world.owner = {present = true, distance = 50}
    else world.character.hp = 39 end
    ctx.tick.time = 61
    status, reason = loot.step(ctx, world, world.drops[1], mover)
    assert(status == "failed" and events[#events].kind == "loot/sweep"
        and events[#events].data.reason == (hazard == "owner" and "owner_near" or "hp_low"))
end

-- Main may preempt before step sees the final disappearance.
local final_drop = drop(219, 10)
world = world_with({final_drop})
ctx, mover = context(61), {status = "done"}
loot.step(ctx, world, final_drop, mover)
world.drops = {}
ctx.tick.time = 61.2
loot.step(ctx, world, {sweep_abort = true}, mover)
assert(events[#events].data.reason == "cleared" and events[#events].data.count == 1
    and events[#events].data.remaining_drops == 0, "preemption must reconcile a cleared observed cluster")

world = world_with({drop(221, 10)})
ctx, mover = context(62), {status = "done"}
loot.step(ctx, world, world.drops[1], mover)
local cleared_before = cleared_actions
loot.step(ctx, world, {sweep_abort = true, preserve_action = true}, mover)
assert(cleared_actions == cleared_before and not mover.loot and events[#events].data.reason == "interrupted",
    "sustain preemption must not clear the newly installed action")

-- Main action-slot preemption must emit the summary before discarding the sweep.
local world_module, sustain, combat = require("lib.world"), require("lib.sustain"), require("lib.combat")
local old_observe, old_sustain, old_select, old_poll, old_publish = world_module.observe, sustain.step,
    combat.select, io_module.poll, io_module.publish
world = world_with({})
world.map_id, world.scene_generation, world.ready = 808, 1, true
world.character.x, world.character.y, world.character.on_ground = 50, 100, true
world_module.observe = function() return world end
sustain.step = function() return false end
combat.select = function() return {object_id = 500} end
io_module.poll = function() return {} end
io_module.publish = function() return true end
local nav = dofile("bot/test/fixtures/synthetic.lua").navigation
local graph = assert(terrain.build(nav))
ctx = {tick = {time = 71, index = 1}, game = game, scene = {terrain = {status = "available", navigation = nav}},
    state = {bot = {mode = "hunt", config = {}}, graph = graph, graph_generation = 1,
        hunt_action = "loot", mover = {status = "done", loot = {sweep = true, started_at = 70,
            items = {}, count = 0, submissions = 1}}}}
game.character = {action_idle = true}
local main_file = assert(io.open("bot/main.lua"))
local tick = assert(load(main_file:read("*a") .. "\nreturn main", "bot/main.lua"))()
main_file:close()
local event_start = #events
tick(ctx)
local summaries = 0
for i = event_start + 1, #events do
    if events[i].kind == "loot/sweep" and events[i].data.reason == "interrupted" then summaries = summaries + 1 end
end
assert(summaries == 1 and ctx.state.mover.loot == nil, "main preemption must summarize exactly once")
combat.select = function() return nil end
for _, hazard in ipairs({"owner", "hp"}) do
    world.owner = hazard == "owner" and {present = true, distance = 20} or {present = false}
    world.character.hp = hazard == "hp" and 39 or 100
    world.drops = {drop(230, 55)}
    world.drops[1].y = 100
    ctx.state.hunt_action, ctx.state.hunt_drop = "loot", world.drops[1]
    ctx.state.mover.loot = {sweep = true, started_at = 70, items = {}, count = 0, submissions = 1}
    event_start = #events
    tick(ctx)
    summaries = 0
    for i = event_start + 1, #events do
        if events[i].kind == "loot/sweep" then summaries = summaries + 1 end
    end
    assert(summaries == 1 and not ctx.state.mover.loot, hazard .. " must summarize the interrupted sweep")
end
world_module.observe, sustain.step, combat.select, io_module.poll, io_module.publish = old_observe, old_sustain,
    old_select, old_poll, old_publish

move.set_path, move.step, move.stop = saved_set_path, saved_move_step, saved_move_stop
io_module.event = saved_event
print("loot tests passed")
