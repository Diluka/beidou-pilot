local metrics, io_module = require('lib.metrics'), require('lib.io')
local combat, sustain = require('lib.combat'), require('lib.sustain')
local old = {new=metrics.new, observe=metrics.observe, target=metrics.target, visit=metrics.visit,
    event=metrics.event, poll=io_module.poll, publish=io_module.publish, io_event=io_module.event,
    select=combat.select, step=combat.step, sustain=sustain.step}
local calls, events, fail_init, fail_observe, selected = {}, {}, false, false, nil
metrics.new = function(path) calls[#calls+1]='new'; assert(path == '/test/metrics.json'); if fail_init then error('disk') end; return {} end
metrics.observe = function(_, _, world)
    calls[#calls+1]='observe'
    if fail_observe then error('observe failure') end
    assert(world.ready == false or world.character.platform ~= nil)
    return true
end
metrics.target = function(_, mob) calls[#calls+1]=mob and 'target' or 'clear' end
metrics.visit = function(_, data) calls[#calls+1]='visit'; assert(data.collection_policy == nil) end
metrics.event = function(_, kind) calls[#calls+1]='event:'..kind end
io_module.poll = function() return {} end
io_module.publish = function() calls[#calls+1]='publish'; return true end
io_module.event = function(_, kind) events[#events+1]=kind; return true end
combat.select = function() return selected end
combat.step = function() return 'running', 'attacking' end
sustain.step = function() return false end
local nav = dofile('bot/test/fixtures/synthetic.lua').navigation
local player = {move=function() return true end, skill=function() return true end, stop=function() return true end}
local function context(enabled)
    return {tick={time=0}, state={bot_root='/test',bot={mode='hunt',config={metrics_enabled=enabled},player=player}},
        scene={terrain={status='available',navigation=nav}},
        game={world={ready=true,map_id=1,scene_generation=1},character={x=1,y=100,on_ground=true,hp=50,max_hp=50,mp=10,max_mp=10},
            scene={monsters={},drops={}},inventory={items={},status='ok'},player=player}}
end
local f=assert(io.open('bot/main.lua')); local tick=assert(load(f:read('*a')..'\nreturn main'))(); f:close()
local ctx=context(1)
tick(ctx)
assert(table.concat(calls,','):find('new,observe,visit',1,true))
assert(table.concat(calls,','):find('clear',1,true))
selected={object_id=7,template_id=1,platform=1,x=1,y=100,active=true}
ctx.tick.time=1; calls={}; tick(ctx)
assert(table.concat(calls,','):find('observe,target',1,true))
selected=nil; ctx.tick.time=2; calls={}; tick(ctx)
assert(table.concat(calls,','):find('observe,clear',1,true))
local disabled=context(0); calls={}; tick(disabled); assert(not table.concat(calls,','):find('new',1,true))
local broken=context(1); fail_init=true; calls={}; tick(broken); tick(broken)
assert(table.concat(calls,','):find('new',1,true) and not table.concat(calls,','):find('observe',1,true))
fail_init=false; local faulty=context(1); fail_observe=true; calls={}; events={}; tick(faulty); faulty.tick.time=1; tick(faulty)
assert(#events==1 and events[1]=='metrics/error', 'exceptions must be isolated and rate limited')
assert(table.concat(calls,','):find('publish',1,true), 'sampling failures must not prevent publish')
local state_module, original_open = require('lib.state'), io.open
local old_root = state_module.bot_root
state_module.bot_root = '/metric-config-test'
io.open = function(path, mode)
    if path == '/metric-config-test/config.conf' then
        return {lines=function() local done=false; return function() if not done then done=true; return 'metrics_enabled=0' end end end,
            close=function() return true end}
    end
    return original_open(path, mode)
end
assert(state_module.new().config.metrics_enabled == 0)
io.open, state_module.bot_root = original_open, old_root
metrics.new,metrics.observe,metrics.target,metrics.visit,metrics.event=old.new,old.observe,old.target,old.visit,old.event
io_module.poll,io_module.publish,io_module.event=old.poll,old.publish,old.io_event
combat.select,combat.step,sustain.step=old.select,old.step,old.sustain
print('metrics wiring tests ok')
