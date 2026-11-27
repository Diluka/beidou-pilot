package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local real_terrain = package.loaded["lib.terrain"]
local graph = {model={stand_height=20}, platforms={{left=-400,right=400}}}
local target_available = true
package.loaded["lib.terrain"] = {
    build=function() return graph end,
    platform_at=function(_, x) if x < 0 and not target_available then return nil end; return 1 end,
    plan=function() error("shop approach must never plan a drop") end,
}
local file = assert(io.open("bot/shop_approach.lua")); local tick = assert(load(file:read("*a") .. "\nreturn main"))(); file:close()
local moving, stops = nil, 0
local ctx = {state={}, tick={time=0}, scene={terrain={status="available", navigation={}}},
    game={world={ready=true,map_id=100000102,scene_generation=1},
    character={x=300,y=182,on_ground=true}, scene={npcs={{name="卢娜",x=-258,y=84}}},
    player={stop=function() stops=stops+1 end, skill=function() end,
        move=function(direction) moving=direction; return true end}}}
assert(tick(ctx) == nil and moving == "left")
ctx.game.character.x = -258
assert(tick(ctx) == "done" and stops == 1)
ctx.state={}; ctx.game.character.x=300; target_available=false
local status, reason = tick(ctx)
assert(status == "failed" and reason == "same_platform_unavailable")
target_available=true; ctx.game.scene.npcs[1].y=0
status, reason = tick(ctx)
assert(status == "failed" and reason == "npc_distance_unsafe")
package.loaded["lib.terrain"] = real_terrain
print("shop approach tests passed")
