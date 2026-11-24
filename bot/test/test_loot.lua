package.path = "bot/?.lua;bot/?/init.lua;" .. package.path

local loot = require("lib.loot")
local move = require("lib.move")
local io_module = require("lib.io")
local saved_set_path, saved_move_step, saved_move_stop = move.set_path, move.step, move.stop
local saved_event = io_module.event
local edges, move_results, events = {}, {}, {}
local pickup_count, cleared_actions, move_stop_count = 0, 0, 0

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
    move = function() return true end,
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
selected, reason = loot.select(selection_world, {})
assert(selected == nil and reason == "unsafe", "an active mob within 80px must block selection")
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
status, reason = loot.step(ctx, world, current, mover)
assert(status == "done" and reason == "picked" and mover.loot == nil,
    "inventory increase must confirm pickup")
assert(cleared_actions > 0, "terminal success must clear the action slot")

current = drop(11, 20)
world = world_with({current})
mover = {status = "done"}
ctx = context(1)
assert(loot.step(ctx, world, current, mover) == "running")
world.drops = {}
status, reason = loot.step(ctx, world, current, mover)
assert(status == "done" and reason == "picked", "disappeared drop must confirm pickup")

current = drop(12, 100)
world = world_with({current})
mover = {status = "done"}
move_results = {{"running"}}
ctx = context(2)
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "moving", "far drop must delegate movement")
local edge = edges[#edges]
assert(edge.kind == "walk" and edge.from == 1 and edge.to == 1 and edge.x == 0
    and edge.destination == 100 and edge.rise == 0, "loot movement edge must match the locked contract")
world.character.x = 80
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "picking" and move_stop_count == 1,
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
assert(status == "failed" and reason == "unsafe" and pickup_count == 4,
    "new danger during a step must stop pickup")
world.character.hp = 40

current = drop(15, 20)
world = world_with({current})
mover = {status = "done"}
ctx = context(0)
assert(loot.step(ctx, world, current, mover) == "running")
ctx.tick.time = 5
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "retry" and mover.loot.attempt == 1,
    "first five-second timeout must retry exactly once")
ctx.tick.time = 10
status, reason = loot.step(ctx, world, current, mover)
assert(status == "failed" and reason == "timeout" and mover.loot == nil,
    "second five-second timeout must fail")
assert(events[#events].data.attempts == 2, "failure event must report both attempts")

current = drop(16, 100)
world = world_with({current})
mover = {status = "done"}
move_results = {{"failed", "no_progress"}, {"failed", "no_progress"}}
ctx = context(20)
status, reason = loot.step(ctx, world, current, mover)
assert(status == "running" and reason == "retry", "no progress must trigger one retry")
status, reason = loot.step(ctx, world, current, mover)
assert(status == "failed" and reason == "no_progress", "repeated no progress must fail")
assert(events[#events].data.attempts == 2, "no-progress failure must not exceed one retry")

move.set_path, move.step, move.stop = saved_set_path, saved_move_step, saved_move_stop
io_module.event = saved_event
print("loot tests passed")
