local M = {}

function M.poll(ctx, now)
    return nil, "not_implemented"
end

function M.publish(ctx, world, now)
    return false, "not_implemented"
end

function M.event(ctx, kind, data)
    return false, "not_implemented"
end

return M
