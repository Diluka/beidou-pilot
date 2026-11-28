-- 按 /work/bot/route.json 的航点逐图走到传送门；仅在观察到目标地图后推进。
package.path = "/work/scripts/bot/?.lua;/work/scripts/bot/?/init.lua;" .. package.path
local travel = require("lib.travel")
local world = require("lib.world")
local sustain = require("lib.sustain")

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
    local observed = world.observe(context)
    local handled = sustain.step(context, observed)
    if handled then
        context.game.player.move(nil)
        context.state.travel.graph, context.state.travel.mover, context.state.travel.path = nil, nil, nil
        return
    end
    local status, reason = travel.step(context.state.travel, context, observed)
    if status ~= "running" then return status, reason end
end
