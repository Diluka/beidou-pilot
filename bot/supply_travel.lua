-- 补给路线独立于 hunt 地图绑定，使用相同 travel 状态机。
local travel = require("lib.travel")
local world = require("lib.world")

local function main(context)
    if not context.state.travel then
        local legs, goal = travel.load_route("/work/bot/route.supply.json")
        if not legs then
            context.game.player.stop()
            return "failed", "supply_route_missing"
        end
        context.state.travel = travel.new(legs, goal)
    end
    local status, reason = travel.step(context.state.travel, context, world.observe(context))
    if status ~= "running" then return status, reason end
end
