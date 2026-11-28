-- 补给路线独立于 hunt 地图绑定，使用相同 travel 状态机。
local travel = require("lib.travel")
local world = require("lib.world")
local sustain = require("lib.sustain")

local function main(context)
    if not context.state.travel then
        local legs, goal = travel.load_route("/work/bot/route.supply.json")
        if not legs then
            context.game.player.stop()
            return "failed", "supply_route_missing"
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
