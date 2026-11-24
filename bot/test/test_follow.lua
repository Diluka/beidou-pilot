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
        state = {},
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

ctx = context({{character_id = 12, name = "Owner", x = 139, y = 999}})
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

io_module.event = saved_event
print("follow tests ok")
