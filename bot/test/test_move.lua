package.path = "bot/?.lua;" .. package.path
local move = require("lib.move")
local terrain = require("lib.terrain")
local platform_at = terrain.platform_at
terrain.platform_at = function() return 1 end
local direction
player = nil
game = {player = {
    move = function(value) assert(value == nil or value == "left" or value == "right"); direction = value; return true end,
    skill = function(value) assert(value == nil); return true end,
    status = function() return {} end,
    stop = function() error("mover must not call player.stop") end,
}}
local ctx = {tick = {time = 0, index = 0}, game = game}
local function step(...)
    ctx.tick.index = ctx.tick.index + 1
    return move.step(...)
end
local world = {character = {x = 0, y = 0, on_ground = true}}
local mover = move.new({})
assert(move.set_path(mover, {{kind = "walk", destination = 100}}))
assert(step(mover, ctx, world) == "running" and direction == "right")
world.character.x = 90
assert(step(mover, ctx, world) == "done" and direction == nil)
world.character.x = 0
assert(move.set_path(mover, {{kind = "walk", destination = 100}}))
assert(step(mover, ctx, world) == "running")
ctx.tick.time = 2
assert(step(mover, ctx, world) == "running" and direction == nil)
assert(step(mover, ctx, world) == "running")
ctx.tick.time = 4
local status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "no_progress" and direction == nil)
assert(move.set_path(mover, {{kind = "unknown", destination = 100}}))
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "unsupported_edge")
assert(move.set_path(mover, {{kind = "walk", destination = 100}}))
assert(step(mover, ctx, world) == "running")
move.stop(mover)
assert(direction == nil)
assert(move.set_path(mover, {{kind = "walk"}}))
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "invalid_edge" and direction == nil)
assert(move.set_path(mover, {{kind = "walk", destination = 1000}}))
for attempt = 1, 2 do
    for i = 0, 10 do
        ctx.tick.time = 20 + (attempt - 1) * 11 + i
        world.character.x = i * 6
        status, reason = step(mover, ctx, world)
    end
end
assert(status == "failed" and reason == "timeout" and direction == nil)
local action
local supported = true
game.player.move = function(value) direction = value; return true end
game.player.jump = function() action = "jump"; return supported end
game.player.skill = function(value) assert(value == nil); action = nil; return true end
local function begin(edge)
    edge.to = edge.to or 1
    ctx.tick.time = 0
    world.character = {x = 0, y = 0, on_ground = true}
    assert(move.set_path(mover, {edge}))
end
game.character = {physics = {x = 0, velocity = {x = 0}}}
begin({kind = "jumpup", x = 0, destination = 0, rise = 30})
assert(step(mover, ctx, world) == "running" and action == "jump")
ctx.tick.time = 0.1; world.character.y = -11; world.character.on_ground = false
assert(step(mover, ctx, world) == "running" and direction == nil and action == nil)
world.character.x = 30; world.character.on_ground = true
assert(step(mover, ctx, world) == "done")
game.character = {physics = {x = 0, velocity = {x = 0}}}
begin({kind = "downjump", x = 0, destination = 0})
assert(step(mover, ctx, world) == "running" and direction == "down" and action == nil,
    "hold Down for one tick before submitting Jump")
assert(step(mover, ctx, world) == "running" and direction == "down" and action == "jump",
    "submit Jump only after Down is already held")
ctx.tick.time = 0.4; world.character.on_ground = false; world.character.y = 11
assert(step(mover, ctx, world) == "running" and direction == nil and action == nil)
world.character.on_ground = true
assert(step(mover, ctx, world) == "done")
begin({kind = "downjump", x = 0, destination = 0, to = 2})
assert(step(mover, ctx, world) == "running" and direction == "down" and action == nil,
    "hold Down for one tick before a mismatched landing")
assert(step(mover, ctx, world) == "running" and direction == "down" and action == "jump")
ctx.tick.time = 0.4; world.character.on_ground = false; world.character.y = 11
assert(step(mover, ctx, world) == "running" and direction == nil and action == nil)
world.character.on_ground = true
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "landing_mismatch" and direction == nil and action == nil)
begin({kind = "downjump", x = 0, destination = 0})
assert(step(mover, ctx, world) == "running" and direction == "down" and action == nil)
assert(step(mover, ctx, world) == "running" and direction == "down" and action == "jump")
move.stop(mover)
assert(direction == nil and action == nil)
begin({kind = "drop", destination = 100})
assert(step(mover, ctx, world) == "running")
assert(step(mover, ctx, world) == "running" and direction == "right")
ctx.tick.time = 0.4; world.character.x = 40; world.character.on_ground = false
assert(step(mover, ctx, world) == "running" and direction == nil)
world.character.x, world.character.y, world.character.on_ground = 100, 11, true
assert(step(mover, ctx, world) == "done")
begin({kind = "rope", x = 0, destination = 0, rise = -100})
assert(step(mover, ctx, world) == "running" and direction == "up")
world.character.y = -80; world.character.on_ground = false
assert(step(mover, ctx, world) == "running" and direction == "up")
ctx.tick.time = 0.4
assert(step(mover, ctx, world) == "running" and direction == "up")
world.character.y = -100; world.character.on_ground = true
assert(step(mover, ctx, world) == "done" and direction == nil)
begin({kind = "rope", x = 0, destination = 0, rise = -100, to = 2, from = 1})
for attempt = 1, 2 do
    step(mover, ctx, world)
    ctx.tick.time = ctx.tick.time + 2
    status, reason = step(mover, ctx, world)
end
assert(status == "failed" and reason == "no_progress" and direction == nil)
for _, edge in ipairs({{kind="jumpup",x=0,destination=0,rise=50}, {kind="drop",destination=100}}) do
    begin(edge)
    step(mover, ctx, world)
    ctx.tick.time = edge.kind == "drop" and 12 or 10
    status, reason = step(mover, ctx, world)
    assert(status == "failed" and reason == "timeout" and direction == nil and action == nil)
end
begin({kind="jumpup",x=0,destination=0,rise=50,to=2})
step(mover, ctx, world)
world.character.on_ground = false; world.character.y = -11
step(mover, ctx, world)
world.character.on_ground = true
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "landing_mismatch" and direction == nil)
begin({kind="rope",x=0,destination=0,rise=-100})
for attempt = 1, 2 do
    step(mover, ctx, world)
    world.character.x = 5
    status, reason = step(mover, ctx, world)
    world.character.x = 0
end
assert(status == "failed" and reason == "rope_mismatch" and direction == nil)
begin({kind="jumpup",x=0,destination=0,rise=50})
supported = false
step(mover, ctx, world)
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "unsupported_edge" and direction == nil)
begin({kind="rope",x=0,destination=0,rise=-100,to=2,from=1})
step(mover, ctx, world)
ctx.tick.time = 10
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "timeout" and direction == nil)
begin({kind="drop",destination=100})
step(mover, ctx, world)
ctx.tick.time = 0.4; world.character.y = 20; world.character.on_ground = false
step(mover, ctx, world)
assert(step(mover, ctx, world) == "running")
ctx.tick.time = 12
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "timeout" and direction == nil)
supported = true
begin({kind="jumpup",x=0,destination=0,rise=50})
assert(step(mover, ctx, world) == "running" and action == "jump")
assert(move.set_path(mover, {{kind="rope",destination=0,rise=-100}}))
assert(step(mover, ctx, world) == "running" and action == nil)
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "invalid_edge" and action == nil)
begin({kind="jumpup",x=0,destination=0,rise=50})
assert(step(mover, ctx, world) == "running" and action == "jump")
move.stop(mover)
assert(action == nil and direction == nil and mover.status == "done")
move.stop(mover)
assert(action == nil and direction == nil and mover.status == "done")
local reused = {{kind="drop",destination=100}}
begin(reused[1])
assert(move.set_path(mover, reused))
step(mover, ctx, world)
ctx.tick.time = 9
assert(move.set_path(mover, reused))
assert(step(mover, ctx, world) == "running")
ctx.tick.time = 10
assert(step(mover, ctx, world) == "running")
begin({kind="jumpup",x=0,destination=0,rise=50})
step(mover, ctx, world)
world.character.on_ground = false; world.character.y = -11
step(mover, ctx, world)
world.character.x = 30; world.character.y = 0; world.character.on_ground = true
assert(step(mover, ctx, world) == "done")
begin({kind="jumpup",x=0,destination=0,rise=50})
step(mover, ctx, world)
world.character.on_ground = false; world.character.y = -11
step(mover, ctx, world)
world.character.y = -30
assert(step(mover, ctx, world) == "running")
world.character.on_ground = true
assert(step(mover, ctx, world) == "done")
begin({kind="jumpup",x=0,destination=0})
step(mover, ctx, world)
world.character.on_ground = false; world.character.y = -11
step(mover, ctx, world)
world.character.on_ground = true; world.character.x = 30
assert(step(mover, ctx, world) == "done")
begin({kind="drop",destination=100})
world.character.on_ground = nil
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "character_unavailable" and direction == nil)
begin({kind="rope",x=0,destination=0,rise=-100})
game.player.move = function(value) direction = value; return value == nil end
step(mover, ctx, world)
status, reason = step(mover, ctx, world)
assert(status == "failed" and reason == "unsupported_edge" and direction == nil)
local draft_action, committed_action, draft_direction, committed_direction
game.player.move = function(value) draft_direction = value; return true end
game.player.jump = function() draft_action = "jump"; return true end
game.player.skill = function(value) assert(value == nil); draft_action = nil; return true end
game.player.status = function() return {input_action = draft_action} end
local function commit_tick()
    committed_action, committed_direction = draft_action, draft_direction
    ctx.tick.index = ctx.tick.index + 1
end
begin({kind="jumpup",x=0,destination=0,rise=50})
assert(move.step(mover, ctx, world) == "running")
commit_tick()
assert(committed_action == "jump" and committed_direction == nil)
assert(move.set_path(mover, {{kind="jumpup",x=0,destination=0,rise=50,to=1}}))
assert(move.step(mover, ctx, world) == "running")
assert(move.step(mover, ctx, world) == "running")
commit_tick()
assert(committed_action == nil and committed_direction == nil)
assert(move.step(mover, ctx, world) == "running")
commit_tick()
assert(committed_action == "jump" and committed_direction == nil)
assert(move.step(mover, ctx, world) == "running")
move.stop(mover)
move.stop(mover)
assert(move.set_path(mover, {{kind="jumpup",x=0,destination=0,rise=50,to=1}}))
assert(move.step(mover, ctx, world) == "running")
commit_tick()
assert(committed_action == nil and committed_direction == nil)
assert(move.step(mover, ctx, world) == "running")
commit_tick()
assert(committed_action == "jump" and committed_direction == nil)
-- stop is the first mover call in this new tick.
move.stop(mover)
assert(move.set_path(mover, {{kind="jumpup",x=0,destination=0,rise=50,to=1}}))
assert(move.step(mover, ctx, world) == "running")
assert(move.step(mover, ctx, world) == "running")
commit_tick()
assert(committed_action == nil and committed_direction == nil)
assert(move.step(mover, ctx, world) == "running")
commit_tick()
assert(committed_action == "jump" and committed_direction == nil)
move.stop(mover)
draft_action = "attack" -- another caller replaces the stopped input
assert(move.set_path(mover, {{kind="walk",destination=100}}))
assert(move.step(mover, ctx, world) == "running")
commit_tick()
assert(committed_action == "attack")
assert(move.step(mover, ctx, world) == "running")
assert(draft_action == "attack" and draft_direction == "right")
commit_tick()
begin({kind="jumpup",x=0,destination=0,rise=50})
assert(move.step(mover, ctx, world) == "running")
commit_tick()
move.stop(mover)
draft_action = "jump" -- another caller owns this new jump
assert(move.set_path(mover, {{kind="walk",destination=100}}))
assert(move.step(mover, ctx, world) == "running")
commit_tick()
assert(committed_action == "jump")
for _, mode in ipairs({"character", "edge"}) do
    mover = move.new({})
    begin({kind="jumpup",x=0,destination=0,rise=50})
    assert(move.step(mover,ctx,world)=="running")
    commit_tick()
    assert(committed_action=="jump")
    if mode == "character" then world.character.on_ground=nil else mover.edges[1].destination=nil end
    status,reason=move.step(mover,ctx,world)
    assert(status=="failed" and reason==(mode=="character" and "character_unavailable" or "invalid_edge"))
    world.character.on_ground=true
    assert(move.set_path(mover,{{kind="jumpup",x=0,destination=0,rise=50,to=1}}))
    assert(move.step(mover,ctx,world)=="running")
    commit_tick()
    assert(committed_action==nil and committed_direction==nil)
    assert(move.step(mover,ctx,world)=="running")
    commit_tick()
    assert(committed_action=="jump")
end
terrain.platform_at = platform_at
game.character = {physics={velocity={x=0}}}
game.player.move = function(value) direction = value; return true end
game.player.jump = function() return true end
game.player.skill = function() return true end
mover = move.new({platforms={
    {left=-100,right=100,segments={-100,100,0,0}},
    {left=-100,right=100,segments={-100,100,-100,-100}},
}})
begin({kind="jumpup",x=0,destination=0,rise=100,to=2})
step(mover, ctx, world)
assert(direction == nil)
world.character.on_ground=false; world.character.y=-100
assert(step(mover, ctx, world)=="running")
assert(step(mover, ctx, world)=="running")
world.character.on_ground=true
assert(step(mover, ctx, world)=="done")
begin({kind="jumpup",x=0,destination=0,rise=100,to=2})
step(mover,ctx,world)
world.character.on_ground=false; world.character.y=-11
step(mover,ctx,world)
world.character.on_ground=true; world.character.y=0
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="landing_mismatch")
begin({kind="drop",destination=0,to=1})
world.character.y=-100
step(mover,ctx,world)
ctx.tick.time=0.4; world.character.on_ground=false; world.character.y=0
step(mover,ctx,world)
world.character.on_ground=true
assert(step(mover,ctx,world)=="done")
begin({kind="drop",destination=0,to=2})
step(mover,ctx,world)
ctx.tick.time=0.4; world.character.on_ground=false
step(mover,ctx,world)
world.character.on_ground=true
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="landing_mismatch")
mover.graph.platforms[1].segments = {-100,100,-100,100}
begin({kind="drop",destination=0,to=2})
step(mover,ctx,world)
ctx.tick.time=0.4; world.character.x=11; world.character.y=11
assert(step(mover,ctx,world)=="running")
assert(step(mover,ctx,world)=="running") -- slope movement is not an airborne landing
world.character.on_ground=false
step(mover,ctx,world)
world.character.on_ground=true
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="landing_mismatch")
begin({kind="rope",x=0,destination=0,rise=-100,to=2,from=1})
step(mover,ctx,world)
world.character.y=-80; world.character.on_ground=false
assert(step(mover,ctx,world)=="running" and direction=="up")
world.character.y=-100; world.character.on_ground=true
assert(step(mover,ctx,world)=="done" and direction==nil)
begin({kind="rope",x=0,destination=0,rise=-100,to=3,from=1})
step(mover,ctx,world)
world.character.y=-80; world.character.on_ground=false
assert(step(mover,ctx,world)=="running")
world.character.y=-100; world.character.on_ground=true
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="landing_mismatch" and direction==nil)
-- Use real platform lookup: a step can pass near a platform while airborne.
local step_edge = {kind="step", from=1, to=2, destination=30}
mover = move.new({platforms={
    {left=0,right=20,segments={0,20,0,12}},
    {left=25,right=40,segments={25,40,24,24}},
    {left=0,right=50,segments={0,50,100,100}},
}})
local action_released
game.player.skill = function(value) assert(value == nil); action_released = true; return true end
for _, landing in ipairs({{30,24,"done"}, {30,100,"failed"}, {20,12,"failed"}}) do
    action_released = false
    begin(step_edge)
    assert(step(mover,ctx,world)=="running")
    world.character.x, world.character.y, world.character.on_ground = 30,24,false
    assert(step(mover,ctx,world)=="running" and mover.index==1, "airborne near target is not a landing")
    world.character.x, world.character.y, world.character.on_ground = landing[1],landing[2],true
    status,reason=step(mover,ctx,world)
    assert(status==landing[3] and direction==nil)
    if status=="failed" then assert(reason=="landing_mismatch" and mover.index==1 and action_released) end
end
begin(step_edge)
assert(step(mover,ctx,world)=="running")
world.character.x, world.character.y = 20,12
assert(step(mover,ctx,world)=="running", "descending a source slope is not arrival")
world.character.x, world.character.y = 30,24
world.character.on_ground = nil
assert(step(mover,ctx,world)=="running", "an unknown ground state cannot confirm arrival")
world.character.on_ground = true
assert(step(mover,ctx,world)=="done", "a grounded crossing needs no airborne sample")
begin(step_edge)
assert(step(mover,ctx,world)=="running")
world.character.x, world.character.y = 30,100
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="landing_mismatch", "a missed airborne sample cannot hide the wrong platform")
assert(move.set_path(mover, {{kind="step", destination=30}}))
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="invalid_edge", "a step needs a target platform")
-- Captured overlap: p125 approaches x=1220.5 from the right at full walk
-- speed. Accepting the position alone launches a moving jump onto p85.
local real = assert(terrain.build(dofile("bot/test/fixtures/map_102000000.lua").navigation))
local edge = {kind="jumpup", from=125, to=86, x=1220.5, destination=1220.5, rise=54.5}
for _, landing in ipairs({{1188,1824,86}, {1162,1852,85}, {1216,1800,87}}) do
    mover = move.new(real)
    local launch = landing[3]==86 and 1183 or 1220.5
    begin({kind="jumpup", from=125, to=86, x=launch, destination=launch})
    game.character = {physics={velocity={x=-125}}}
    game.player.jump = function() action = "jump"; return true end
    game.player.skill = function() action = nil; return true end
    action = nil
    world.character.x, world.character.y = 1237,1875
    assert(step(mover,ctx,world)=="running" and direction=="left")
    world.character.x = math.floor(launch + 6)
    assert(step(mover,ctx,world)=="running" and not direction and not action,
        "release the approach direction and brake on the source platform before jumping")
    assert(step(mover,ctx,world)=="running" and not direction and not action,
        "another Lua tick is not proof that the approach velocity has dissipated")
    world.character.x, game.character.physics.velocity.x = math.floor(launch + 5),0
    assert(step(mover,ctx,world)=="running" and action=="jump" and direction==nil,
        "a vertical overlap jump must not steer toward a fractional probe coordinate")
    world.character.y, world.character.on_ground = 1858,false
    assert(step(mover,ctx,world)=="running" and not action)
    world.character.x, world.character.y, world.character.on_ground = landing[1],landing[2],true
    assert(terrain.platform_at(real,landing[1],landing[2],20)==landing[3])
    status,reason=step(mover,ctx,world)
    if landing[3]==edge.to then assert(status=="done")
    else assert(status=="failed" and reason=="landing_mismatch") end
    assert(direction==nil and action==nil)
end
-- Unknown speed is not proof of rest; a never-settling approach remains bounded.
for _, physics in ipairs({{}, {velocity={x=-125}}}) do
    mover = move.new(real)
    begin(edge)
    game.character = {physics=physics}
    world.character.x, world.character.y = 1220,1875
    status,reason=step(mover,ctx,world)
    if physics.velocity then
        assert(status=="running" and not direction and not action)
        ctx.tick.time=10.01
        status,reason=step(mover,ctx,world)
        assert(reason=="timeout")
    else assert(reason=="character_unavailable") end
    assert(status=="failed" and not direction and not action)
end
local drop_platforms = {}
for index = 1, 7 do
    drop_platforms[index] = {left=500,right=500,segments={500,500,0,0}}
end
drop_platforms[5] = {left=-200,right=-130,segments={-200,-130,485,485}}
drop_platforms[7] = {left=-133,right=0,segments={-133,0,469,469}}
local drop_graph = {platforms=drop_platforms}
local natural_drop = {kind="drop",from=7,to=5,x=-133,destination=-175.5,rise=16}
mover = move.new(drop_graph)
begin(natural_drop)
world.character = {x=-93,y=469,on_ground=true}
ctx.tick.time = 0
assert(step(mover,ctx,world)=="running" and direction=="left")
ctx.tick.time = 0.4; world.character.x = -135
assert(step(mover,ctx,world)=="running" and direction=="left",
    "a drop keeps moving past the source edge while still grounded")
ctx.tick.time = 0.8; world.character.x = -150
assert(step(mover,ctx,world)=="running" and direction=="left",
    "a drop does not stop merely for reaching the edge coordinate")
ctx.tick.time = 1; world.character.y = 480
assert(step(mover,ctx,world)=="running" and direction==nil and mover.phase=="wait",
    "release movement after the ten-pixel descent signal")
assert(step(mover,ctx,world)=="running" and not mover.airborne,
    "a grounded height change alone cannot confirm a landing")
ctx.tick.time = 1.1; world.character.on_ground = false
assert(step(mover,ctx,world)=="running" and mover.airborne)
ctx.tick.time = 1.2
world.character.x, world.character.y, world.character.on_ground = -160, 485, true
assert(terrain.platform_at(drop_graph,world.character.x,world.character.y,20)==5)
assert(step(mover,ctx,world)=="done" and direction==nil,
    "a grounded landing on platform 5 within 20px of destination completes the drop")

mover = move.new(drop_graph)
begin(natural_drop)
world.character = {x=-93,y=469,on_ground=true}
ctx.tick.time = 0; step(mover,ctx,world)
ctx.tick.time = 0.4; world.character.x = -135; world.character.on_ground = false
assert(step(mover,ctx,world)=="running" and direction==nil)
ctx.tick.time = 0.8
world.character.x, world.character.y, world.character.on_ground = -140, 485, true
assert(terrain.platform_at(drop_graph,world.character.x,world.character.y,20)==5)
status, reason = step(mover,ctx,world)
assert(status=="failed" and reason=="landing_mismatch" and direction==nil,
    "a landing more than 20px from the target point is rejected")

mover = move.new(drop_graph)
begin(natural_drop)
world.character = {x=-93,y=469,on_ground=true}
ctx.tick.time = 0; step(mover,ctx,world)
ctx.tick.time = 0.4; world.character.x = -135; world.character.on_ground = false
step(mover,ctx,world)
ctx.tick.time = 0.8
world.character.x, world.character.y, world.character.on_ground = -90, 469, true
status, reason = step(mover,ctx,world)
assert(status=="failed" and reason=="landing_mismatch" and direction==nil,
    "landing on the source platform is rejected")

mover = move.new(drop_graph)
begin(natural_drop)
world.character = {x=-93,y=469,on_ground=true}
ctx.tick.time = 0; step(mover,ctx,world)
ctx.tick.time = 2
assert(step(mover,ctx,world)=="running" and mover.retries==1 and direction==nil,
    "a stalled edge retries once after clearing direction")
ctx.tick.time = 2.1
assert(step(mover,ctx,world)=="running" and direction=="left")
ctx.tick.time = 4.2
status, reason = step(mover,ctx,world)
assert(status=="failed" and reason=="no_progress" and direction==nil,
    "a drop that cannot leave the edge reports no_progress")

-- A downjump must wait for horizontal approach momentum to settle before Down+Jump.
local downjump_graph = {platforms={
    {left=534,right=765,segments={534,765,365,365}},
    {left=546,right=714,segments={546,714,425,425}},
}}
mover = move.new(downjump_graph)
begin({kind="downjump",from=1,to=2,x=630,destination=630,rise=60})
world.character.x,world.character.y = 495,365
world.character.on_ground = true
game.character.physics = {x=495,velocity={x=87}}
direction,action = nil,nil
assert(step(mover,ctx,world)=="running" and direction=="right" and action==nil)
ctx.tick.time=0.1
world.character.x,game.character.physics.x,game.character.physics.velocity.x = 624,624,125
assert(step(mover,ctx,world)=="running" and direction==nil and action==nil,
    "release horizontal input but do not launch while the actor is still moving")
ctx.tick.time=0.2
world.character.x,game.character.physics.x,game.character.physics.velocity.x = 632,632,68
assert(step(mover,ctx,world)=="running" and direction==nil and action==nil,
    "continued drift must not consume the downjump action")
ctx.tick.time=0.3
world.character.x,game.character.physics.x,game.character.physics.velocity.x = 630.4,630.4,0.25
assert(step(mover,ctx,world)=="running" and direction=="down" and action==nil,
    "commit Down for a tick after horizontal velocity settles")
ctx.tick.time=0.333
assert(step(mover,ctx,world)=="running" and direction=="down" and action=="jump",
    "issue Jump on a later tick while Down is already held")
ctx.tick.time=0.7
world.character.y,world.character.on_ground = 373,false
assert(step(mover,ctx,world)=="running" and direction==nil and action==nil)
ctx.tick.time=0.8
world.character.x,world.character.y,world.character.on_ground = 630,425,true
assert(terrain.platform_at(downjump_graph,world.character.x,world.character.y,20)==2)
assert(step(mover,ctx,world)=="done" and direction==nil and action==nil,
    "a grounded landing on p13 completes the downjump")

mover=move.new(downjump_graph)
begin({kind="downjump",from=1,to=2,x=630,destination=630,rise=60})
world.character.x,world.character.y = 630,365
game.character=nil
assert(step(mover,ctx,world)=="running" and direction==nil and action==nil)
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="character_unavailable" and direction==nil and action==nil,
    "downjump must fail closed when horizontal velocity is unavailable")

game.character=nil

local map10000 = assert(terrain.build(dofile("bot/test/fixtures/map_10000.lua").navigation))
local horizontal_edge = assert(terrain.plan(map10000, 4, 10, {speed=125}))[1]
mover = move.new(map10000)
begin(horizontal_edge)
world.character = {x=horizontal_edge.x,y=365,on_ground=true}
ctx.tick.time=0; direction,action=nil,nil
game.player.move = function(value) direction=value; return true end
game.player.jump = function() action="jump"; return true end
game.player.skill = function(value) assert(value==nil); action=nil; return true end
assert(step(mover,ctx,world)=="running" and direction=="right" and action=="jump",
    "a horizontal jump launches toward its destination")
ctx.tick.time=0.1; world.character.x,world.character.y,world.character.on_ground = horizontal_edge.x+14,320,false
assert(step(mover,ctx,world)=="running" and direction=="right")
ctx.tick.time=0.4; world.character.x=horizontal_edge.destination-4
assert(step(mover,ctx,world)=="running" and direction==nil and action==nil,
    "release horizontal input at the landing strip and release Jump after launch")
world.character.x,world.character.y,world.character.on_ground = horizontal_edge.destination,485,true
assert(terrain.platform_at(map10000,world.character.x,world.character.y,20)==horizontal_edge.to)
assert(step(mover,ctx,world)=="done" and direction==nil,
    "complete a horizontal jump only after landing on its target platform")

local wrong_landing_graph = {platforms={
    {left=0,right=20,segments={0,20,100,100}},
    {left=40,right=70,segments={40,70,90,90}},
    {left=40,right=70,segments={40,70,100,100}},
}}
mover = move.new(wrong_landing_graph)
begin({kind="horizontal_jump",from=1,to=2,x=12,destination=50})
world.character = {x=12,y=100,on_ground=true}
ctx.tick.time=0
assert(step(mover,ctx,world)=="running")
world.character.x,world.character.y,world.character.on_ground = 30,50,false
assert(step(mover,ctx,world)=="running")
world.character.x,world.character.y,world.character.on_ground = 50,100,true
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="landing_mismatch" and direction==nil,
    "a horizontal jump landing on a different platform must fail explicitly")

-- Directional jumpup retreats on the source platform, then measures speed across ticks.
terrain.platform_at = function(_, _, y) return y < -5 and 2 or 1 end
game.player.move = function(value) direction = value; return true end
game.player.jump = function() action = "jump"; return true end
game.player.skill = function() action = nil; return true end
local function runup(sign, distance)
    local extent = distance + 8
    mover = move.new({platforms={{left=sign == 1 and -extent or -100,
        right=sign == 1 and 100 or extent, segments={-100,100,0,0}}}})
    begin({kind="jumpup",from=1,to=2,x=0,destination=sign*40})
    action, direction = nil, nil
    assert(step(mover,ctx,world)=="running" and action==nil)
    assert(step(mover,ctx,world)=="running" and direction==(sign==1 and "left" or "right") and action==nil)
    world.character.x=-sign*distance; ctx.tick.time=0.5
    assert(step(mover,ctx,world)=="running" and direction==nil and action==nil)
    game.character = {physics={velocity={x=0}}}
    ctx.tick.time=0.51
    assert(step(mover,ctx,world)=="running" and direction==nil and action==nil)
    ctx.tick.time=0.52
    assert(step(mover,ctx,world)=="running" and direction==(sign==1 and "right" or "left") and action==nil)
end
for _, sign in ipairs({1,-1}) do
    for _, distance in ipairs({32,20,12}) do
        runup(sign,distance)
        -- A large displacement outside the launch window is insufficient.
        if distance == 32 then
            world.character.x=-sign*20; ctx.tick.time=0.6
            assert(step(mover,ctx,world)=="running" and action==nil)
        end
        -- No elapsed time and zero speed cannot trigger a jump.
        assert(step(mover,ctx,world)=="running" and action==nil)
        world.character.x=-sign*8; ctx.tick.time=distance == 32 and 0.7 or 0.55
        assert(step(mover,ctx,world)=="running" and action=="jump")
        world.character.on_ground=false; world.character.y=-11; ctx.tick.time=0.8
        assert(step(mover,ctx,world)=="running")
        world.character.on_ground=true; world.character.x=sign*40
        assert(step(mover,ctx,world)=="done")
    end
end
-- Entering the launch window below 40px/s does not jump; exactly 40 does.
runup(1,20)
world.character.x=-12; ctx.tick.time=1
assert(step(mover,ctx,world)=="running" and action==nil)
world.character.x=-7; ctx.tick.time=1.125
assert(step(mover,ctx,world)=="running" and action=="jump")
move.stop(mover)
-- Too little safe source space fails after the retry, without jumping.
mover=move.new({platforms={{left=-19,right=100,segments={-19,100,0,0}}}})
begin({kind="jumpup",from=1,to=2,x=0,destination=40}); action=nil
assert(step(mover,ctx,world)=="running" and action==nil)
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="runup_unavailable" and action==nil)
-- A stalled approach times out, retries, and can subsequently succeed.
runup(1,32)
ctx.tick.time=2.1
assert(step(mover,ctx,world)=="running" and action==nil)
assert(step(mover,ctx,world)=="running")
world.character.x=-32; ctx.tick.time=2.2
assert(step(mover,ctx,world)=="running" and direction==nil)
ctx.tick.time=2.3
assert(step(mover,ctx,world)=="running" and direction==nil)
world.character.x=-8; ctx.tick.time=2.4
assert(step(mover,ctx,world)=="running" and action=="jump")
world.character.on_ground=false; world.character.y=-11; ctx.tick.time=2.5
step(mover,ctx,world)
world.character.on_ground=true; world.character.y=0
status,reason=step(mover,ctx,world)
assert(status=="failed" and reason=="landing_mismatch")
-- Regression: approach a leftward jump from far across the same wide platform.
-- Walking toward the run-up point must not be mistaken for retreat or a retry.
mover = move.new({platforms={{left=938,right=3458,segments={938,3458,0,0}}}})
begin({kind="jumpup",from=1,to=2,x=944,destination=928,rise=50})
world.character.x = 3398
game.character = {physics={x=3398,velocity={x=0}}}
action, direction = nil, nil
assert(step(mover,ctx,world)=="running" and action==nil)
for i, x in ipairs({3298,2798,2298,1798,1298,1000}) do
    ctx.tick.time = i
    world.character.x = x
    game.character.physics.x = x
    game.character.physics.velocity.x = -100
    status, reason = step(mover,ctx,world)
    assert(status=="running" and direction=="left" and action==nil and mover.retries==0,
        "far approach must walk left without failing, jumping or retrying")
end
world.character.x = 976; game.character.physics.x = 976; ctx.tick.time = 6.25
status, reason = step(mover,ctx,world)
assert(status=="running" and direction==nil and action==nil and mover.retries==0,
    "stop at the safe run-up point before settling")
game.character.physics.velocity.x = 0; ctx.tick.time = 6.35
status, reason = step(mover,ctx,world)
assert(status=="running" and action==nil and mover.retries==0,
    "settling must not jump or retry")
ctx.tick.time = 6.45
status, reason = step(mover,ctx,world)
assert(status=="running" and direction=="left" and action==nil and mover.retries==0,
    "run up left after settling")
world.character.x = 952; game.character.physics.x = 952; ctx.tick.time = 6.65
assert(step(mover,ctx,world)=="running" and direction=="left" and action=="jump" and mover.retries==0,
    "jump left inside the launch window")
world.character.on_ground=false; world.character.y=-11; ctx.tick.time=6.75
assert(step(mover,ctx,world)=="running")
world.character.on_ground=true; world.character.x=928; world.character.y=-50
assert(step(mover,ctx,world)=="done" and direction==nil and mover.retries==0,
    "land on the destination platform without retrying")
-- Scene 29: starting exactly on the source edge can move inward safely.
terrain.platform_at = function(_, _, y) return y < 370 and 28 or 29 end
local platforms29 = {}
platforms29[29] = {left=3458,right=3638,segments={3458,3638,394,394}}
mover = move.new({platforms=platforms29})
begin({kind="jumpup",from=29,to=28,x=3464,destination=3448,rise=60})
world.character.x, world.character.y = 3458, 394
game.character = {physics={x=3458,velocity={x=0}}}
action, direction = nil, nil
assert(step(mover,ctx,world)=="running" and action==nil and mover.retries==0)
assert(step(mover,ctx,world)=="running" and direction=="right" and action==nil and mover.retries==0,
    "move inward from the source platform edge")
world.character.x=3496; ctx.tick.time=0.4
assert(step(mover,ctx,world)=="running" and direction==nil and action==nil and mover.retries==0)
ctx.tick.time=0.5
assert(step(mover,ctx,world)=="running" and direction==nil and action==nil)
ctx.tick.time=0.6
assert(step(mover,ctx,world)=="running" and direction=="left" and action==nil)
world.character.x=3472; ctx.tick.time=0.8
assert(step(mover,ctx,world)=="running" and direction=="left" and action=="jump" and mover.retries==0)
world.character.on_ground=false; world.character.y=380; ctx.tick.time=0.9
assert(step(mover,ctx,world)=="running")
world.character.on_ground=true; world.character.x=3448; world.character.y=334
assert(step(mover,ctx,world)=="done" and direction==nil and mover.retries==0)
terrain.platform_at = platform_at
print("move tests ok")
