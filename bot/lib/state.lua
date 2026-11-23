local defaults = require("defaults")
local M = {}
local allowed_modes = {recover = true, idle = true, follow = true, hunt = true, dead = true}

local function read_values(path)
    local values = {}
    local file = io.open(path, "r")
    if not file then return nil end
    for line in file:lines() do
        local key, value = line:match("^([%w_]+)=(.*)$")
        if key then values[key] = value end
    end
    file:close()
    return values
end

function M.new()
    local config = {}
    for key, value in pairs(defaults) do config[key] = value end
    local configured = read_values("/work/bot/config.conf") or {}
    for key, value in pairs(defaults) do
        local raw = configured[key]
        if raw ~= nil then
            if type(value) == "string" then
                config[key] = raw
            else
                config[key] = tonumber(raw) or value
            end
        end
    end
    local checkpoint = read_values("/work/bot/checkpoint.conf")
    local valid_checkpoint = checkpoint ~= nil
        and allowed_modes[checkpoint.mode] ~= nil
        and (checkpoint.map_id == nil or tonumber(checkpoint.map_id) ~= nil)
    if valid_checkpoint and checkpoint.target and checkpoint.target == "" then valid_checkpoint = false end
    local checkpoint_error
    if not valid_checkpoint then checkpoint_error = "checkpoint_invalid_or_missing" end

    local target
    if config.owner_character_id > 0 then
        target = tostring(config.owner_character_id)
    elseif config.owner_name ~= "" then
        target = config.owner_name
    end

    return {
        mode = "recover",
        target = nil,
        owner_target = target,
        config = config,
        last_command = nil,
        last_error = checkpoint_error,
        checkpoint = valid_checkpoint and checkpoint or nil,
        started_at = os.clock(),
    }
end

function M.apply(state, command)
    if type(command) ~= "table" or type(command.kind) ~= "string" then
        return false, "invalid_command"
    end
    if command.kind == "status" then
        state.last_command = command.kind
        return true
    elseif command.kind == "follow" then
        local target = command.target or state.owner_target
        if not target or target == "" then return false, "target_required" end
        state.target = target
        state.mode = "follow"
    elseif command.kind == "hunt" then
        state.mode, state.target = "hunt", nil
    elseif command.kind == "stay" then
        if not state.player then return false, "player_unavailable" end
        local ok, reason = state.player.stop()
        if not ok then return false, reason or "player_stop_failed" end
        state.mode = "idle"
    elseif command.kind == "stop" then
        if not state.player then return false, "player_unavailable" end
        local ok, reason = state.player.stop()
        if not ok then return false, reason or "player_stop_failed" end
        state.mode, state.target, state.path = "idle", nil, nil
    else
        return false, "unknown_kind"
    end
    state.last_command = command.kind
    state.last_error = nil
    return true
end

function M.transition(state, mode, reason)
    if not allowed_modes[mode] then return false, "invalid_mode" end
    state.mode = mode
    state.transition_reason = reason
    if mode ~= "recover" then state.last_error = nil end
    return true
end

return M
