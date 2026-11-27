local M = {}

function M.new(graph)
    return {graph = graph, status = "done"}
end

function M.set_path(mover, edges)
    if type(edges) ~= "table" then return false, "invalid_edge" end
    mover.edges, mover.index, mover.status = edges, 1, "running"
    mover.started, mover.retries, mover.reason, mover.downjump_preheld = nil, 0, nil, nil
    return true
end

function M.stop(mover)
    game.player.move(nil)
    game.player.skill(nil)
    mover.stop_pending = mover.stop_pending or mover.jump_held or nil
    mover.status, mover.started, mover.jump_held, mover.downjump_preheld = "done", nil, nil, nil
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
    elseif edge.kind ~= "walk" and edge.kind ~= "step" and edge.kind ~= "jumpup" and edge.kind ~= "horizontal_jump" and edge.kind ~= "downjump" and edge.kind ~= "drop" and edge.kind ~= "rope" then
        reason = "unsupported_edge"
    elseif type(edge.destination) ~= "number" or (edge.kind == "step" and type(edge.to) ~= "number") then
        reason = "invalid_edge"
    end
    local character = world and world.character
    if not reason and (not character or type(character.x) ~= "number" or type(character.y) ~= "number" or ((edge.kind == "jumpup" or edge.kind == "horizontal_jump" or edge.kind == "downjump" or edge.kind == "drop" or edge.kind == "rope") and type(character.on_ground) ~= "boolean")) then
        reason = "character_unavailable"
    end
    if reason then
        game.player.move(nil)
        if mover.jump_held then game.player.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
        mover.status, mover.reason = "failed", reason
        return "failed", reason
    end
    local now = (ctx.tick and ctx.tick.time) or world.now
    if edge.kind == "horizontal_jump" then
        local p, terrain = ctx.game.player, require("lib.terrain")
        if type(edge.from) ~= "number" or type(edge.to) ~= "number" or type(edge.x) ~= "number" then
            p.move(nil)
            mover.status, mover.reason = "failed", "invalid_edge"
            return "failed", mover.reason
        end
        if mover.active_edges ~= mover.edges or mover.active_index ~= mover.index then
            mover.active_edges, mover.active_index, mover.edge_started = mover.edges, mover.index, now
            mover.airborne = nil
        end
        if not mover.started then
            mover.started, mover.phase, mover.start_y = now, "align", character.y
            mover.progress_time, mover.progress_x = now, character.x
        end
        local failure
        if now - mover.edge_started >= 10 then failure = "timeout" end
        if not failure and mover.phase == "align" and character.on_ground == true then
            local platform = terrain.platform_at(mover.graph, character.x, character.y, 20)
            if platform ~= edge.from then
                failure = "landing_mismatch"
            elseif math.abs(character.x - edge.x) > 8 then
                local direction = character.x < edge.x and "right" or "left"
                if not p.move(direction) then failure = "unsupported_edge" end
            else
                local jump_direction = character.x < edge.destination and "right" or "left"
                if not p.move(jump_direction) or not p.jump() then failure = "unsupported_edge"
                else
                    mover.phase, mover.phase_time, mover.airborne, mover.jump_held = "flight", now, false, true
                end
            end
        elseif not failure and mover.phase == "flight" then
            if character.on_ground == false then mover.airborne = true end
            if mover.airborne and character.on_ground == true then
                p.move(nil)
                if mover.jump_held then p.skill(nil); mover.jump_held = nil end
                local platform = terrain.platform_at(mover.graph, character.x, character.y, 20)
                if platform ~= edge.to or math.abs(character.x - edge.destination) > 20 then
                    failure = "landing_mismatch"
                else
                    mover.phase = "complete"
                end
            else
                local direction = character.x < edge.destination and "right" or "left"
                if (direction == "right" and character.x >= edge.destination - 8)
                    or (direction == "left" and character.x <= edge.destination + 8) then
                    if not p.move(nil) then failure = "unsupported_edge" end
                elseif not p.move(direction) then
                    failure = "unsupported_edge"
                end
                if mover.jump_held and now - mover.phase_time >= 0.3 then
                    p.skill(nil)
                    mover.jump_held = nil
                end
                if not failure and now - mover.progress_time >= 2 then
                    if math.abs(character.x - mover.progress_x) < 5 then failure = "no_progress" end
                    mover.progress_time, mover.progress_x = now, character.x
                end
            end
        end
        if failure then
            p.move(nil)
            if mover.jump_held then p.skill(nil); mover.jump_held = nil end
            if failure ~= "timeout" and failure ~= "landing_mismatch" and mover.retries < 1 then
                mover.retries, mover.started, mover.airborne = mover.retries + 1, nil, nil
                return "running"
            end
            mover.status, mover.reason = "failed", failure
            return "failed", failure
        end
        if mover.phase == "complete" then
            p.move(nil)
            mover.index, mover.started, mover.retries, mover.airborne = mover.index + 1, nil, 0, nil
            if mover.index > #mover.edges then mover.status = "done"; return "done" end
        end
        return "running"
    end
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
            mover.airborne, mover.downjump_preheld = nil, nil
            -- Allow travel to a distant launch point without removing the overall deadline.
            local movement = ctx.game.character and ctx.game.character.movement
            local speed = movement and movement.max_speed
            if type(speed) ~= "number" or speed <= 0 or speed ~= speed or speed == math.huge then speed = 100 end
            local align_x = edge.kind == "drop" and edge.destination or edge.x
            mover.edge_timeout = 10 + 2 * math.abs(align_x - character.x) / speed
        end
        if not mover.started then
            if mover.retries == 0 then mover.edge_started = now; mover.airborne = nil end
            mover.started, mover.phase, mover.start_y = now, "align", character.y
            if edge.kind == "jumpup" and edge.x ~= edge.destination then
                mover.phase = "prepare_runup"
            end
            if edge.kind == "drop" then
                mover.progress_time, mover.progress_x, mover.progress_y = now, character.x, character.y
            end
        end
        local failure
        if (edge.kind == "jumpup" or edge.kind == "downjump" or edge.kind == "drop") and mover.phase ~= "align" and character.on_ground == false then mover.airborne = true end
        if now - mover.edge_started >= mover.edge_timeout then failure = "timeout" end
        if not failure and mover.phase == "prepare_runup" then
            local platforms = type(mover.graph) == "table" and mover.graph.platforms
            local source = type(platforms) == "table" and platforms[edge.from] or nil
            local left = type(source) == "table" and source.left or nil
            local right = type(source) == "table" and source.right or nil
            local function finite(x) return type(x) == "number" and x == x and math.abs(x) < math.huge end
            local sign = edge.destination > edge.x and 1 or -1
            local segments = type(source) == "table" and source.segments or nil
            local on_source = false
            if type(segments) == "table" and #segments > 0 and #segments % 4 == 0 then
                for i = 1, #segments, 4 do
                    local a, b, y1, y2 = segments[i], segments[i + 1], segments[i + 2], segments[i + 3]
                    if not finite(a) or not finite(b) or not finite(y1) or not finite(y2) or a > b then
                        on_source = false; break
                    end
                    if character.x >= a and character.x <= b then
                        local y = a == b and y1 or y1 + (character.x - a) / (b - a) * (y2 - y1)
                        if math.abs(character.y - y) <= 20 then on_source = true end
                    end
                end
            end
            if not finite(edge.x) or not finite(edge.destination) or not finite(left) or not finite(right)
                or left > right or not character.on_ground or not on_source then
                failure = "runup_unavailable"
            else
                local target
                for _, distance in ipairs({32, 20, 12}) do
                    local candidate = edge.x - sign * distance
                    if candidate >= left + 8 and candidate <= right - 8 then target = candidate; break end
                end
                if not target then failure = "runup_unavailable" else
                    mover.runup_direction = sign == 1 and "right" or "left"
                    mover.runup_sign, mover.runup_target = sign, target
                    local movement = ctx.game.character and ctx.game.character.movement
                    local speed = movement and movement.max_speed
                    if type(speed) ~= "number" or speed <= 0 or speed ~= speed or speed == math.huge then speed = 100 end
                    mover.runup_left, mover.runup_right = left, right
                    mover.phase, mover.phase_time = "to_runup_start", now
                    mover.runup_timeout = 2 + 2 * math.abs(character.x - target) / speed
                end
            end
        elseif not failure and mover.phase == "to_runup_start" then
            if not character.on_ground or character.x < mover.runup_left or character.x > mover.runup_right
                or now - mover.phase_time >= mover.runup_timeout then
                failure = "runup_unavailable"
            elseif math.abs(character.x - mover.runup_target) <= 4 then
                if not p.move(nil) then failure = "unsupported_edge" else
                    mover.phase, mover.phase_time = "runup_settle", now
                    mover.runup_x, mover.runup_time = character.x, now
                end
            elseif not p.move(character.x < mover.runup_target and "right" or "left") then
                failure = "unsupported_edge"
            end
        elseif not failure and mover.phase == "runup_settle" then
            local physics = ctx.game.character and ctx.game.character.physics
            local velocity = physics and physics.velocity and physics.velocity.x
            local stable = type(velocity) ~= "number" and now > mover.runup_time and character.x == mover.runup_x
            if not character.on_ground or character.x < mover.runup_left or character.x > mover.runup_right
                or now - mover.phase_time >= 0.5 then
                failure = "runup_unavailable"
            elseif not p.move(nil) then
                failure = "unsupported_edge"
            elseif (type(velocity) == "number" and math.abs(velocity) < 1) or stable then
                mover.phase, mover.phase_time = "runup", now
                mover.runup_x, mover.runup_time = character.x, now
            else
                mover.runup_x, mover.runup_time = character.x, now
            end
        elseif not failure and mover.phase == "runup" then
            local dt = now - mover.runup_time
            local speed = dt > 0 and (character.x - mover.runup_x) * mover.runup_sign / dt or 0
            if not character.on_ground or character.x < mover.runup_left or character.x > mover.runup_right
                or now - mover.phase_time >= 1.5 or (character.x - edge.x) * mover.runup_sign > 12 then
                failure = "runup_unavailable"
            elseif not p.move(mover.runup_direction) then
                failure = "unsupported_edge"
            elseif math.abs(character.x - edge.x) <= 12 and speed >= 40 then
                if not p.jump() then failure = "unsupported_edge" else
                    mover.phase, mover.phase_time, mover.start_y, mover.jump_held = "launch", now, character.y, true
                end
            end
            mover.runup_x, mover.runup_time = character.x, now
        elseif not failure and mover.phase == "align" then
            local tolerance = edge.kind == "rope" and 4 or 8
            local vertical = (edge.kind == "jumpup" and edge.x == edge.destination) or edge.kind == "downjump"
            local physics = vertical and ctx.game.character and ctx.game.character.physics
            local align_x = (physics and physics.x) or character.x
            if edge.kind ~= "drop" and math.abs(align_x - edge.x) > tolerance then
                if not p.move(align_x < edge.x and "right" or "left") then failure = "unsupported_edge" end
            elseif edge.kind == "jumpup" then
                local moved = p.move(nil)
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
                    if not p.move(nil) then failure = "unsupported_edge" else
                        mover.downjump_preheld = nil
                        return "running"
                    end
                elseif not mover.downjump_preheld then
                    if not p.move("down") then failure = "unsupported_edge" else
                        mover.downjump_preheld = true
                        return "running"
                    end
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
            -- 爬升中持续按住方向；只有落到目标平台才完成，落到别的平台报 landing_mismatch。
            if math.abs(character.x - edge.x) > 4 then
                failure = "rope_mismatch"
            else
                local platform = character.on_ground == true
                    and terrain.platform_at(mover.graph, character.x, character.y, 20) or nil
                if character.on_ground == true and platform == edge.to then
                    p.move(nil)
                    mover.phase = "complete"
                else
                    if character.on_ground == true and platform ~= nil and platform ~= edge.from then
                        failure = "landing_mismatch"
                    end
                    if not failure then
                        if not p.move(edge.rise < 0 and "up" or "down") then failure = "unsupported_edge"
                        elseif now - mover.progress_time >= 2 then
                            if math.abs(character.y - mover.progress_y) < 5 then failure = "no_progress" end
                            mover.progress_time, mover.progress_y = now, character.y
                        end
                    end
                end
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
            mover.downjump_preheld = nil
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
