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
    game.player.move(nil)
    game.player.skill(nil)
    mover.stop_pending = mover.stop_pending or mover.jump_held or nil
    mover.status, mover.started, mover.jump_held = "done", nil, nil
end

function M.step(mover, ctx, world)
    if mover.stop_pending and mover.status == "running" then
        mover.stop_pending, mover.release_tick = nil, ctx.tick.index
        return "running"
    end
    if mover.jump_held and (mover.status ~= "running" or not mover.started or mover.active_edges ~= mover.edges or mover.active_index ~= mover.index) then
        game.player.move(nil)
        game.player.skill(nil)
        mover.jump_held = nil
        if mover.status == "running" then
            mover.release_tick = ctx.tick.index
            return "running"
        end
    end
    if mover.release_tick ~= nil then
        if ctx.tick.index == mover.release_tick then return mover.status, mover.reason end
        mover.release_tick = nil
    end
    if mover.status ~= "running" then return mover.status, mover.reason end
    local edge = mover.edges[mover.index]
    if not edge then
        M.stop(mover)
        return "done"
    end
    local reason
    if type(edge) ~= "table" or type(edge.kind) ~= "string" then
        reason = "invalid_edge"
    elseif edge.kind ~= "walk" and edge.kind ~= "step" and edge.kind ~= "jumpup" and edge.kind ~= "downjump" and edge.kind ~= "drop" and edge.kind ~= "rope" then
        reason = "unsupported_edge"
    elseif type(edge.destination) ~= "number" or (edge.kind == "step" and type(edge.to) ~= "number") then
        reason = "invalid_edge"
    end
    local character = world and world.character
    if not reason and (not character or type(character.x) ~= "number" or type(character.y) ~= "number" or ((edge.kind == "jumpup" or edge.kind == "downjump" or edge.kind == "drop" or edge.kind == "rope") and type(character.on_ground) ~= "boolean")) then
        reason = "character_unavailable"
    end
    if reason then
        game.player.move(nil)
        if mover.jump_held then game.player.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
        mover.status, mover.reason = "failed", reason
        return "failed", reason
    end
    local now = (ctx.tick and ctx.tick.time) or world.now
    if edge.kind == "jumpup" or edge.kind == "downjump" or edge.kind == "drop" or edge.kind == "rope" then
        local p = ctx.game.player
        local terrain = require("lib.terrain")
        if type(edge.to) ~= "number" or (edge.kind ~= "drop" and type(edge.x) ~= "number") or (edge.kind == "rope" and (type(edge.rise) ~= "number" or edge.rise == 0)) then
            p.move(nil)
            if mover.jump_held then p.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
            mover.status, mover.reason = "failed", "invalid_edge"; return "failed", mover.reason
        end
        if mover.active_edges ~= mover.edges or mover.active_index ~= mover.index then
            mover.active_edges, mover.active_index, mover.edge_started = mover.edges, mover.index, now
            mover.airborne = nil
        end
        if not mover.started then
            if mover.retries == 0 then mover.edge_started = now; mover.airborne = nil end
            mover.started, mover.phase, mover.start_y = now, "align", character.y
            if edge.kind == "drop" then
                mover.progress_time, mover.progress_x, mover.progress_y = now, character.x, character.y
            end
        end
        local failure
        if (edge.kind == "jumpup" or edge.kind == "downjump" or edge.kind == "drop") and mover.phase ~= "align" and character.on_ground == false then mover.airborne = true end
        if now - mover.edge_started >= 10 then failure = "timeout" end
        if not failure and mover.phase == "align" then
            local tolerance = edge.kind == "rope" and 4 or 8
            local vertical = (edge.kind == "jumpup" and edge.x == edge.destination) or edge.kind == "downjump"
            local physics = vertical and ctx.game.character and ctx.game.character.physics
            local align_x = (physics and physics.x) or character.x
            if edge.kind ~= "drop" and math.abs(align_x - edge.x) > tolerance then
                if not p.move(align_x < edge.x and "right" or "left") then failure = "unsupported_edge" end
            elseif edge.kind == "jumpup" then
                local direction
                if not vertical then
                    direction = character.x < edge.destination and "right" or (character.x > edge.destination and "left" or nil)
                end
                local moved = p.move(direction)
                if moved and vertical then
                    -- A neutral jump inherits the approach velocity until ground friction stops it.
                    if not physics or not physics.velocity or physics.velocity.x == nil then
                        mover.status, mover.reason = "failed", "character_unavailable"
                        return "failed", mover.reason
                    end
                    if not character.on_ground or physics.velocity.x ~= 0 then return "running" end
                end
                local ok = moved and p.jump()
                if not ok then failure = "unsupported_edge" else
                    mover.phase, mover.phase_time, mover.start_y, mover.jump_held = "launch", now, character.y, true
                end
            elseif edge.kind == "downjump" then
                if not character.on_ground then return "running" end
                -- A prior edge can carry momentum; treat speeds below 1px/s as settled.
                if not physics or not physics.velocity or physics.velocity.x == nil then
                    failure = "character_unavailable"
                elseif math.abs(physics.velocity.x) >= 1 then
                    if not p.move(nil) then failure = "unsupported_edge" else return "running" end
                else
                    local ok = p.move("down") and p.jump()
                    if not ok then failure = "unsupported_edge" else
                        mover.phase, mover.phase_time, mover.start_y, mover.jump_held = "launch", now, character.y, true
                    end
                end
            elseif edge.kind == "drop" then
                if not p.move(character.x < edge.destination and "right" or "left") then failure = "unsupported_edge" end
                mover.phase, mover.phase_time, mover.start_y = "launch", now, character.y
            else
                mover.phase, mover.start_y = "climb", character.y
                mover.progress_time, mover.progress_y = now, character.y
                if not p.move(edge.rise < 0 and "up" or "down") then failure = "unsupported_edge" end
            end
        elseif not failure and mover.phase == "launch" then
            if edge.kind == "drop" then
                if character.on_ground == false or character.y - mover.start_y >= 10 then
                    p.move(nil)
                    mover.phase = "wait"
                else
                    local direction = character.x < edge.destination and "right" or "left"
                    if not p.move(direction) then failure = "unsupported_edge"
                    elseif now - mover.progress_time >= 2 then
                        if math.abs(character.x - mover.progress_x) < 5
                            and math.abs(character.y - mover.progress_y) < 5 then
                            failure = "no_progress"
                        else
                            mover.progress_time, mover.progress_x, mover.progress_y = now, character.x, character.y
                        end
                    end
                end
            elseif now - mover.phase_time >= 0.3 or (edge.kind == "jumpup" and character.y < mover.start_y - 10) then
                p.move(nil)
                if mover.jump_held then p.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
                mover.phase = "wait"
            end
        elseif not failure and mover.phase == "climb" then
            local target = mover.start_y + edge.rise
            if math.abs(character.x - edge.x) > 4 then
                failure = "rope_mismatch"
            elseif (edge.rise < 0 and character.y <= target + 20) or (edge.rise > 0 and character.y >= target - 20) then
                p.move(nil)
                if terrain.platform_at(mover.graph, edge.destination, target, 20) ~= edge.to then failure = "landing_mismatch"
                else mover.phase, mover.phase_time = "settle", now end
            elseif now - mover.progress_time >= 2 then
                if math.abs(character.y - mover.progress_y) < 5 then failure = "no_progress" end
                mover.progress_time, mover.progress_y = now, character.y
            end
        elseif not failure and mover.phase == "settle" then
            if character.on_ground == true or now - mover.phase_time >= 0.3 then mover.phase = "complete" end
        elseif not failure and mover.phase == "wait" then
            if character.on_ground == false then mover.airborne = true end
            if character.on_ground == true and mover.airborne then
                local platform = terrain.platform_at(mover.graph, character.x, character.y, 20)
                if platform ~= edge.to or (edge.kind == "drop" and math.abs(character.x - edge.destination) > 20) then
                    failure = "landing_mismatch"
                elseif edge.kind == "jumpup" or character.y - mover.start_y >= 10 then
                    mover.phase = "complete"
                end
            end
            if not failure and mover.phase == "wait" and edge.kind == "drop" and now - mover.progress_time >= 2 then
                if math.abs(character.x - mover.progress_x) < 5
                    and math.abs(character.y - mover.progress_y) < 5 then
                    failure = "no_progress"
                else
                    mover.progress_time, mover.progress_x, mover.progress_y = now, character.x, character.y
                end
            end
        end
        if failure then
            p.move(nil)
            if mover.jump_held then p.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
            if failure ~= "timeout" and failure ~= "landing_mismatch" and mover.retries < 1 then mover.retries, mover.started, mover.airborne = mover.retries + 1, nil, nil; return "running" end
            mover.status, mover.reason = "failed", failure; return "failed", failure
        end
        if mover.phase == "complete" then
            p.move(nil); mover.index, mover.started, mover.retries, mover.airborne = mover.index + 1, nil, 0, nil
            if mover.index > #mover.edges then mover.status = "done"; return "done" end
        end
        return "running"
    end
    if not mover.started then
        mover.started, mover.progress_time, mover.progress_x = now, now, character.x
        mover.airborne = false
    end
    local arrived = edge.kind == "walk" and math.abs(character.x - edge.destination) <= 12
    if edge.kind == "step" then
        if character.on_ground == true then
            local platform = require("lib.terrain").platform_at(mover.graph, character.x, character.y, 20)
            arrived = platform == edge.to
            if not arrived and (mover.airborne or (platform and edge.from and platform ~= edge.from)) then
                M.stop(mover)
                mover.status, mover.reason = "failed", "landing_mismatch"
                return mover.status, mover.reason
            end
        elseif character.on_ground == false then
            mover.airborne = true
        end
    end
    if arrived then
        game.player.move(nil)
        mover.index, mover.started, mover.retries = mover.index + 1, nil, 0
        if mover.index > #mover.edges then mover.status = "done"; return "done" end
        return "running"
    end
    if now - mover.started >= 10 then
        reason = "timeout"
    elseif now - mover.progress_time >= 2 then
        if math.abs(character.x - mover.progress_x) < 5 then reason = "no_progress" end
        mover.progress_time, mover.progress_x = now, character.x
    end
    if reason then
        game.player.move(nil)
        if mover.retries < 1 then
            mover.retries, mover.started = mover.retries + 1, nil
            return "running"
        end
        mover.status, mover.reason = "failed", reason
        return "failed", reason
    end
    if not ctx.game.player.move(character.x < edge.destination and "right" or "left") then
        game.player.move(nil)
        mover.status, mover.reason = "failed", "unsupported_edge"
        return "failed", mover.reason
    end
    return "running"
end

return M
