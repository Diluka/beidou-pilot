package.path = "bot/?.lua;bot/?/init.lua;" .. package.path

-- Use the runtime entry itself. Only mailbox/files, clock, scene snapshots and native input are fixtures.
local source = assert(io.open("bot/main.lua", "r"))
local main = assert(load(source:read("*a") .. "\nreturn main", "@bot/main.lua"))()
source:close()
local fixture = dofile("bot/test/fixtures/synthetic.lua")
local io_module = require("lib.io")
local saved_poll, saved_publish, saved_event = io_module.poll, io_module.publish, io_module.event
local saved_open, saved_game = io.open, game
local root = "/synthetic/target-test"
local targets = [[
102000000:target-test:1:portal:路口=175,80
102000000:point:路口=10,100
102000000:point:边缘=102,80
102000000:target-test:2:portal:旧门=95,100
102000000:different-client:1:portal:其他实例=95,100
102000000:target-test:1:portal:双门=95,100
102000000:target-test:1:portal:双门=175,80
999:point:其他地图=95,100
]]
io.open = function(path, mode)
    assert(mode == nil or mode == "r" or mode == "rb", "target navigation may only read files")
    if path ~= root .. "/targets.conf" then return nil end
    return {lines = function() return targets:gmatch("[^\n]+") end,
        read = function(_, format) assert(format == "*a" or format == "a"); return targets end,
        close = function() return true end}
end

local pending, events, input
io_module.poll = function()
    local commands = pending
    pending = {}
    return commands
end
io_module.publish = function() return true end
io_module.event = function(_, kind, data)
    events[#events + 1] = {kind = kind, reason = data.reason}
    return true
end

local function event_count(kind, reason)
    local n = 0
    for _, event in ipairs(events) do
        if event.kind == kind and (not reason or reason == event.reason) then n = n + 1 end
    end
    return n
end

local function scenario(kind, target, x, y)
    pending = {{id = "synthetic-command", source = "host", kind = kind, target = target, _ok = true}}
    events, input = {}, {moves = 0, pickups = 0}
    game = {
        player = {
            move = function(direction)
                input.direction = direction
                if direction then input.moves = input.moves + 1 end
                return true
            end,
            stop = function() input.direction = nil; return true end,
            skill = function(id) assert(id == nil, "unexpected skill"); return true end,
            pickup = function() input.pickups = input.pickups + 1; return true end,
        },
        -- Runtime JSON can supply integral IDs as Lua floats; config keys still use decimal integers.
        world = {ready = true, map_id = fixture.map_id + 0.0, scene_generation = fixture.scene_generation + 0.0},
        character = {x = x, y = y, on_ground = true, action_idle = true, hp = 100, max_hp = 100, mp = 100, max_mp = 100,
            movement = {max_speed = 125, max_jump_height = 75}},
        scene = {npcs = {}, monsters = {}, drops = {}, players = {}, players_complete = true},
        inventory = {items = {}},
    }
    return {state = {bot_root = root}, game = game, tick = {time = 0, index = 0, scene_generation = fixture.scene_generation},
        scene = {instance_id = "target-test", map_id = fixture.map_id, scene_generation = fixture.scene_generation,
            terrain = {status = "available", navigation = fixture.navigation}}}
end

local function tick(ctx, dt)
    ctx.tick.index = ctx.tick.index + 1
    ctx.tick.time = ctx.tick.time + (dt or 0.05)
    main(ctx)
end

local function assert_terminal(ctx, kind, reason)
    assert(event_count(kind, reason) == 1, "expected one " .. kind .. "/" .. reason)
    assert(event_count("target/arrived") + event_count("target/wait") == 1, "contradictory terminal events")
    assert(ctx.state.bot.mode == "idle" and input.direction == nil, "terminal state must be idle with input released")
    local moves, plans = input.moves, event_count("target/plan")
    for _ = 1, 3 do tick(ctx, 1) end
    assert(ctx.state.bot.mode == "idle" and input.moves == moves and event_count("target/plan") == plans
        and event_count("target/arrived") + event_count("target/wait") == 1, "idle replayed a finished command")
end

-- Exact name beats the nearby prefix match; numeric selectors use template ID, not object ID.
for _, target in ipairs({"npc:导游", "npc:12101"}) do
    local ctx = scenario("follow", target, 5, 100)
    ctx.game.scene.npcs = {
        {object_id = 12101, template_id = 999, name = "导游助手", x = 7, y = 100},
        {object_id = 42, template_id = 12101.0, name = "导游", x = 95, y = 100},
    }
    tick(ctx)
    assert(event_count("target/plan") == 1 and input.direction == "right", "must approach " .. target)
    tick(ctx)
    assert(event_count("target/plan") == 1, "stationary NPC must not cause a plan every tick")
    ctx.game.character.x, ctx.game.character.on_ground = 94, false
    tick(ctx)
    assert(event_count("target/arrived") == 0 and ctx.state.bot.mode == "follow", "airborne is not arrived")
    ctx.game.character.on_ground = true
    tick(ctx)
    assert_terminal(ctx, "target/arrived", "arrived")
end

-- An interrupted route must not keep walking while sustain owns the tick.
local interrupted = scenario("follow", "point:路口", 95, 100)
tick(interrupted)
assert(input.direction == "left")
interrupted.game.character.hp = 5
tick(interrupted)
assert_terminal(interrupted, "target/wait", "no_potion")

-- The selected NPC vanished; another NPC with the same name/template is not the selected object.
local ctx = scenario("follow", "npc:商人", 5, 100)
ctx.game.scene.npcs = {{object_id = 57, template_id = 800, name = "商人", x = 97, y = 100}}
tick(ctx)
assert(input.direction == "right", "NPC must first be acquired")
ctx.game.scene.npcs = {{object_id = 58, template_id = 800, name = "商人", x = 5, y = 100}}
tick(ctx)
assert_terminal(ctx, "target/wait", "target_disappeared")

-- Portal and named point may share a name. A* lands at x=120; the portal is farther along platform 2.
ctx = scenario("follow", "portal:路口", 10, 100)
tick(ctx)
assert(event_count("target/plan") == 1 and input.direction == "right", "portal must start cross-platform travel")
ctx.game.character.x, ctx.game.character.y = 120, 80
tick(ctx)
tick(ctx)
assert(ctx.state.bot.mode == "follow" and input.direction == "right" and event_count("target/arrived") == 0,
    "landing on the destination platform must still drive the last segment")
ctx.game.character.x = 145 -- 30px is within normal stop_distance but outside this portal's interaction box.
tick(ctx)
assert(ctx.state.bot.mode == "follow" and input.direction == "right", "portal must use its interaction bounds")
ctx.game.character.x = 174
tick(ctx)
assert_terminal(ctx, "target/arrived", "arrived")

ctx = scenario("follow", "point:路口", 95, 100)
tick(ctx)
assert(input.direction == "left" and event_count("target/plan") == 1, "named point uses its own coordinates")
ctx.game.character.x = 12
tick(ctx)
assert_terminal(ctx, "target/arrived", "arrived")

-- Both positions are within stop_distance, but lie on opposite sides of a platform boundary.
ctx = scenario("follow", "point:边缘", 98, 100)
tick(ctx)
assert(ctx.state.bot.mode == "follow" and event_count("target/arrived") == 0, "nearby on the wrong platform is not arrived")
ctx.game.character.x, ctx.game.character.y = 103, 80
tick(ctx)
assert_terminal(ctx, "target/arrived", "arrived")

for _, missing in ipairs({"npc:不存在", "point:其他地图", "portal:旧门", "portal:其他实例"}) do
    ctx = scenario("follow", missing, 5, 100)
    tick(ctx)
    assert(input.moves == 0, "unresolved target must not move: " .. missing)
    assert_terminal(ctx, "target/wait", "no_target")
end

ctx = scenario("follow", "portal:双门", 5, 100)
tick(ctx)
assert(input.moves == 0, "ambiguous portal must not pick a destination")
assert_terminal(ctx, "target/wait", "ambiguous_target")

-- The fixture has directed 1->2->3->4 edges and no way back from platform 4 to 1.
ctx = scenario("follow", "point:路口", 285, 160)
tick(ctx)
assert(input.moves == 0, "unreachable point must not be approached by walking across platforms")
assert_terminal(ctx, "target/wait", "no_path")

-- Invalidate an in-flight route before evaluating the same coordinates in a new scene generation.
ctx = scenario("follow", "portal:路口", 10, 100)
tick(ctx)
assert(input.direction == "right")
ctx.game.world.scene_generation, ctx.scene.scene_generation, ctx.tick.scene_generation = 2, 2, 2
ctx.game.character.x, ctx.game.character.y = 175, 80
tick(ctx)
assert(event_count("target/arrived") == 0 and input.direction == nil and ctx.state.bot.mode == "idle",
    "old portal coordinates and held input must not survive a scene generation change")

-- No selectable mob or loot (nonempty snapshots) waits in hunt; recheck later without a new command.
ctx = scenario("hunt", nil, 10, 100)
ctx.game.scene.monsters = {{object_id = 9, template_id = 100, active = false, x = 10, y = 100}}
ctx.game.scene.drops = {{object_id = 11, item_id = 400, landed = false, x = 15, y = 100}}
tick(ctx)
assert(ctx.state.bot.mode == "hunt" and event_count("hunt/empty") == 1 and input.direction == "right")
ctx.game.scene.drops[1].landed = true
tick(ctx, 0.001)
assert(ctx.state.bot.mode == "hunt" and input.pickups > 0, "hunt must resume immediately when a selectable drop appears")

io_module.poll, io_module.publish, io_module.event = saved_poll, saved_publish, saved_event
io.open, game = saved_open, saved_game
print("target navigation and hunt wait contracts ok")
