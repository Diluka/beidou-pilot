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
local function at(time, expected)
    ctx.tick.time = time
    tick(ctx)
    assert(inputs[#inputs] == expected, ("at %s expected %s got %s"):format(time, expected, tostring(inputs[#inputs])))
end
at(0, "right")
at(1.9, "right")
at(2, "stop")
at(4.9, "stop")
at(5, "left")
at(6.9, "left")
at(7, "stop")
local empty_count = 0
for _, event in ipairs(events) do if event.kind == "hunt/empty" then empty_count = empty_count + 1 end end
assert(empty_count == 1, "continuous empty patrol emits one event")
ctx.game.character.attacking = true
at(10, "stop")
ctx.game.character.attacking = false
ctx.game.character.action_idle = false
at(10.1, "stop")
io_module.poll, io_module.publish, io_module.event, game = saved_poll, saved_publish, saved_event, saved_game
print("hunt tests passed")
