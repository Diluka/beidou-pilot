package.path = "bot/?.lua;bot/?/init.lua;" .. package.path

local combat = require("lib.combat")
local movement = require("lib.move")
local combat_io
for index = 1, math.huge do
    local name, value = debug.getupvalue(combat.step, index)
    if name == nil then break end
    if name == "io_module" then combat_io = value; break end
end
assert(combat_io, "combat must retain the event module")
local original_set_path, original_step, original_stop = movement.set_path, movement.step, movement.stop
local original_event = combat_io.event
local edges, calls, events = {}, {}, {}
local can_set_path = true
movement.set_path = function(mover, path)
    edges[#edges + 1] = path[1]
    if not can_set_path then return false, "no_path" end
    mover.status = "running"
    return true
end
movement.step = function(mover)
    calls[#calls + 1] = "move_step"
    return "running"
end
local test_player
movement.stop = function()
    calls[#calls + 1] = "move_stop"
    if test_player then test_player.move(nil); test_player.skill(nil) end
end
combat_io.event = function(_, kind, data)
    events[#events + 1] = {kind = kind, data = data}
    return true
end

local function entity(id, x, platform, overrides)
    local result = {
        object_id = id, template_id = 1000 + id, x = x, y = 0,
        platform = platform, active = true, hp_percent = 100,
    }
    for key, value in pairs(overrides or {}) do result[key] = value end
    return result
end
local function make_world()
    return {
        map_id = 7, scene_generation = 1,
        character = {x = 0, y = 0, platform = 1, mp = 20},
        owner = {present = true, x = 0, y = 0},
        mobs = {},
    }
end
local world = make_world()
world.mobs = {
    entity(9, 40, 1),
    entity(3, 40, 1),
    entity(1, 20, 2),
    entity(2, 301, 1),
    entity(4, 10, 1, {active = false}),
    entity(5, 10, 1, {template_id = ""}),
}
assert(combat.select(world, {}).object_id == 3, "selection must filter invalid targets and break distance ties by object_id")
assert(combat.select(world, {exclude = {3}}).object_id == 9, "excluded target must not be selected")
world.owner = {present = false}
world.mobs = {entity(1, 200, 1), entity(2, 201, 1)}
assert(combat.select(world, {}).object_id == 1, "without owner, self range includes 200px")
world.mobs = {entity(2, 201, 1)}
assert(combat.select(world, {}) == nil, "without owner, targets beyond 200px must be ignored")
world.owner = {present = true, x = 0, y = 0}
world.mobs = {entity(1, 300, 1), entity(2, 301, 1)}
assert(combat.select(world, {}).object_id == 1, "owner range includes 300px")
world.owner.x = nil
assert(combat.select(world, {}) == nil, "present owner with unavailable position cannot establish its range")

local function player_context()
    calls, edges = {}, {}
    test_player = {
        move = function(direction)
            calls[#calls + 1] = direction == nil and "move_nil" or "move_" .. direction
            return true
        end,
        skill = function(skill_id)
            calls[#calls + 1] = skill_id == nil and "skill_nil" or "skill_" .. skill_id
            return true
        end,
        attack = function() calls[#calls + 1] = "attack"; return true end,
        stop = function() error("combat must not call player.stop") end,
    }
    local context = {tick = {time = 0, index = 1}, state = {}, game = {player = test_player}}
    return context
end
local function mover()
    return {status = "done"}
end

world = make_world()
world.owner = {present = false}
world.character.x = 0
local target = entity(7, 90, 1)
world.mobs = {target}
local ctx, path_mover = player_context(), mover()
local status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "running" and reason == "approaching" and #edges == 1)
assert(edges[1].kind == "walk" and edges[1].from == 1 and edges[1].to == 1
    and edges[1].x == 0 and edges[1].destination == 90 and edges[1].rise == 0,
    "approach must ask mover for a same-platform walk edge")
world.character.x = 40
path_mover.status = "done"
ctx.tick.time = 1
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "running" and reason == "facing" and calls[#calls] == "move_right")
ctx.tick.time = 1.1
world.config = {attack_skill_id = 123}
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "running" and reason == "attacking" and calls[#calls - 1] == "move_nil"
    and calls[#calls] == "skill_123", "face for one tick, then keep the configured skill input")
ctx.tick.time = 2
combat.step(ctx, world, target, path_mover)
local skill_submissions = 0
for _, call in ipairs(calls) do if call == "skill_123" then skill_submissions = skill_submissions + 1 end end
assert(calls[#calls] == "move_nil" and skill_submissions == 1,
    "held skill must not be resubmitted every tick")
world.character.mp = 9
ctx.tick.time = 2.1
combat.step(ctx, world, target, path_mover)
assert(calls[#calls] == "attack", "low MP must use normal attack")
world.mobs = {}
assert(combat.select(world, {}) == nil and calls[#calls] == "skill_nil",
    "when selection has no target, the prior combat input must be withdrawn")
world.mobs = {target}
world.character.mp = 20
assert(combat.select(world, {}) == target, "a reappearing eligible target can be selected again")
ctx.tick.time = 2.2
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "running" and reason == "facing" and calls[#calls] == "move_right",
    "reselected target must restart facing after prior action cleanup")
ctx.tick.time = 2.3
combat.step(ctx, world, target, path_mover)
assert(calls[#calls] == "skill_123", "reselected target must restart its attack action")
world.mobs = {}
assert(combat.select(world, {}) == nil and calls[#calls] == "skill_nil",
    "when selection has no target, the prior combat input must be withdrawn")
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "done" and reason == "killed" and calls[#calls - 1] == "move_nil"
    and calls[#calls] == "skill_nil", "vanished target must finish and clear the action slot")

local function fresh_step(target_x, owner_x)
    world = make_world()
    world.character.mp = 0
    world.owner = {present = owner_x ~= nil, x = owner_x or 0, y = 0}
    local current = entity(11, target_x, 1)
    world.mobs = {current}
    ctx, path_mover = player_context(), mover()
    return current
end

target = fresh_step(50, 0)
world.mobs = {entity(12, 50, 2)}
status, reason = combat.step(ctx, world, world.mobs[1], path_mover)
assert(status == "failed" and reason == "target_platform_unreachable" and calls[#calls] == "skill_nil")

target = fresh_step(100, 0)
world.owner.x = -301
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "failed" and reason == "leash_exceeded" and calls[#calls] == "skill_nil")

target = fresh_step(50, 0)
combat.step(ctx, world, target, path_mover)
ctx.tick.time = 15
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "failed" and reason == "timeout" and calls[#calls] == "skill_nil")

target = fresh_step(50, nil)
world.owner = {present = false}
ctx.tick.time = 0
combat.step(ctx, world, target, path_mover)
ctx.tick.time = 3
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "running" and reason == "reposition" and edges[#edges].kind == "walk"
    and edges[#edges].from == edges[#edges].to and edges[#edges].destination == 80,
    "three seconds without HP progress must trigger one same-platform reposition")
ctx.tick.time = 6
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "failed" and reason == "no_progress" and events[#events].kind == "combat_no_progress"
    and calls[#calls] == "skill_nil", "a second no-progress interval must abandon, emit an event, and clear actions")
assert(combat.select(world, {}) == nil, "abandoned target must not be immediately selected again")
world.scene_generation = 2
assert(combat.select(world, {}).object_id == target.object_id, "abandonment is scoped to the current scene")

target = fresh_step(90, nil)
can_set_path = false
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "failed" and reason == "no_path" and calls[#calls] == "skill_nil",
    "a mover that cannot set the same-platform edge must fail cleanly")
can_set_path = true

world = make_world()
world.map_id = 30
world.owner = {present = true, x = 0, y = 0}
local locked_a, closer_b = entity(30, 40, 1), entity(31, 10, 1)
world.mobs = {locked_a}
ctx, path_mover = player_context(), mover()
assert(combat.select(world, {}) == locked_a)
combat.step(ctx, world, locked_a, path_mover)
world.mobs = {closer_b, locked_a}
assert(combat.select(world, {}) == locked_a,
    "a valid locked object_id must not be displaced by a closer target")
world.mobs = {closer_b}
assert(combat.select(world, {}) == closer_b, "a disappeared lock must release and select the next target")

world = make_world()
world.map_id = 31
world.owner = {present = true, x = 0, y = 0}
locked_a, closer_b = entity(32, 40, 1), entity(33, 520, 1)
world.mobs = {locked_a}
ctx, path_mover = player_context(), mover()
assert(combat.select(world, {}) == locked_a)
combat.step(ctx, world, locked_a, path_mover)
world.mobs = {locked_a, closer_b}
world.owner.x = 500
assert(combat.select(world, {}) == closer_b, "a lock beyond the owner leash must be released")

world = make_world()
world.map_id = 32
world.owner = {present = true, x = 0, y = 0}
locked_a, closer_b = entity(34, 40, 1), entity(35, 10, 1)
world.mobs = {locked_a}
ctx, path_mover = player_context(), mover()
assert(combat.select(world, {}) == locked_a)
combat.step(ctx, world, locked_a, path_mover)
world.mobs = {locked_a, closer_b}
locked_a.active = false
status, reason = combat.step(ctx, world, locked_a, path_mover)
assert(status == "done" and reason == "killed" and combat.select(world, {}) == closer_b,
    "step completion must clear the lock before selecting another target")

world = make_world()
world.map_id = 33
world.owner = {present = true, x = 0, y = 0}
locked_a, closer_b = entity(36, 40, 1), entity(37, 10, 1)
world.mobs = {locked_a}
ctx, path_mover = player_context(), mover()
assert(combat.select(world, {}) == locked_a)
combat.step(ctx, world, locked_a, path_mover)
world.mobs = {locked_a, closer_b}
locked_a.platform = 2
status, reason = combat.step(ctx, world, locked_a, path_mover)
assert(status == "failed" and reason == "target_platform_unreachable" and combat.select(world, {}) == closer_b,
    "step failure must clear the lock before selecting another target")

movement.set_path, movement.step, movement.stop = original_set_path, original_step, original_stop
combat_io.event = original_event
print("combat tests passed")
