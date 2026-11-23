local M = {}

function M.new(graph)
    return {graph = graph, status = "done"}
end

function M.set_path(mover, edges)
    if type(edges) ~= "table" then return false, "invalid_edge" end
    mover.edges, mover.index, mover.status = edges, 1, "running"
    mover.started, mover.retries, mover.reason = nil, 0, nil
    return true
end

function M.stop(mover)
    player.move(nil)
    mover.status, mover.started = "done", nil
end

function M.step(mover, ctx, world)
    if mover.status ~= "running" then return mover.status, mover.reason end
    local edge = mover.edges[mover.index]
    if not edge then
        M.stop(mover)
        return "done"
    end
    local reason
    if type(edge) ~= "table" or type(edge.kind) ~= "string" then
        reason = "invalid_edge"
    elseif edge.kind ~= "walk" and edge.kind ~= "step" then
        reason = "unsupported_edge"
    elseif type(edge.destination) ~= "number" then
        reason = "invalid_edge"
    end
    local character = world and world.character
    if not reason and (not character or type(character.x) ~= "number" or type(character.y) ~= "number") then
        reason = "character_unavailable"
    end
    if reason then
        player.move(nil)
        mover.status, mover.reason = "failed", reason
        return "failed", reason
    end
    local now = (ctx.tick and ctx.tick.time) or world.now
    if not mover.started then
        mover.started, mover.progress_time, mover.progress_x = now, now, character.x
        mover.start_y, mover.airborne = character.y, character.on_ground == false
    end
    if edge.kind == "walk" and math.abs(character.x - edge.destination) <= 12
        or edge.kind == "step" and (character.y - mover.start_y >= 10 or (mover.airborne and character.on_ground)) then
        player.move(nil)
        mover.index, mover.started, mover.retries = mover.index + 1, nil, 0
        if mover.index > #mover.edges then mover.status = "done"; return "done" end
        return "running"
    end
    if character.on_ground == false then mover.airborne = true end
    if now - mover.started >= 10 then
        reason = "timeout"
    elseif now - mover.progress_time >= 2 then
        if math.abs(character.x - mover.progress_x) < 5 then reason = "no_progress" end
        mover.progress_time, mover.progress_x = now, character.x
    end
    if reason then
        player.move(nil)
        if mover.retries < 1 then
            mover.retries, mover.started = mover.retries + 1, nil
            return "running"
        end
        mover.status, mover.reason = "failed", reason
        return "failed", reason
    end
    player.move(character.x < edge.destination and "right" or "left")
    return "running"
end

return M
