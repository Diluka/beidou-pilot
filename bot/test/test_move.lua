package.path = "bot/?.lua;" .. package.path
local move = require("lib.move")
local direction
player = nil
game = {player = {
    move = function(value) assert(value == nil or value == "left" or value == "right"); direction = value end,
    stop = function() error("mover must not clear the action slot") end,
}}
local ctx = {tick = {time = 0}, game = game}
local world = {character = {x = 0, y = 0, on_ground = true}}
local mover = move.new({})
assert(move.set_path(mover, {{kind = "walk", destination = 100}}))
assert(move.step(mover, ctx, world) == "running" and direction == "right")
world.character.x = 90
assert(move.step(mover, ctx, world) == "done" and direction == nil)
world.character.x = 0
assert(move.set_path(mover, {{kind = "walk", destination = 100}}))
assert(move.step(mover, ctx, world) == "running")
ctx.tick.time = 2
assert(move.step(mover, ctx, world) == "running" and direction == nil)
assert(move.step(mover, ctx, world) == "running")
ctx.tick.time = 4
local status, reason = move.step(mover, ctx, world)
assert(status == "failed" and reason == "no_progress" and direction == nil)
assert(move.set_path(mover, {{kind = "jumpup", destination = 100}}))
status, reason = move.step(mover, ctx, world)
assert(status == "failed" and reason == "unsupported_edge")
assert(move.set_path(mover, {{kind = "walk", destination = 100}}))
assert(move.step(mover, ctx, world) == "running")
move.stop(mover)
assert(direction == nil)
assert(move.set_path(mover, {{kind = "walk"}}))
status, reason = move.step(mover, ctx, world)
assert(status == "failed" and reason == "invalid_edge" and direction == nil)
world.character.on_ground = nil
assert(move.set_path(mover, {{kind = "step", destination = 100}}))
assert(move.step(mover, ctx, world) == "running")
world.character.on_ground = true
assert(move.step(mover, ctx, world) == "running")
world.character.on_ground = false
ctx.tick.time = 5
assert(move.step(mover, ctx, world) == "running")
world.character.on_ground = true
assert(move.step(mover, ctx, world) == "done" and direction == nil)
assert(move.set_path(mover, {{kind = "walk", destination = 1000}}))
for attempt = 1, 2 do
    for i = 0, 10 do
        ctx.tick.time = 20 + (attempt - 1) * 11 + i
        world.character.x = i * 6
        status, reason = move.step(mover, ctx, world)
    end
end
assert(status == "failed" and reason == "timeout" and direction == nil)
print("move tests ok")
