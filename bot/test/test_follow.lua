package.path = "bot/?.lua;bot/?/init.lua;" .. package.path

local io_module = require("lib.io")
local saved_event = io_module.event
local events = {}
io_module.event = function(_, kind, data)
    events[#events + 1] = {kind = kind, data = data}
    return true
end

local follow = require("lib.follow")
local function context(players)
    return {
        tick = {time = 0},
        state = {bot = {config = {}}},
        game = {
            scene = {players = players},
            player = setmetatable({}, {__index = function() error("follow must not access player") end}),
        },
    }
end

local function world(distance, owner_id, owner_name, platform)
    if platform == nil then platform = 1 elseif platform == false then platform = nil end
    return {
        character = {x = 100, y = 200, platform = 1},
        owner = {
            present = true,
            character_id = owner_id,
            name = owner_name,
            x = 100 + distance,
            y = 300,
            platform = platform,
        },
    }
end

local function assert_wait(action, reason)
    assert(action.kind == "wait" and action.reason == reason,
        ("expected wait/%s, got %s/%s"):format(reason, tostring(action.kind), tostring(action.reason)))
end

local ctx = context({{character_id = 12, name = "Owner", x = 221, y = 300}})
local action = follow.update(ctx, world(121, 12, "Owner"))
assert(action.kind == "move" and action.x == 221 and action.y == 300 and action.stop_distance == 40,
    "an owner more than 80 pixels away must produce a move action")

ctx = context({
    {character_id = 13, name = "Owner", x = 999, y = 500},
    {character_id = 12, name = "Renamed", x = 221, y = 300},
})
action = follow.update(ctx, world(121, 12, "Owner"))
assert(action.kind == "move" and action.x == 221,
    "when both IDs are available, matching must use the character ID rather than the name")

ctx = context({{name = "Owner", x = 221, y = 300}})
action = follow.update(ctx, world(121, 12, "Owner"))
assert(action.kind == "move" and action.x == 221,
    "when either ID is unavailable, matching must fall back to the exact name")

ctx = context({{character_id = 12, name = "Owner", x = 139, y = 200}})
action = follow.update(ctx, world(39, 12, "Owner"))
assert_wait(action, "close_enough")

ctx.game.scene.players[1].x = 140
action = follow.update(ctx, world(40, 12, "Owner"))
assert_wait(action, "deadband")
ctx.game.scene.players[1].x = 180
action = follow.update(ctx, world(80, 12, "Owner"))
assert_wait(action, "deadband")
ctx.game.scene.players[1].x = 220
ctx.game.scene.players[1].y = 300
action = follow.update(ctx, world(120, 12, "Owner"))
assert(action.kind == "move" and action.x == 220 and action.y == 300 and action.stop_distance == 40,
    "the locked 40/80 boundaries and 120-pixel move case must be preserved")

ctx = context({{character_id = 13, name = "Owner", x = 500, y = 300}})
action = follow.update(ctx, world(200, 12, "Owner"))
assert_wait(action, "owner_absent")

action = follow.update(context({}), {
    character = {x = 0, y = 0},
    owner = {present = false, character_id = 12, name = "Owner"},
})
assert_wait(action, "owner_absent")

action = follow.update(context({{character_id = 12, name = "Owner", x = 100, y = 200}}),
    world(121, 12, "Owner", false))
assert_wait(action, "owner_platform_unknown")

-- An absent owner is recorded after the initial 30-second interval, then throttled.
local absent_context = context({})
local absent_world = {character = {x = 0, y = 0}, owner = {present = false, character_id = 12, name = "Owner"}}
for now = 0, 31 do
    absent_context.tick.time = now
    action = follow.update(absent_context, absent_world)
    assert_wait(action, "owner_absent")
end
assert(#events == 1 and events[1].kind == "owner_absent" and events[1].data.reason == "owner_absent",
    "one event must be logged during the first 31 seconds of continuous absence")
absent_context.tick.time = 59
follow.update(absent_context, absent_world)
assert(#events == 1, "owner absence events must be throttled to 30 seconds")
absent_context.tick.time = 60
follow.update(absent_context, absent_world)
assert(#events == 2, "a continuing absence must be logged again after another 30 seconds")

absent_context.game.scene.players = {{character_id = 12, name = "Owner", x = 221, y = 100}}
absent_context.tick.time = 61
action = follow.update(absent_context, world(121, 12, "Owner"))
assert(action.kind == "move" and absent_context.state.follow_owner_absent_since == nil
    and absent_context.state.follow_owner_absent_event_at == nil,
    "finding the owner must clear the absence event throttle")
absent_context.game.scene.players = {}
absent_context.tick.time = 62
follow.update(absent_context, absent_world)
absent_context.tick.time = 91
follow.update(absent_context, absent_world)
assert(#events == 2, "a new absence episode must start its own 30-second interval")
absent_context.tick.time = 92
follow.update(absent_context, absent_world)
assert(#events == 3, "a new absence episode must eventually emit its event")

-- Exercise the real follow -> plan -> mover pipeline with disconnected platforms.
local terrain = require("lib.terrain")
local raw_plan, raw_poll, raw_publish, raw_game = terrain.plan, io_module.poll, io_module.publish, game
local plans, inputs = 0, {}
terrain.plan = function(...)
    plans = plans + 1
    return raw_plan(...)
end
io_module.poll = function() return {} end
io_module.publish = function() return true end
local owner = {character_id = 12, x = 275, y = 160}
local navigation = dofile("bot/test/fixtures/synthetic.lua").navigation
ctx = context({owner})
ctx.state.bot = {mode = "follow", target = "12", config = {metrics_enabled = 0}}
ctx.scene = {terrain = {status = "available", navigation = navigation}}
-- Start on the wide platform 1, remove outgoing edges, and place the owner on 4.
navigation.candidates = {walk = {}, step = {}, jumpup = {}, drop = {}, rope = {}}
ctx.game.character = {x = 1, y = 100, hp = 50, max_hp = 50, mp = 10, max_mp = 10,
    movement = {max_speed = 100, max_jump_height = 50}}
ctx.game.world = {ready = true, map_id = 102000000, scene_generation = 1}
ctx.game.inventory = {items = {}}
ctx.game.player = {move = function(dir) if dir then inputs[#inputs + 1] = dir end; return true end,
    skill = function(id) assert(id == nil); return true end}
game = ctx.game
local main_file = assert(io.open("bot/main.lua"))
local tick = assert(load(main_file:read("*a") .. "\nreturn main", "bot/main.lua"))()
main_file:close()
events = {}
for now = 0, 31 do
    ctx.tick.time = now
    owner.x = now % 2 == 0 and 275 or 290
    tick(ctx)
    assert(ctx.state.bot.mode == "follow" and ctx.state.bot.last_error == nil,
        "no path to the owner is a wait, not a follow error")
    assert(#inputs == 0 and plans == 1, "do not move or replan for the same unreachable platform")
    if now == 0 then
        assert(#events == 1 and events[1].data.reason == "owner_platform_unreachable")
    end
end
assert(#events == 2 and events[2].data.reason == "owner_platform_unreachable", "throttle the wait event")
ctx.game.world.scene_generation = 2
tick(ctx)
assert(plans == 2 and #inputs == 0, "a new scene generation must recheck the same platform pair")
owner.x, owner.y = 98, 100
tick(ctx)
assert(plans == 3 and inputs[1] == "right", "follow must resume walking when the owner returns to platform 1")
assert(ctx.state.bot.mode == "follow" and ctx.state.bot.last_error == nil)
-- An empty cross-platform result must also stop the old walk, not signal arrival.
terrain.plan = function() plans = plans + 1; return {} end
owner.x, owner.y, ctx.tick.time = 275, 160, 62
tick(ctx)
assert(plans == 4 and #inputs == 1 and ctx.state.mover.status == "done" and ctx.state.path_target == nil)
assert(events[#events].data.reason == "owner_platform_unreachable" and ctx.state.bot.last_error == nil)
terrain.plan, io_module.poll, io_module.publish, game = raw_plan, raw_poll, raw_publish, raw_game
io_module.event = saved_event
print("follow tests ok")
