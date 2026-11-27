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
    entity(1, 310, 2),
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
assert(combat.select(world, {hunt = true}).object_id == 2, "hunt selects visible targets beyond assist range")
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
    local context = {tick = {time = 0, index = 1}, state = {}, game = {player = test_player, character = {action_idle = true}}}
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
assert(status == "failed" and reason == "no_path" and calls[#calls] == "skill_nil")

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
assert(status == "failed" and reason == "no_path" and combat.select(world, {}) == closer_b,
    "step failure must clear the lock before selecting another target")

-- 远程/技能：有效射程 = 弓弩基础射程 110 + 已学「远程箭」（3000002）每级 15。
local function ranged_fixture(object_id, target_x, config, skills, complete)
    world = make_world()
    world.owner = {present = false}
    world.config = config
    local current = entity(object_id, target_x, 1)
    world.mobs = {current}
    ctx, path_mover = player_context(), mover()
    ctx.game.character = {skills = skills or {}, skills_complete = complete ~= false, action_idle = true}
    ctx.state.graph = {platforms = {{left = -200, right = 200}}, walls = {}, model = {stand_height = 40}}
    return current
end

local target_in_base = ranged_fixture(40, 100, {attack_mode = "ranged"})
status, reason = combat.step(ctx, world, target_in_base, path_mover)
assert(status == "running" and reason == "facing" and #edges == 0,
    "a target inside the 110px base range must stop and face instead of approaching")
ctx.tick.time = 0.1
status, reason = combat.step(ctx, world, target_in_base, path_mover)
assert(status == "running" and reason == "attacking" and calls[#calls] == "attack",
    "a target inside the base range must be attacked without a skill")

local target_mid = ranged_fixture(41, 150, {attack_mode = "ranged"})
status, reason = combat.step(ctx, world, target_mid, path_mover)
assert(status == "running" and reason == "approaching" and #edges == 1
    and edges[1].destination == 150, "a target beyond the base range must be approached")
local fired = false
for _, call in ipairs(calls) do
    if call == "attack" or call:match("^skill_%d+$") then fired = true end
end
assert(not fired, "no attack may be issued while the target is out of range")

local target_far = ranged_fixture(42, 200, {attack_mode = "ranged"})
status, reason = combat.step(ctx, world, target_far, path_mover)
assert(status == "running" and reason == "approaching" and #edges == 1,
    "the old 200px default must no longer be used as a base range")

local learned = {["3000002"] = {level = 4}}
local target_partial = ranged_fixture(43, 180, {attack_mode = "ranged"}, learned)
status, reason = combat.step(ctx, world, target_partial, path_mover)
assert(status == "running" and reason == "approaching",
    "4/8 ranged skill levels add 60px, so 180px is still out of range")

learned = {["3000002"] = {level = 8}}
local target_learned = ranged_fixture(44, 200, {attack_mode = "ranged"}, learned)
status, reason = combat.step(ctx, world, target_learned, path_mover)
assert(status == "running" and reason == "facing",
    "8/8 ranged skill levels add 120px, so 200px is inside the effective range")
ctx.tick.time = 0.1
status, reason = combat.step(ctx, world, target_learned, path_mover)
assert(status == "running" and reason == "attacking" and calls[#calls] == "attack",
    "a learned ranged skill must raise the attack range")

local target_fallback = ranged_fixture(45, 200,
    {attack_mode = "ranged", ranged_skill_level = 8}, nil, false)
status, reason = combat.step(ctx, world, target_fallback, path_mover)
assert(status == "running" and reason == "facing",
    "when the skill list is unreadable the configured skill level must be used")
ctx.tick.time = 0.1
status, reason = combat.step(ctx, world, target_fallback, path_mover)
assert(status == "running" and reason == "attacking" and calls[#calls] == "attack")

local target_close = ranged_fixture(46, 40, {attack_mode = "ranged"})
status, reason = combat.step(ctx, world, target_close, path_mover)
assert(status == "running" and reason == "retreating" and edges[1].destination == -30,
    "a close target must trigger a bounded retreat through the mover")

local blocked = ranged_fixture(146, 40, {attack_mode = "ranged"})
world.map_id = 146
ctx.state.graph.platforms[1].left = -10
world.character.hp, world.character.max_hp = 20, 100
ctx.state.bot = {mode = "hunt", config = world.config}
world.now = 0
assert(combat.select(world, {hunt = true}) == blocked)
status, reason = combat.step(ctx, world, blocked, path_mover)
assert(status == "failed" and reason == "retreat_blocked")
local event = events[#events]
assert(event.kind == "combat/retreat_blocked" and event.data.reason == "insufficient_space"
    and event.data.platform == 1 and event.data.retreat_distance == 10 and event.data.target_distance == 40)
for _, call in ipairs(calls) do assert(call ~= "attack" and not call:match("^skill_%d+$")) end
local alternative_blocked = entity(149, 100, 1)
world.mobs = {blocked, alternative_blocked}
assert(combat.select(world, {hunt = true}) == alternative_blocked, "blocked target must yield immediately")
world.mobs = {blocked}
world.now = 9
assert(combat.select(world, {hunt = true}) == nil, "cooldown must suppress the target")
world.now = 10
assert(combat.select(world, {hunt = true}) == blocked, "target must be eligible after cooldown")

local wall_target = ranged_fixture(147, 40, {attack_mode = "ranged"})
ctx.state.graph.walls = {-15, -40, 0}
status, reason = combat.step(ctx, world, wall_target, path_mover)
assert(status == "failed" and reason == "retreat_blocked" and events[#events].data.retreat_distance == 15)

local narrow_target = ranged_fixture(148, 80, {attack_mode = "ranged"})
ctx.state.bot = {mode = "hunt", config = world.config}
ctx.state.graph.platforms[1] = {left = -50, right = 50}
status, reason = combat.step(ctx, world, narrow_target, path_mover)
assert(status == "failed" and reason == "narrow_platform", "hunt must not attack a narrow platform")
for _, call in ipairs(calls) do assert(call ~= "attack" and not call:match("^skill_%d+$")) end

local target_edge = ranged_fixture(47, 65, {attack_mode = "ranged"})
status, reason = combat.step(ctx, world, target_edge, path_mover)
assert(status == "running" and reason == "facing" and calls[#calls] == "move_right",
    "65px is inside range with the 60px min range and must not retreat")

local target_mp = ranged_fixture(48, 100,
    {attack_mode = "skill", attack_skill_id = 3001004, skill_mp_cost = 10})
world.character.mp = 5
status, reason = combat.step(ctx, world, target_mp, path_mover)
assert(status == "running" and reason == "facing")
ctx.tick.time = 0.1
status, reason = combat.step(ctx, world, target_mp, path_mover)
assert(status == "running" and reason == "attacking" and calls[#calls] == "attack",
    "insufficient MP must fall back to a normal attack")
world.character.mp = 20
ctx.tick.time = 0.2
status, reason = combat.step(ctx, world, target_mp, path_mover)
assert(status == "running" and reason == "attacking" and calls[#calls] == "skill_3001004",
    "restored MP must switch the skill mode back to the skill")

learned = {["3000002"] = {level = 8}}
local target_skill_range = ranged_fixture(49, 200,
    {attack_mode = "skill", attack_skill_id = 3001004}, learned)
status, reason = combat.step(ctx, world, target_skill_range, path_mover)
assert(status == "running" and reason == "facing")
ctx.tick.time = 0.1
status, reason = combat.step(ctx, world, target_skill_range, path_mover)
assert(status == "running" and reason == "attacking" and calls[#calls] == "skill_3001004",
    "skill mode must use the same skill-derived range")

-- Ranged hunt selects a visible cross-platform target without pursuing it.
world = make_world()
world.map_id = 155
world.character.on_ground = true
world.owner = {present = false}
world.mobs = {entity(200, 90, 2), entity(201, 65, 1)}
ctx, path_mover = player_context(), mover()
ctx.state.bot = {mode = "hunt", config = {attack_mode = "ranged"}}
ctx.state.graph = {platforms = {{left = -200, right = 200}, {left = 80, right = 200}}, walls = {}}
local opts = {hunt = true, config = ctx.state.bot.config, graph = ctx.state.graph, context = ctx}
assert(combat.select(world, opts) == world.mobs[1], "cross platform must outrank closer local target")
local selected_event = events[#events]
assert(selected_event.kind == "combat/ranged_target" and selected_event.data.platform == 2
    and selected_event.data.horizontal_distance == 90 and selected_event.data.cross_platform == true)
status, reason = combat.step(ctx, world, world.mobs[1], path_mover)
assert(status == "running" and reason == "facing" and #edges == 0)
ctx.tick.time = 0.1
status, reason = combat.step(ctx, world, world.mobs[1], path_mover)
assert(reason == "attacking" and calls[#calls] == "attack" and #edges == 0)
world.mobs[1].x = 150
status, reason = combat.step(ctx, world, world.mobs[1], path_mover)
assert(status == "failed" and reason == "range_blocked" and calls[#calls] == "skill_nil" and #edges == 0,
    "moving out of range must release attack without pursuing")
ctx.tick.time = 6
ctx.game.character.skills = {["3000002"] = {level = 4}}
assert(combat.select(world, opts) == world.mobs[1], "learned range must be used on the first selection")
ctx.game.character.skills = nil
for _, case in ipairs({
    {reason = "out_of_range", x = 150}, {reason = "height_difference", y = 41},
    {reason = "wall", wall = {40, -40, 0}}, {reason = "platform_boundary", left = -10},
}) do
    world.scene_generation = world.scene_generation + 1
    world.mobs = {entity(202, case.x or 90, 2)}
    world.mobs[1].y = case.y or 0
    ctx.state.graph.platforms[1].left = case.left or -200
    ctx.state.graph.walls = case.wall or {}
    ctx.tick.time = ctx.tick.time + 6
    assert(combat.select(world, opts) == nil, case.reason .. " must not be selected")
    local e = events[#events]
    assert(e.kind == "combat/range_blocked" and e.data.reason == case.reason)
    status, reason = combat.step(ctx, world, world.mobs[1], path_mover)
    assert(status == "failed" and reason == "range_blocked" and #edges == 0)
end

-- Cross-platform planning uses the same mover and keeps the target locked.
local terrain = require("lib.terrain")
local original_plan = terrain.plan
local planned = 0
terrain.plan = function(graph, from, to)
    assert(graph == ctx.state.graph and from == 1 and to == 2)
    planned = planned + 1
    return {{kind = "jumpup", from = 1, to = 2, x = 0, destination = 30, rise = 40}}
end
world = make_world()
world.map_id = 100
world.owner = {present = false}
target = entity(100, 30, 2)
world.mobs = {target}
ctx, path_mover = player_context(), mover()
ctx.state.graph = {}
assert(combat.select(world, {}) == target, "cross-platform target must be selectable")
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "running" and planned == 1 and edges[1].to == 2,
    "cross-platform pursuit must plan and submit a route")
world.mobs = {entity(101, 5, 1), target}
assert(combat.select(world, {}) == target, "cross-platform lock must survive closer same-platform mobs")
world.character.platform = 2
calls = {}
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "running" and calls[1] == "move_step" and #calls == 1,
    "reaching the target platform must not interrupt an unfinished transition")
movement.step = function(mover)
    calls[#calls + 1] = "move_step"
    mover.status = "done"
    return "done"
end
calls = {}
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "running" and reason == "facing" and calls[1] == "move_step",
    "combat may resume after the transition completes")
movement.step = function(mover)
    calls[#calls + 1] = "move_step"
    return "running"
end

world = make_world()
world.map_id = 101
world.owner = {present = false}
target = entity(102, 20, 2)
local alternative = entity(103, 50, 1)
world.mobs = {target, alternative}
ctx, path_mover = player_context(), mover()
ctx.state.graph = {}
terrain.plan = function() return nil, "no_path" end
assert(combat.select(world, {}) == target)
status, reason = combat.step(ctx, world, target, path_mover)
assert(status == "failed" and reason == "no_path")
assert(combat.select(world, {}) == alternative, "unreachable target must be skipped in favor of the next one")
terrain.plan = original_plan

for _, busy in ipairs({"attacking", "action_idle"}) do
    target = fresh_step(50, nil)
    world.map_id = busy == "attacking" and 102 or 103
    ctx.game.character = {attacking = busy == "attacking", action_idle = busy ~= "action_idle"}
    status, reason = combat.step(ctx, world, target, path_mover)
    assert(status == "running" and reason == "action_busy")
    for _, call in ipairs(calls) do
        assert(call == "move_nil" or call == "skill_nil" or call == "move_stop",
            "attack animation must not submit directional movement or another attack")
    end
end

movement.set_path, movement.step, movement.stop = original_set_path, original_step, original_stop
combat_io.event = original_event
print("combat tests passed")
