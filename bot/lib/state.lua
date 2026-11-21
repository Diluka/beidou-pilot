local M = {}

function M.new()
    return nil, "not_implemented"
end

function M.apply(state, command)
    return false, "not_implemented"
end

function M.transition(state, mode, reason)
    return false, "not_implemented"
end

return M
