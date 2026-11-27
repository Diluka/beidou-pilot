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
assert(failures.state.blocked["1:2"], "failed edge must be blocked")
local found_edge = false
for _, e in ipairs(patrol_events) do
    if e[1] == "hunt/recover" and e[2].edge_kind == "jumpup" and e[2].edge_x == 7 then found_edge = true end
end
assert(found_edge, "failure event must describe the failed edge")
failures.state.hunt_failures = 3
failures.tick.time = 2
assert(select(2, hunt.step(failures, failed_world, failed_graph, fm)) == "fallback")
failures.tick.time = 10
assert(select(2, hunt.step(failures, failed_world, failed_graph, fm)) == "fallback")

local empty = {state = {}, tick = {time = 0}, game = failures.game}
local em = {status = "done"}
terrain.plan = function() return nil, "no_path" end
hunt.step(empty, failed_world, failed_graph, em)
empty.tick.time = 1
hunt.step(empty, failed_world, failed_graph, em)
empty.tick.time = 2
assert(select(2, hunt.step(empty, failed_world, failed_graph, em)) == "refresh")
local cycle_events = #patrol_events
for t = 3, 31 do empty.tick.time = t; hunt.step(empty, failed_world, failed_graph, em) end
assert(#patrol_events == cycle_events, "refresh wait must not emit extra cycles")
empty.tick.time = 32
assert(select(2, hunt.step(empty, failed_world, failed_graph, em)) == "refresh_complete")
assert(next(empty.state.hunt_patrol.skipped) == nil, "new cycle clears skips")
terrain.plan, move.set_path, move.step, move.stop = old_plan, old_set, old_step, old_stop
hunt_io.event = old_hunt_event
io_module.event = saved_event
print("hunt tests passed")
