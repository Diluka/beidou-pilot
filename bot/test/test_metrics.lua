local saved_storage, saved_io = package.loaded['lib.metrics_storage'], package.loaded['lib.io']
local snapshots = {}
package.loaded['lib.metrics_storage'] = {
    new = function(path) return {path=path} end,
    save = function(_, rows) snapshots[#snapshots + 1] = table.concat(rows, ','); return true end,
}
package.loaded['lib.io'] = {event=function() return true end}
package.loaded['lib.metrics'] = nil
local metrics = require('lib.metrics')
local m = assert(metrics.new('/metrics.json'))
local ctx = {tick={time=0}, game={character={experience=10}}}
local w = {ready=true, map_id=1, scene_generation=1, metrics_complete=true,
    character={platform=2,hp=100,level=10}, mobs={{object_id=9,template_id=100,platform=2,active=true}}, drops={}}
assert(metrics.observe(m,ctx,w))
metrics.target(m,w.mobs[1])
ctx.tick.time=1; assert(metrics.observe(m,ctx,w))
ctx.tick.time=2; w.character.hp=90; ctx.game.character.experience=15
w.mobs[1].active=false; w.metrics_exp_attributable=true
assert(metrics.observe(m,ctx,w)); w.metrics_exp_attributable=nil
assert(metrics.event(m,'hp_potion',{map_id=1,platform=2,mob_template=100}))
assert(metrics.event(m,'drop_picked',{map_id=1,platform=2,mob_template=100,item_id=42}))
ctx.tick.time=20
assert(metrics.observe(m,ctx,w))
local text = snapshots[1]
assert(text:find('"kills":1',1,true) and text:find('"estimated":true',1,true))
assert(text:find('"exp":5',1,true) and text:find('"dwell_s":1',1,true))
assert(text:find('"hp_potions":1',1,true) and text:find('"42":1',1,true))
assert(text:find('"insufficient":true',1,true))
-- A disappearing target is only an estimate and invalidates rate eligibility.
w.mobs={{object_id=10,template_id=100,platform=2,active=true}}
metrics.target(m,w.mobs[1]); ctx.tick.time=22; w.mobs={}
assert(metrics.observe(m,ctx,w)); ctx.tick.time=40; assert(metrics.observe(m,ctx,w))
text=snapshots[2]
assert(text:find('"exp_unknown_kills":1',1,true) and text:find('"complete":false',1,true))
-- A scene change is never counted as a kill.
w.mobs={{object_id=11,template_id=100,platform=2,active=true}}
metrics.target(m,w.mobs[1]); ctx.tick.time=42; w.scene_generation=2; w.mobs={}
assert(metrics.observe(m,ctx,w)); ctx.tick.time=60; assert(metrics.observe(m,ctx,w))
text=snapshots[3]
assert(text:find('"scene_or_observation_changed"',1,true))
-- Passive exposure includes time with no selected combat target, including zero kills.
local n = assert(metrics.new('/other.json'))
local q = {ready=true,map_id=7,scene_generation=3,metrics_complete=true,metrics_targets_complete=true,
    character={platform=4,hp=100,level=10},mobs={{object_id=80,template_id=12,platform=4,active=true}},drops={}}
ctx.tick.time=0; assert(metrics.observe(n,ctx,q))
metrics.visit(n,{arrival_reason='patrol',collection_policy='round_robin',policy_seed=5,exit_reason='patrol'})
assert(metrics.observe(n,ctx,q))
for i=1,20 do ctx.tick.time=i; assert(metrics.observe(n,ctx,q)) end
text=snapshots[#snapshots]
assert(text:find('"dwell_s":20',1,true) and text:find('"kills":0',1,true))
assert(text:find('"entries":1',1,true) and text:find('"collection_policy":"round_robin"',1,true))
-- Missing samples and platform changes do not produce a kill or attribute experience.
metrics.target(n,q.mobs[1]); ctx.tick.time=25; q.mobs={}; assert(metrics.observe(n,ctx,q))
assert(n.target == nil)
ctx.tick.time=26; q.character.platform=5; assert(metrics.observe(n,ctx,q))
ctx.tick.time=40; assert(metrics.observe(n,ctx,q))
text=snapshots[#snapshots]
assert(not text:find('"kills":1',1,true))
-- Visiting with a known exit reason closes the previous window normally.
local v = assert(metrics.new('/visit.json'))
ctx.tick.time=0; q.character.platform=4; q.scene_generation=3
q.mobs={{object_id=81,template_id=12,platform=4,active=true}}
assert(metrics.observe(v,ctx,q)); metrics.visit(v,{arrival_reason='patrol',collection_policy='round_robin'})
assert(metrics.observe(v,ctx,q))
for i=1,3 do ctx.tick.time=i; assert(metrics.observe(v,ctx,q)) end
metrics.visit(v,{arrival_reason='loot',exit_reason='patrol',collection_policy='round_robin'})
assert(table.concat(v.rows, ','):find('"complete":true',1,true))
assert(table.concat(v.rows, ','):find('"exit_reason":"patrol"',1,true))
-- Invalid observations do not carry their scene into the next valid window.
ctx.tick.time=4; q.ready=false; assert(metrics.observe(v,ctx,q))
ctx.tick.time=5; q.ready=true; q.scene_generation=4; assert(metrics.observe(v,ctx,q))
assert(v.scene == 4 and v.window_start == 5)
package.loaded['lib.metrics_storage'], package.loaded['lib.io'], package.loaded['lib.metrics'] = saved_storage, saved_io, nil
print('metrics tests ok')
