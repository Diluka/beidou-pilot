package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local events = {}
package.loaded["lib.sustain"] = nil
package.loaded["lib.io"] = {event = function(_, _, data) events[#events + 1] = data.reason end}
local sustain = require("lib.sustain")
local calls = {}
local ctx = {state = {sustain = {config = {hp_item = 1, mp_item = 2}}}, game = {player = {
    use_item = function(id) calls[#calls + 1] = id end,
    skill = function() calls[#calls + 1] = "clear" end,
    revive = function() calls[#calls + 1] = "revive" end,
}}}
local world = {now = 0, character = {hp = 50, max_hp = 100, mp = 100, max_mp = 100},
    inventory = {{item_id = 1, quantity = 1}, {item_id = 2, quantity = 1}}}
local handled, reason = sustain.step(ctx, world)
assert(handled and reason == "hp_potion" and calls[#calls] == 1)
world.character.hp = 65
assert(sustain.step(ctx, world))
world.character.hp = 66
assert(not sustain.step(ctx, world) and calls[#calls] == "clear")
world.character.mp = 20
handled, reason = sustain.step(ctx, world)
assert(handled and reason == "mp_potion" and calls[#calls] == 2)
world.inventory = {{item_id = 2}, {item_id = 2, quantity = 0}}
handled, reason = sustain.step(ctx, world)
assert(handled and reason == "no_potion" and calls[#calls] == "clear")
world.character.hp = 0
handled, reason = sustain.step(ctx, world)
assert(handled and reason == "reviving" and calls[#calls] == "revive")
world.now = 10
handled, reason = sustain.step(ctx, world)
assert(handled and reason == "revive_unknown" and events[1] == "revive_unknown")
local count = #calls
sustain.step(ctx, world)
assert(#calls == count and #events == 1)
ctx.state.sustain = {config = {hp_item = 1, mp_item = 2}}
world.now = 20
sustain.step(ctx, world)
world.character.hp, world.character.mp = 100, 100
sustain.step(ctx, world)
assert(events[#events] == "revived")
world.character.hp = 0
count = #calls
sustain.step(ctx, world)
assert(#calls == count, "revive must not be resent after recovery")
-- HP and MP retain their hysteresis independently when priority changes.
ctx.state.sustain = {config = {hp_item = 1, mp_item = 2}}
world.inventory = {{item_id = 1, quantity = 1}, {item_id = 2, quantity = 1}}
world.character.hp, world.character.mp = 100, 20
sustain.step(ctx, world)
world.character.hp, world.character.mp = 50, 32
sustain.step(ctx, world)
assert(calls[#calls] == 1)
world.character.hp = 66
sustain.step(ctx, world)
assert(calls[#calls] == 2, "MP hysteresis must survive HP priority")
ctx.state.sustain = {config = {hp_item = 1.5, mp_item = 2}}
world.character.hp, world.character.mp = 50, 100
world.inventory = {{item_id = 1.5, quantity = 1}}
handled, reason = sustain.step(ctx, world)
assert(handled and reason == "no_potion")
ctx.state.sustain.config.hp_item = 2147483648
world.inventory = {{item_id = 2147483648, quantity = 1}}
handled, reason = sustain.step(ctx, world)
assert(handled and reason == "no_potion")
ctx.state.sustain = {revive_at = 0, revive_reported = true, config = {hp_item = 1, mp_item = 2}}
world.character.hp = 100
local event_count = #events
sustain.step(ctx, world)
assert(#events == event_count + 1 and events[#events] == "revived")
sustain.step(ctx, world)
assert(#events == event_count + 1)
print("sustain tests passed")
