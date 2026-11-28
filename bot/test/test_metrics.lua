local saved_storage, saved_io = package.loaded['lib.metrics_storage'], package.loaded['lib.io']
local snapshots = {}
package.loaded['lib.metrics_storage'] = {
    new = function(path) return {path=path} end,
    save = function(_, rows) snapshots[#snapshots + 1] = table.concat(rows, ','); return true end,
}
local events = {}
package.loaded['lib.io'] = {event=function(_,kind,data) events[#events+1]={kind=kind,data=data}; return true end}
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
-- Platform observations are independent of monster completeness and include idle time.
local p = assert(metrics.new('/platform.json'))
local pc = {tick={time=0}, state={bot={config={ammo_item_id=2060000,hp_item=2000000,mp_item=2000003}}},
    game={character={experience=100},inventory={status='ok'}}}
local pw = {ready=true,map_id=1,scene_generation=1,character={platform=2,level=10},
    inventory={{item_id=2060000,quantity=100},{item_id=2000000,quantity=10},{item_id=2000003,quantity=9}}}
for i=0,20 do
    pc.tick.time=i
    if i==1 then pc.game.character.experience=110; pw.inventory[1].quantity=97; pw.inventory[2].quantity=9 end
    assert(metrics.observe(p,pc,pw))
end
text=snapshots[#snapshots]
assert(text:find('"dwell_s":20',1,true) and text:find('"platform_complete":true',1,true))
assert(text:find('"exp_delta_observed":10',1,true) and text:find('"arrow_delta_observed":3',1,true))
assert(text:find('"hp_potion_delta_observed":1',1,true) and text:find('"mp_potion_delta_observed":0',1,true))
assert(text:find('"attribution":"platform_window"',1,true) and text:find('"complete":false',1,true))
-- Level reset and unavailable inventory poison only the affected window, not the next.
pc.tick.time=21; pw.character.level=11; pc.game.character.experience=0; pc.game.inventory.status='unavailable'
assert(metrics.observe(p,pc,pw))
for i=22,40 do pc.tick.time=i; assert(metrics.observe(p,pc,pw)) end
text=snapshots[#snapshots]
assert(text:find('"exp_delta_observed":null',1,true) and text:find('"arrow_delta_observed":null',1,true))
-- A short normal platform change retains the prior valid exposure; the crossing interval is excluded.
local cross = assert(metrics.new('/cross.json'))
pc.tick.time=0; pc.game.inventory.status='ok'; pc.game.character.experience=200
pw.character.level=10; pw.character.platform=2; pw.mobs=nil; pw.metrics_complete=true
assert(metrics.observe(cross,pc,pw))
for i=1,5 do pc.tick.time=i; assert(metrics.observe(cross,pc,pw)) end
pc.tick.time=6; pw.character.platform=3; assert(metrics.observe(cross,pc,pw))
text=table.concat(cross.rows, ',')
assert(text:find('"dwell_s":5',1,true) and text:find('"platform_complete":true',1,true))
assert(text:find('"complete":false',1,true), 'missing mobs cannot establish monster completeness')
metrics.visit(cross, {arrival_reason='platform_or_scene_changed',preserve_observation=true})
pc.tick.time=7; pc.game.character.experience=205; assert(metrics.observe(cross,pc,pw))
metrics.visit(cross, {exit_reason='patrol'})
text=table.concat(cross.rows, ',')
assert(text:find('"dwell_s":1',1,true) and text:find('"exp_delta_observed":5',1,true),
    'visit metadata must preserve first new-platform interval')
local missing_mobs = assert(metrics.new('/missing-mobs.json'))
pc.tick.time=0; assert(metrics.observe(missing_mobs,pc,pw))
for i=1,20 do pc.tick.time=i; assert(metrics.observe(missing_mobs,pc,pw)) end
text=snapshots[#snapshots]
assert(text:find('"platform_complete":true',1,true) and text:find('"complete":false',1,true))
-- Increases reset the baseline; unavailable or ambiguous item observations remain unknown.
local inventory_test = assert(metrics.new('/inventory.json'))
pc.tick.time=0; pw.character.platform=2; pw.inventory[1].quantity=100
assert(metrics.observe(inventory_test,pc,pw))
pc.tick.time=1; pw.inventory[1].quantity=110; assert(metrics.observe(inventory_test,pc,pw))
pc.tick.time=2; pw.inventory[1].quantity=100; assert(metrics.observe(inventory_test,pc,pw))
for i=3,20 do pc.tick.time=i; assert(metrics.observe(inventory_test,pc,pw)) end
text=snapshots[#snapshots]
assert(text:find('"arrow_delta_observed":10',1,true))
pc.tick.time=21; pw.inventory[1].quantity=nil; assert(metrics.observe(inventory_test,pc,pw))
for i=22,40 do pc.tick.time=i; assert(metrics.observe(inventory_test,pc,pw)) end
assert(snapshots[#snapshots]:find('"arrow_delta_observed":null',1,true))
-- Timing metadata is emitted only for a slow, normally returned save.
local clock = os.clock
local ticks = {0, 0.06}
os.clock = function() return table.remove(ticks, 1) end
local probe = assert(metrics.new('/probe.json'))
probe.rows = {'{"x":1}'}; probe.last_write = 0
events = {}
assert(metrics.flush(probe, 20, ctx))
assert(#events == 1 and events[1].kind == 'metrics/flush')
assert(events[1].data.slow_candidate.bytes == 7 and events[1].data.slow_candidate.duration_us >= 59999)
ticks = {1, 1.01}; events = {}
assert(metrics.flush(probe, 40, ctx))
assert(#events == 1 and events[1].data.slow_candidate == nil)
os.clock = clock
package.loaded['lib.metrics_storage'], package.loaded['lib.io'], package.loaded['lib.metrics'] = saved_storage, saved_io, nil
print('metrics tests ok')
