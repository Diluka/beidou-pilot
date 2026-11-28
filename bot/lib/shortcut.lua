-- Offline prototype only: no runtime caller or native portal producer exists yet.
local terrain = require("lib.terrain")
local M = {}

-- Inputs are synthetic, pre-validated portal records, not raw Map.wz data.
function M.candidates(graph, map_id, portals)
    local by_name, duplicate, result = {}, {}, {}
    for _, portal in ipairs(portals) do
        if by_name[portal.name] then duplicate[portal.name] = true end
        by_name[portal.name] = portal
    end
    for _, portal in ipairs(portals) do
        local target = by_name[portal.target]
        if portal.verified == true and portal.activation == "up" and portal.map == map_id
            and portal.target_map == map_id and not duplicate[portal.name]
            and target and not duplicate[portal.target] and target.map == map_id
            and portal.name ~= portal.target then
            local from = terrain.platform_at(graph, portal.x, portal.y, graph.model.stand_height)
            local to = terrain.platform_at(graph, target.x, target.y, graph.model.stand_height)
            local dx, dy = portal.x - target.x, portal.y - target.y
            if from and to and from ~= to and dx * dx + dy * dy > 1600 then
                result[#result + 1] = {kind = "portal", from = from, to = to, x = portal.x, y = portal.y,
                    target_x = target.x, target_y = target.y, map_id = map_id, name = portal.name,
                    activation = "up", cost = 0.2}
            end
        end
    end
    return result
end

-- Caller supplies an approach callback and must stop invoking after any terminal result.
function M.step(state, context, world, approach)
    local edge, player, now = state.edge, context.game.player, context.tick.time
    local character = world.character
    if not world.ready or world.map_id ~= edge.map_id or world.scene_generation ~= state.generation
        or not character then
        player.stop()
        state.phase, state.reason = "failed", "scene_changed"
        return "failed", state.reason
    end
    if state.phase == "done" or state.phase == "failed" then
        player.stop()
        return state.phase, state.reason
    end
    if not state.phase then
        local status, reason = approach(context, world, edge)
        if status == "failed" then player.stop(); state.phase, state.reason = "failed", reason; return "failed", reason end
        if status ~= "done" then return "running" end
        if character.on_ground ~= true or math.abs(character.x - edge.x) > 6
            or math.abs(character.y - edge.y) > 20 then
            player.stop(); state.phase, state.reason = "failed", "portal_not_reached"
            return "failed", state.reason
        end
        player.stop()
        player.move("up")
        state.phase, state.started = "waiting", now
        return "running"
    end
    player.move(nil)
    local dx, dy = character.x - edge.target_x, character.y - edge.target_y
    if character.on_ground == true and dx * dx + dy * dy <= 400 then
        player.stop(); state.phase = "done"; return "done"
    end
    if now - state.started >= 3 then
        player.stop(); state.phase, state.reason = "failed", "portal_timeout"; return "failed", state.reason
    end
    return "running"
end

return M
