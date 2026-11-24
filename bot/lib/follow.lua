local M = {}

local FOLLOW_DISTANCE = 80
local STOP_DISTANCE = 40
local EVENT_INTERVAL = 30

local function wait(reason)
    return {kind = "wait", reason = reason}
end

local function wait_for_absent_owner(ctx)
    local state = ctx.state
    local now = ctx.tick.time
    state.follow_owner_absent_since = state.follow_owner_absent_since or now
    local last_event = state.follow_owner_absent_event_at
    if now - state.follow_owner_absent_since >= EVENT_INTERVAL
        and (last_event == nil or now - last_event >= EVENT_INTERVAL) then
        require("lib.io").event(ctx, "owner_absent", {reason = "owner_absent"})
        state.follow_owner_absent_event_at = now
    end
    return wait("owner_absent")
end

function M.update(ctx, world)
    local owner = world and world.owner
    if type(owner) ~= "table" or owner.present == false then return wait_for_absent_owner(ctx) end

    local scene = ctx.game.scene
    local players = scene and scene.players
    local matched_owner
    if type(players) == "table" then
        for _, player in ipairs(players) do
            local owner_id, player_id = owner.character_id, player.character_id
            local has_owner_id = owner_id ~= nil and owner_id ~= ""
            local has_player_id = player_id ~= nil and player_id ~= ""
            if has_owner_id and has_player_id then
                if owner_id == player_id then
                    matched_owner = player
                    break
                end
            elseif owner.name ~= nil and owner.name ~= "" and player.name == owner.name then
                matched_owner = player
                break
            end
        end
    end
    if not matched_owner then return wait_for_absent_owner(ctx) end

    ctx.state.follow_owner_absent_since = nil
    ctx.state.follow_owner_absent_event_at = nil
    if owner.platform == nil then return wait("owner_platform_unknown") end

    local character = world.character
    if type(matched_owner.x) ~= "number" or type(matched_owner.y) ~= "number"
        or type(character) ~= "table" or type(character.x) ~= "number" then
        return wait("owner_absent")
    end

    local distance = math.abs(matched_owner.x - character.x)
    if distance < STOP_DISTANCE then return wait("close_enough") end
    if distance <= FOLLOW_DISTANCE then return wait("deadband") end
    return {
        kind = "move",
        x = matched_owner.x,
        y = matched_owner.y,
        stop_distance = STOP_DISTANCE,
    }
end

return M
