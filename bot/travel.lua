-- 按 /work/bot/route.json 的航点逐图走到传送门；仅在观察到目标地图后推进。
package.path = "/work/scripts/bot/?.lua;/work/scripts/bot/?/init.lua;" .. package.path
local travel = require("lib.travel")
local world = require("lib.world")

local function main(context)
    if not context.state.travel then
        local legs, goal = travel.load_route("/work/bot/route.json")
        if not legs then
            context.game.player.stop()
            context.game.log("travel failed: route_missing")
            return "failed", "route_missing"
        end
        context.state.travel = travel.new(legs, goal)
    end
    local status, reason = travel.step(context.state.travel, context, world.observe(context))
    if status ~= "running" then return status, reason end
end
