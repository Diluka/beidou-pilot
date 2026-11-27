package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local io_module = require("lib.io")
local saved_poll, saved_publish, saved_event, saved_game = io_module.poll, io_module.publish, io_module.event, game
local events, inputs = {}, {}
io_module.poll = function() return {} end
io_module.publish = function() return true end
io_module.event = function(_, kind, data) events[#events + 1] = {kind = kind, data = data}; return true end
local ctx = {
    tick = {time = 0}, state = {bot = {mode = "hunt", config = {}}},
    scene = {terrain = {status = "available", navigation = dofile("bot/test/fixtures/synthetic.lua").navigation}},
    game = {
        character = {x = 50, y = 100, on_ground = true, hp = 50, max_hp = 50, mp = 10, max_mp = 10, action_idle = true},
        world = {ready = true, map_id = 102000000, scene_generation = 1},
        scene = {players = {}, mobs = {}, drops = {}}, inventory = {items = {}},
        player = {move = function(direction) inputs[#inputs + 1] = direction or "stop"; return true end,
            skill = function() return true end},
    },
}
game = ctx.game
local file = assert(io.open("bot/main.lua"))
local tick = assert(load(file:read("*a") .. "\nreturn main", "bot/main.lua"))()
file:close()
tick(ctx)
local patrol_count = 0
for _, event in ipairs(events) do if event.kind == "hunt/patrol" then patrol_count = patrol_count + 1 end end
assert(ctx.state.hunt_action == "patrol" and ctx.state.hunt_patrol and ctx.state.hunt_patrol.target,
    "empty hunt selects a patrol target")
local combat = require("lib.combat")
local saved_select, saved_combat_step = combat.select, combat.step
local mob = {object_id = 900, template_id = 1000, x = 60, y = 100, platform = 1, active = true}
combat.select = function() return mob end
combat.step = function() return "failed", "retreat_blocked" end
ctx.state.hunt_action = "combat"
ctx.state.hunt_last_platform = 1
ctx.state.hunt_patrol = {scope = "102000000:1", visited = {}, skipped = {}, attempts = {}, index = 1,
    fallback_until = math.huge}
ctx.tick.time = 1
tick(ctx)
assert(ctx.state.hunt_action == nil and ctx.state.hunt_patrol == nil,
    "failed combat must clear action and fallback immediately")
combat.select = function() return nil end
ctx.tick.time = 2
tick(ctx)
assert(ctx.state.hunt_action == "patrol" and ctx.state.hunt_patrol.target,
    "next tick after failed combat must plan patrol")
ctx.state.hunt_action = "combat"
ctx.state.hunt_patrol.fallback_until = math.huge
ctx.game.character.x, ctx.game.character.y = 130, 80
ctx.tick.time = 3
tick(ctx)
local recovered = false
for _, e in ipairs(events) do
    if e.kind == "hunt/recover" and e.data.reason == "platform_changed" and e.data.from == 1 and e.data.to == 2 then
        recovered = true
    end
end
assert(recovered and ctx.state.hunt_patrol and ctx.state.hunt_patrol.order[1] == 2
    and not ctx.state.hunt_patrol.fallback_until, "knockback must rebuild patrol on the landed platform")
ctx.state.hunt_patrol.fallback_until = math.huge
ctx.tick.time = 4
tick(ctx)
ctx.tick.time = 14
tick(ctx)
local stalled = false
for _, e in ipairs(events) do if e.kind == "hunt/stalled" and e.data.platform == 2 then stalled = true end end
assert(stalled and not ctx.state.hunt_patrol.fallback_until, "idle watchdog must clear stale fallback")
combat.select, combat.step = saved_select, saved_combat_step
io_module.poll, io_module.publish, io_module.event, game = saved_poll, saved_publish, saved_event, saved_game
local hunt = require("lib.hunt")
local terrain, move = require("lib.terrain"), require("lib.move")
local old_plan, old_set, old_step, old_stop = terrain.plan, move.set_path, move.step, move.stop
local plans, patrol_events = 0, {}
local hunt_io
for index = 1, math.huge do
    local name, value = debug.getupvalue(hunt.step, index)
    if not name then break end
    if name == "io_module" then hunt_io = value; break end
end
local old_hunt_event = hunt_io.event
hunt_io.event = function(_, name, data) patrol_events[#patrol_events + 1] = {name, data} end
terrain.plan = function(_, from, to)
    plans = plans + 1
    if to == 3 then return nil, "no_path" end
    return {{kind = "jumpup", from = from, to = to, x = 0, destination = 0, rise = 40}}
end
move.set_path = function(m, path) m.status, m.edges, m.index = "running", path, 1; return true end
move.step = function() return "running" end
move.stop = function(m) m.status = "done" end
local graph = {platforms = {{}, {}, {}}, candidates = {jumpup = {1, 2, 0, 0, 40}}}
local w = {map_id = 1, scene_generation = 1, character = {platform = 1, on_ground = true}}
local c = {state = {}, tick = {time = 0}}
local m = {status = "done"}
assert(hunt.step(c, w, graph, m) == "running" and plans == 1)
assert(hunt.step(c, w, graph, m) == "running" and plans == 1, "active route is cached")
w.character.platform = 3
assert(select(2, hunt.step(c, w, graph, m)) == "plan_throttled" and plans == 1)
c.tick.time = 1
assert(hunt.step(c, w, graph, m) == "running" and plans == 2, "displacement replans target")
w.character.platform = 2
local result, why = hunt.step(c, w, graph, m)
assert(result == "waiting" and why == "arrived")
c.tick.time = 2
result, why = hunt.step(c, w, graph, m)
assert(why == "no_path" and plans == 3, "unreachable platform is skipped")
assert(select(2, hunt.step(c, w, graph, m)) == "refresh")
c.tick.time = 8
assert(select(2, hunt.step(c, w, graph, m)) == "refresh_complete")
hunt.step(c, w, graph, m)
assert(plans == 4, "next cycle revisits reachable platforms")

local failures = {state = {}, tick = {time = 0}, game = {character = {action_idle = true},
    player = {move = function() return true end}}}
local failed_world = {map_id = 2, scene_generation = 1,
    character = {platform = 1, on_ground = true, x = 50}}
local failed_graph = {platforms = {{left = 0, right = 100}, {}, {}},
    candidates = {jumpup = {1, 2, 0, 0, 40}}}
local fm = {status = "done"}
terrain.plan = function(_, from, to, options)
    if options.blocked[from .. ":" .. to] then return nil, "no_path" end
    return {{kind = "jumpup", from = from, to = to, x = 7, destination = 7, rise = 40}}
end
assert(hunt.step(failures, failed_world, failed_graph, fm) == "running")
move.step = function(mover) mover.status, mover.reason = "failed", "no_progress"; return "failed", "no_progress" end
failures.tick.time = 1
hunt.step(failures, failed_world, failed_graph, fm)
assert(not failures.state.blocked and failures.state.hunt_patrol.attempts[2] == 1,
    "transient failure must not block an edge")
local found_edge = false
for _, e in ipairs(patrol_events) do
    if e[1] == "hunt/retry" and e[2].edge_kind == "jumpup" and e[2].edge_x == 7
        and e[2].attempts == 1 and e[2].next_attempt == 2 then found_edge = true end
end
assert(found_edge, "retry event must describe the failed edge and attempt")
failures.tick.time = 10
assert(select(2, hunt.step(failures, failed_world, failed_graph, fm)) == "fallback")
failures.tick.time = 31
assert(hunt.step(failures, failed_world, failed_graph, fm) == "running")
failures.tick.time = 32
hunt.step(failures, failed_world, failed_graph, fm)
assert(failures.state.hunt_patrol.attempts[2] == 2 and not failures.state.hunt_patrol.skipped[2])
failures.tick.time = 62
assert(hunt.step(failures, failed_world, failed_graph, fm) == "running")
failures.tick.time = 63
hunt.step(failures, failed_world, failed_graph, fm)
assert(failures.state.hunt_patrol.skipped[2] and failures.state.hunt_patrol.attempts[2] == 3)
assert(not failures.state.blocked, "transient retries must never block the edge")
local last = patrol_events[#patrol_events]
assert(last[1] == "hunt/skip" and last[2].attempts == 3)
local structural = {state = {}, tick = {time = 0}, game = failures.game}
local sm = {status = "done"}
assert(hunt.step(structural, failed_world, failed_graph, sm) == "running")
move.step = function(mover) mover.status, mover.reason = "failed", "unsupported_edge"; return "failed", "unsupported_edge" end
structural.tick.time = 1
hunt.step(structural, failed_world, failed_graph, sm)
assert(structural.state.blocked["1:2"] and structural.state.hunt_patrol.skipped[2],
    "structural edge failure blocks and skips")

local empty = {state = {}, tick = {time = 0}, game = failures.game}
local em = {status = "done"}
terrain.plan = function() return nil, "no_path" end
hunt.step(empty, failed_world, failed_graph, em)
empty.tick.time = 1
hunt.step(empty, failed_world, failed_graph, em)
empty.tick.time = 2
assert(select(2, hunt.step(empty, failed_world, failed_graph, em)) == "fallback")
local cycle_events = #patrol_events
for t = 3, 120 do empty.tick.time = t; hunt.step(empty, failed_world, failed_graph, em) end
assert(#patrol_events == cycle_events, "exhausted targets must not emit extra cycles")
assert(empty.state.hunt_patrol.skipped[2] and empty.state.blocked["1:2"], "no_path is scoped skip and block")
failed_world.scene_generation = 2
hunt.step(empty, failed_world, failed_graph, em)
assert(empty.state.hunt_patrol.scope == "2:2" and not empty.state.hunt_patrol.skipped[3],
    "scene change rebuilds patrol state")
local ranged_graph = {platforms = {{left = 0, right = 200}, {left = 0, right = 100},
    {left = 0, right = 150}}, candidates = {jumpup = {1, 2, 0, 0, 40, 1, 3, 0, 0, 40}}}
local ranged_world = {map_id = 50, scene_generation = 1, config = {attack_mode = "ranged", min_range = 60},
    character = {platform = 1, on_ground = true, x = 50}}
local ranged_ctx = {state = {}, tick = {time = 0}, game = failures.game}
local ranged_mover = {status = "done"}
terrain.plan = function(_, from, to) return {{kind = "jumpup", from = from, to = to, x = 0, destination = 0, rise = 40}} end
assert(hunt.step(ranged_ctx, ranged_world, ranged_graph, ranged_mover) == "running")
assert(ranged_ctx.state.hunt_patrol.target == 3 and ranged_ctx.state.hunt_patrol.skipped[2])
local skips = 0
for _, e in ipairs(patrol_events) do
    if e[1] == "hunt/skip" and e[2].reason == "narrow_platform" and e[2].platform == 2 then skips = skips + 1 end
end
assert(skips == 1, "narrow platform must emit a single scoped skip")
ranged_world.character.platform = 3
assert(select(2, hunt.step(ranged_ctx, ranged_world, ranged_graph, ranged_mover)) == "arrived")

terrain.plan, move.set_path, move.step, move.stop = old_plan, old_set, old_step, old_stop
hunt_io.event = old_hunt_event
io_module.event = saved_event
print("hunt tests passed")
