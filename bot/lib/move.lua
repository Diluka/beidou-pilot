local M = {}

function M.new(graph)
    return nil, "not_implemented"
end

function M.set_path(mover, edges)
    return false, "not_implemented"
end

function M.step(mover, ctx, world)
    return "failed", "not_implemented"
end

function M.stop(mover)
    return false, "not_implemented"
end

return M
