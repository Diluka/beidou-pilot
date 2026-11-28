package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local shortcut = require("lib.shortcut")
local graph = {model = {stand_height = 10}, platforms = {
    {left = 0, right = 100, segments = {0,100,100,100}},
    {left = 0, right = 100, segments = {0,100,0,0}},
}}
local portals = {
    {name="a", target="b", map=1, target_map=1, x=50, y=100, activation="up", verified=true},
    {name="b", target="a", map=1, target_map=1, x=50, y=0, activation="unknown", verified=false},
}
local edges = shortcut.candidates(graph, 1, portals)
assert(#edges == 1 and edges[1].from == 1 and edges[1].to == 2 and edges[1].cost < 1)
portals[1].target_map = 2
assert(#shortcut.candidates(graph, 1, portals) == 0, "cross-map portal rejected")
portals[1].target_map = 1; portals[1].verified = false
assert(#shortcut.candidates(graph, 1, portals) == 0, "unverified portal rejected")
portals[1].verified = true; portals[2].y = -100
assert(#shortcut.candidates(graph, 1, portals) == 0, "unstandable destination rejected")
portals[2].y = 0; portals[3] = portals[2]
assert(#shortcut.candidates(graph, 1, portals) == 0, "ambiguous name rejected")
portals[3] = nil
local edge = shortcut.candidates(graph, 1, portals)[1]
local commands = {}
local context = {tick={time=0}, game={player={move=function(x) commands[#commands+1] = x or "release" end,
    stop=function() commands[#commands+1] = "stop" end}}}
local world = {ready=true, map_id=1, scene_generation=1, character={x=50,y=100,on_ground=true}}
local state = {edge=edge, generation=1}
local approach = function() return "done" end
assert(shortcut.step(state, context, world, approach) == "running" and commands[#commands] == "up")
context.tick.time = 0.5
assert(shortcut.step(state, context, world, approach) == "running" and commands[#commands] == "release")
world.character.y = 0
assert(shortcut.step(state, context, world, approach) == "done" and commands[#commands] == "stop")
world.character.y = 100; state = {edge=edge, generation=1}; context.tick.time = 1
shortcut.step(state, context, world, approach); context.tick.time = 4
assert(select(2, shortcut.step(state, context, world, approach)) == "portal_timeout")
local before = #commands
assert(shortcut.step(state, context, world, approach) == "failed")
for i=before+1,#commands do assert(commands[i] ~= "up", "failed portal must not repeat") end
state = {edge=edge, generation=1}; world.scene_generation = 2
assert(select(2, shortcut.step(state, context, world, approach)) == "scene_changed")
print("shortcut prototype tests ok")
