local M = {}

function M.new(graph)
    return {graph = graph, status = "done"}
end

function M.set_path(mover, edges)
    if type(edges) ~= "table" then return false, "invalid_edge" end
    mover.edges, mover.index, mover.status = edges, 1, "running"
    mover.started, mover.retries, mover.reason, mover.downjump_preheld, mover.last_failure = nil, 0, nil, nil, nil
    mover.runup_failure_detail = nil
    mover.on_rope, mover.rope_index = nil, nil
    return true
end

function M.stop(mover)
    game.player.move(nil)
    game.player.skill(nil)
    mover.stop_pending = mover.stop_pending or mover.jump_held or nil
    mover.status, mover.started, mover.jump_held, mover.downjump_preheld = "done", nil, nil, nil
    mover.on_rope, mover.rope_index = nil, nil
end

-- 绳梯攀爬每 30ms 直接把 y 写 3px，GUI 下 physics.velocity 可能是 0 或未知，不能用于判定附着。
-- 跳跃弧线每步 y 变化随重力连续改变，2..4px 的窗口最多连续出现一次（连续两次以上即可排除普通跳跃）；
-- 因此把连续三次同向约 3px 的采样视为已进入攀爬步进。
local function climb_step(mover, character, axis_x, rope, tick_delta)
    local function reset()
        mover.rope_step_streak, mover.rope_last_y = 0, character.y
        return false
    end
    if character.on_ground == true or math.abs(character.x - axis_x) > 10 then return reset() end
    if type(rope) == "table" and type(rope.y1) == "number" and type(rope.y2) == "number" then
        local top, bottom = math.min(rope.y1, rope.y2), math.max(rope.y1, rope.y2)
        if character.y < top - 20 or character.y > bottom + 20 then return reset() end
    end
    local previous = mover.rope_last_y
    mover.rope_last_y = character.y
    if type(previous) ~= "number" then
        mover.rope_step_streak = 0
        return false
    end
    local dy = character.y - previous
    -- 同一原生更新的重复样本不算新的一步，也不打断连续计数。
    if dy == 0 then return false end
    local rise = -dy
    -- 攀爬每个 tick 的位移由 tick 间隔决定（100px/s；30ms tick 约 3px，100ms tick 约 10px），
    -- 不能按固定 3px 窗口判定。跳跃弧线受重力影响每 tick 位移连续变化，不会连续 3 次落在同一窗口。
    local delta = type(tick_delta) == "number" and tick_delta > 0 and tick_delta or 0.03
    local expected = 100 * delta
    if rise >= expected * 0.55 and rise <= expected * 1.5 then
        mover.rope_step_streak = mover.rope_step_streak + 1
        return mover.rope_step_streak >= 3
    end
    mover.rope_step_streak = 0
    return false
end

local function rope_at(graph, rope_index)
    local ropes = type(graph) == "table" and graph.ropes
    if type(ropes) ~= "table" or type(rope_index) ~= "number" then return nil end
    for _, rope in ipairs(ropes) do
        if type(rope) == "table" and rope.index == rope_index then return rope end
    end
end

local function step(mover, ctx, world)
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
    elseif edge.kind ~= "walk" and edge.kind ~= "step" and edge.kind ~= "jumpup" and edge.kind ~= "horizontal_jump" and edge.kind ~= "downjump" and edge.kind ~= "drop" and edge.kind ~= "rope"
        and edge.kind ~= "rope_grab" and edge.kind ~= "rope_climb" and edge.kind ~= "rope_leave" and edge.kind ~= "rope_hop" then
        reason = "unsupported_edge"
    elseif (edge.kind ~= "rope_climb" and type(edge.destination) ~= "number") or (edge.kind == "step" and type(edge.to) ~= "number") then
        reason = "invalid_edge"
    end
    local character = world and world.character
    if not reason and (not character or type(character.x) ~= "number" or type(character.y) ~= "number" or ((edge.kind == "jumpup" or edge.kind == "horizontal_jump" or edge.kind == "downjump" or edge.kind == "drop" or edge.kind == "rope" or edge.kind == "rope_grab" or edge.kind == "rope_climb" or edge.kind == "rope_leave" or edge.kind == "rope_hop") and type(character.on_ground) ~= "boolean")) then
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
                if platform ~= edge.to or math.abs(character.x - edge.destination) > 32 then
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
    if edge.kind == "rope_grab" or edge.kind == "rope_climb" or edge.kind == "rope_leave" or edge.kind == "rope_hop" then
        local p = ctx.game.player
        local terrain = require("lib.terrain")
        local invalid
        if edge.kind == "rope_climb" then
            if type(edge.x) ~= "number" or type(edge.target_y) ~= "number" then invalid = true end
        elseif edge.kind == "rope_leave" then
            if type(edge.x) ~= "number" or type(edge.destination) ~= "number" or type(edge.to) ~= "number" then
                invalid = true
            end
        elseif edge.kind == "rope_hop" then
            -- rope_hop 只用目标绳轴决定跳跃方向；x 是源绳轴，执行时由当前绳上位置代替。
            if type(edge.destination) ~= "number" then invalid = true end
        elseif type(edge.x) ~= "number" or type(edge.destination) ~= "number" then
            invalid = true
        end
        if invalid then
            p.move(nil)
            if mover.jump_held then p.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
            mover.status, mover.reason = "failed", "invalid_edge"
            return "failed", mover.reason
        end
        -- 绳上状态无法靠重复同一相位恢复，缺失或绳索不匹配时直接失败，不做重试。
        -- rope_hop 的 rope_index 是目标绳，源绳记录在 from_rope_index。
        local source_rope = edge.kind == "rope_hop" and edge.from_rope_index or edge.rope_index
        if edge.kind ~= "rope_grab" and (mover.on_rope ~= true
            or (type(source_rope) == "number" and type(mover.rope_index) == "number"
                and source_rope ~= mover.rope_index)) then
            p.move(nil)
            mover.on_rope, mover.rope_index = nil, nil
            mover.status, mover.reason = "failed", "rope_mismatch"
            return "failed", mover.reason
        end
        if mover.active_edges ~= mover.edges or mover.active_index ~= mover.index then
            mover.active_edges, mover.active_index, mover.edge_started = mover.edges, mover.index, now
            mover.airborne, mover.downjump_preheld = nil, nil
            local movement = ctx.game.character and ctx.game.character.movement
            local speed = movement and movement.max_speed
            if type(speed) ~= "number" or speed <= 0 or speed ~= speed or speed == math.huge then speed = 100 end
            if edge.kind == "rope_grab" then
                mover.edge_timeout = 10 + 2 * math.abs(edge.x - character.x) / speed
            elseif edge.kind == "rope_climb" then
                mover.edge_timeout = 10 + 2 * math.abs(edge.target_y - character.y) / 100
            else
                mover.edge_timeout = 10
            end
        end
        if not mover.started then
            if mover.retries == 0 then mover.edge_started, mover.airborne = now, nil end
            mover.started, mover.phase_time = now, now
            mover.rope_last_y, mover.rope_step_streak = nil, 0
            mover.leave_preheld, mover.rope_align_wait = nil, nil
            if edge.kind == "rope_grab" then
                local rope = rope_at(mover.graph, edge.rope_index)
                local top, bottom
                if type(rope) == "table" and type(rope.y1) == "number" and type(rope.y2) == "number" then
                    top, bottom = math.min(rope.y1, rope.y2), math.max(rope.y1, rope.y2)
                end
                local grab_y = type(edge.grab_y) == "number" and edge.grab_y or edge.destination
                if top and bottom and bottom >= character.y - 20 and top <= character.y then
                    -- 绳段进入脚下 20px 的原版地面向上抓取区间：走到绳轴后按上即可附着，无需跳跃。
                    mover.phase = "ground"
                elseif grab_y - character.y > 10 then
                    -- 抓点明显低于平台：走到平台边缘走出后下落抓取。
                    mover.phase = "walkoff"
                else
                    mover.phase = "align"
                end
            elseif edge.kind == "rope_climb" then
                mover.phase = "climb"
                mover.progress_time, mover.progress_y = now, character.y
                local rope = rope_at(mover.graph, edge.rope_index)
                if type(rope) == "table" and type(rope.y1) == "number" and type(rope.y2) == "number" then
                    local top = math.min(rope.y1, rope.y2)
                    -- 靠近绳顶时继续按上，让原版顶端退出把角色放到上层平台。
                    mover.climb_top_exit = math.abs(edge.target_y - top) <= 10
                else
                    mover.climb_top_exit = nil
                end
            elseif edge.kind == "rope_hop" then
                mover.phase = "hop"
                mover.leave_direction = edge.destination >= character.x and "right" or "left"
            else
                mover.phase = "leave"
                mover.leave_direction = edge.destination >= character.x and "right" or "left"
                mover.progress_time, mover.progress_x = now, character.x
                -- 落点与绳轴几乎同列时不做无意义跳跃，按上到绳顶自然脱绳再校验落点平台。
                mover.leave_top_exit = math.abs(edge.destination - edge.x) <= 8
            end
        end
        local failure
        if now - mover.edge_started >= mover.edge_timeout then
            if edge.kind == "rope_leave" then
                failure = "landing_mismatch"
            elseif edge.kind == "rope_grab" or edge.kind == "rope_hop" then
                failure = "rope_grab_failed"
            else
                failure = "timeout"
            end
        end
        if not failure and mover.phase == "ground" then
            if character.on_ground == false then
                mover.phase, mover.phase_time, mover.airborne = "grab", now, true
                if not p.move("up") then failure = "unsupported_edge" end
            elseif math.abs(character.x - edge.destination) > 8 then
                if not p.move(character.x < edge.destination and "right" or "left") then failure = "unsupported_edge" end
            elseif not p.move("up") then
                failure = "unsupported_edge"
            end
        elseif not failure and mover.phase == "align" then
            if character.on_ground == false then
                -- 起跳前先落回平台；不在地面时不推进相位，超时兜底。
                if not p.move(nil) then failure = "unsupported_edge" end
            elseif math.abs(character.x - edge.x) > 8 then
                mover.rope_align_wait = nil
                if not p.move(character.x < edge.x and "right" or "left") then failure = "unsupported_edge" end
            else
                -- 走动惯性会把起跳点带离绳轴，导致下落段错过 ±10 抓取窗口；先刹停再跳。
                local physics = ctx.game.character and ctx.game.character.physics
                local velocity_x = physics and physics.velocity and physics.velocity.x
                local settled = type(velocity_x) ~= "number" or math.abs(velocity_x) <= 1
                if not settled and (mover.rope_align_wait or 0) < 10 then
                    mover.rope_align_wait = (mover.rope_align_wait or 0) + 1
                    if not p.move(nil) then failure = "unsupported_edge" end
                else
                    local direction
                    if edge.destination - edge.x > 6 then direction = "right"
                    elseif edge.x - edge.destination > 6 then direction = "left" end
                    if not (p.move(direction) and p.jump()) then failure = "unsupported_edge" else
                        mover.phase, mover.phase_time, mover.jump_held = "grab", now, true
                        mover.airborne, mover.rope_align_wait = nil, nil
                    end
                end
            end
        elseif not failure and mover.phase == "walkoff" then
            if character.on_ground == false then
                mover.phase, mover.phase_time, mover.airborne = "grab", now, true
                if not p.move("up") then failure = "unsupported_edge" end
            else
                local direction
                if edge.destination > character.x then
                    direction = "right"
                elseif edge.destination < character.x then
                    direction = "left"
                else
                    local platforms = type(mover.graph) == "table" and mover.graph.platforms
                    local platform = type(platforms) == "table" and edge.from and platforms[edge.from] or nil
                    direction = type(platform) == "table" and platform.open_left and "left" or "right"
                end
                if not p.move(direction) then failure = "unsupported_edge" end
            end
        elseif not failure and mover.phase == "grab" then
            if not p.move("up") then failure = "unsupported_edge" end
            if not failure and mover.jump_held and now - mover.phase_time >= 0.3 then
                p.skill(nil)
                mover.jump_held, mover.release_tick = nil, ctx.tick.index
            end
            if character.on_ground == false then mover.airborne = true end
            if not failure and mover.airborne and character.on_ground == true then
                failure = "rope_grab_failed"
            end
            if not failure and character.on_ground == false
                and climb_step(mover, character, edge.destination, rope_at(mover.graph, edge.rope_index),
                    ctx.tick and ctx.tick.delta) then
                if mover.jump_held then p.skill(nil); mover.jump_held = nil end
                p.move(nil)
                mover.on_rope, mover.rope_index = true, edge.rope_index
                mover.phase = "complete"
            end
        elseif not failure and mover.phase == "climb" then
            local delta = edge.target_y - character.y
            if math.abs(character.x - edge.x) > 10 then
                failure = "rope_mismatch"
            elseif mover.climb_top_exit then
                -- 绳顶退出：继续按上，等原版顶端逻辑让角色落到上层平台，或被顶端钳住不再移动。
                if character.on_ground == true then
                    p.move(nil)
                    mover.phase = "complete"
                else
                    if not p.move("up") then failure = "unsupported_edge" end
                    if not failure and character.y == mover.rope_last_y then
                        mover.rope_step_streak = (mover.rope_step_streak or 0) + 1
                        if mover.rope_step_streak >= 3 then p.move(nil); mover.phase = "complete" end
                    else
                        mover.rope_step_streak = 0
                    end
                    mover.rope_last_y = character.y
                    if not failure and mover.phase == "climb" and now - mover.progress_time >= 2 then
                        if math.abs(character.y - mover.progress_y) < 5 then failure = "no_progress" end
                        mover.progress_time, mover.progress_y = now, character.y
                    end
                end
            elseif math.abs(delta) <= 6 then
                p.move(nil)
                mover.phase = "complete"
            elseif character.on_ground == true then
                failure = "rope_mismatch"
            else
                if not p.move(delta < 0 and "up" or "down") then
                    failure = "unsupported_edge"
                elseif character.y == mover.rope_last_y then
                    -- 附着时每 30ms 至少移动 3px；连续无变化说明已掉离绳梯。
                    mover.rope_step_streak = (mover.rope_step_streak or 0) + 1
                    if mover.rope_step_streak >= 3 then failure = "rope_mismatch" end
                else
                    mover.rope_step_streak = 0
                end
                mover.rope_last_y = character.y
                if not failure and now - mover.progress_time >= 2 then
                    if math.abs(character.y - mover.progress_y) < 5 then failure = "no_progress" end
                    mover.progress_time, mover.progress_y = now, character.y
                end
            end
        elseif not failure and mover.phase == "hop" then
            if not p.move(mover.leave_direction) then
                failure = "unsupported_edge"
            elseif mover.leave_preheld then
                if not p.jump() then
                    failure = "unsupported_edge"
                else
                    mover.phase, mover.phase_time, mover.jump_held = "hop_flight", now, true
                    mover.airborne = nil
                end
            else
                mover.leave_preheld = true
            end
        elseif not failure and mover.phase == "hop_flight" then
            if not p.move("up") then failure = "unsupported_edge" end
            if not failure and mover.jump_held and now - mover.phase_time >= 0.3 then
                p.skill(nil)
                mover.jump_held, mover.release_tick = nil, ctx.tick.index
            end
            if character.on_ground == false then mover.airborne = true end
            if not failure and mover.airborne and character.on_ground == true then
                failure = "rope_grab_failed"
            end
            if not failure and character.on_ground == false
                and climb_step(mover, character, edge.destination, rope_at(mover.graph, edge.rope_index),
                    ctx.tick and ctx.tick.delta) then
                if mover.jump_held then p.skill(nil); mover.jump_held = nil end
                p.move(nil)
                mover.on_rope, mover.rope_index = true, edge.rope_index
                mover.phase = "complete"
            end
        elseif not failure and mover.phase == "leave" then
            if character.on_ground == true then
                -- 爬绳顶端已经自然落到平台：直接校验落点，不再要求一次跳跃。
                local platform = terrain.platform_at(mover.graph, character.x, character.y, 20)
                if platform == edge.to and math.abs(character.x - edge.destination) <= 20 then
                    mover.phase = "complete"
                else
                    failure = "landing_mismatch"
                end
            elseif math.abs(character.x - edge.x) > 10 then
                failure = "rope_mismatch"
            elseif mover.leave_top_exit then
                -- 落点与绳轴同列：不做无意义跳跃，按上到绳顶自然脱绳，落地后校验目标平台。
                if not p.move("up") then failure = "unsupported_edge" end
            elseif not p.move(mover.leave_direction) then
                failure = "unsupported_edge"
            elseif mover.leave_preheld then
                if not p.jump() then
                    failure = "unsupported_edge"
                else
                    mover.phase, mover.phase_time, mover.jump_held = "leave_flight", now, true
                    mover.airborne = nil
                end
            else
                mover.leave_preheld = true
            end
        elseif not failure and mover.phase == "leave_flight" then
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
            if mover.jump_held then p.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
            if failure ~= "timeout" and failure ~= "landing_mismatch" and mover.retries < 1 then
                mover.retries, mover.started, mover.airborne = mover.retries + 1, nil, nil
                return "running"
            end
            mover.on_rope, mover.rope_index = nil, nil
            mover.status, mover.reason = "failed", failure
            return "failed", failure
        end
        if mover.phase == "complete" then
            p.move(nil)
            if mover.jump_held then p.skill(nil); mover.jump_held = nil end
            if edge.kind == "rope_leave" then mover.on_rope, mover.rope_index = nil, nil end
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
            mover.rope_x, mover.rope_tick = nil, nil
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
        if not failure and mover.phase == "prepare_runup" and character.on_ground == false then
            -- A newly planned edge can begin while the actor is still falling.
            -- Keep the original edge deadline and wait without issuing movement.
            if not p.move(nil) then failure = "unsupported_edge" end
        elseif not failure and mover.phase == "prepare_runup" then
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
                if not finite(edge.x) or not finite(edge.destination) then mover.runup_failure_detail = "edge_invalid"
                elseif not finite(left) or not finite(right) or left > right then mover.runup_failure_detail = "source_invalid"
                elseif not character.on_ground then mover.runup_failure_detail = "airborne"
                else mover.runup_failure_detail = "source_mismatch" end
                failure = "runup_unavailable"
            else
                local target
                for _, distance in ipairs({32, 20, 12}) do
                    local candidate = edge.x - sign * distance
                    if candidate >= left + 8 and candidate <= right - 8 then target = candidate; break end
                end
                if not target then mover.runup_failure_detail = "insufficient_space"; failure = "runup_unavailable" else
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
                mover.runup_failure_detail = not character.on_ground and "approach_airborne"
                    or (character.x < mover.runup_left or character.x > mover.runup_right) and "approach_outside_source"
                    or "approach_timeout"
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
                mover.runup_failure_detail = not character.on_ground and "settle_airborne"
                    or (character.x < mover.runup_left or character.x > mover.runup_right) and "settle_outside_source"
                    or "settle_timeout"
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
                mover.runup_failure_detail = not character.on_ground and "runup_airborne"
                    or (character.x < mover.runup_left or character.x > mover.runup_right) and "runup_outside_source"
                    or now - mover.phase_time >= 1.5 and "runup_timeout" or "launch_overshoot"
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
            local tolerance = edge.kind == "rope" and 6 or 8
            local vertical = (edge.kind == "jumpup" and edge.x == edge.destination) or edge.kind == "downjump"
            local physics = vertical and ctx.game.character and ctx.game.character.physics
            local align_x = (physics and physics.x) or character.x
            if edge.kind ~= "drop" and math.abs(align_x - edge.x) > tolerance then
                if edge.kind == "rope" then mover.rope_x, mover.rope_tick = nil, nil end
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
                local physics = ctx.game.character and ctx.game.character.physics
                local velocity = physics and physics.velocity and physics.velocity.x
                local stable = type(velocity) == "number" and math.abs(velocity) <= 1
                    or type(velocity) ~= "number" and mover.rope_x ~= nil
                        and ctx.tick.index ~= mover.rope_tick and character.x == mover.rope_x
                mover.rope_x, mover.rope_tick = character.x, ctx.tick.index
                if not stable then
                    if not p.move(nil) then failure = "unsupported_edge" end
                else
                    local ropes = mover.graph and mover.graph.ropes
                    local rope = ropes and ropes[edge.rope_index]
                    if edge.rise < 0 and rope and type(rope.y2) == "number" and character.y - rope.y2 > 10 then
                        if not p.jump() then failure = "unsupported_edge" else
                            mover.phase, mover.phase_time, mover.start_y, mover.jump_held = "rope_grab", now, character.y, true
                            if not p.move("up") then failure = "unsupported_edge" end
                        end
                    else
                        mover.phase, mover.start_y = "climb", character.y
                        mover.progress_time, mover.progress_y = now, character.y
                        if not p.move(edge.rise < 0 and "up" or "down") then failure = "unsupported_edge" end
                    end
                end
            end
        elseif not failure and mover.phase == "rope_grab" then
            if now - mover.phase_time >= 2 then
                failure = "rope_grab_failed"
            elseif not p.move("up") then
                failure = "unsupported_edge"
            elseif not character.on_ground and mover.start_y - character.y >= 10 then
                if mover.jump_held then p.skill(nil); mover.jump_held = nil end
                mover.phase = "climb"
                mover.progress_time, mover.progress_y = now, character.y
            elseif mover.jump_held and now - mover.phase_time >= 0.3 then
                p.skill(nil); mover.jump_held = nil
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
            elseif (edge.kind == "jumpup" and mover.runup_direction)
                or now - mover.phase_time >= 0.3
                or (edge.kind == "jumpup" and character.y < mover.start_y - 10) then
                if edge.kind == "jumpup" and mover.runup_direction then
                    -- 水平 jumpup：越过平台高度差前持续按住落点方向；0.3s 后释放跳跃键但方向保持到落地。
                    if character.on_ground == true and mover.airborne then
                        if mover.jump_held then p.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
                        local platform = terrain.platform_at(mover.graph, character.x, character.y, 20)
                        if platform ~= edge.to then
                            failure = "landing_mismatch"
                        else
                            mover.phase = "complete"
                        end
                    elseif now - mover.phase_time >= 0.3 then
                        if mover.jump_held then p.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
                        mover.phase = "wait"
                    end
                else
                    p.move(nil)
                    if mover.jump_held then p.skill(nil); mover.jump_held = nil; mover.release_tick = ctx.tick.index end
                    mover.phase = "wait"
                end
            end
        elseif not failure and mover.phase == "climb" then
            -- 爬升中持续按住方向；只有落到目标平台才完成，落到别的平台报 landing_mismatch。
            if math.abs(character.x - edge.x) > 6 then
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
            if not failure and character.on_ground == false and edge.kind == "jumpup" and mover.runup_direction then
                if not p.move(mover.runup_direction) then failure = "unsupported_edge" end
            end
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

function M.step(mover, ctx, world)
    local status, reason = step(mover, ctx, world)
    if status == "failed" and not mover.last_failure then
        local edge = mover.edges and mover.edges[mover.index]
        local character = world and world.character
        local platform = character and character.on_ground == true and mover.graph
            and require("lib.terrain").platform_at(mover.graph, character.x, character.y, 20) or nil
        mover.last_failure = {
            reason = reason, kind = type(edge) == "table" and edge.kind or nil,
            from = type(edge) == "table" and edge.from or nil, to = type(edge) == "table" and edge.to or nil,
            x = type(edge) == "table" and edge.x or nil, destination = type(edge) == "table" and edge.destination or nil,
            rise = type(edge) == "table" and edge.rise or nil, landing_platform = platform,
            landing_x = character and character.x, landing_y = character and character.y,
            phase = mover.phase, detail = reason == "runup_unavailable" and mover.runup_failure_detail or nil,
            on_ground = character and character.on_ground,
            velocity_x = ctx and ctx.game and ctx.game.character and ctx.game.character.physics
                and ctx.game.character.physics.velocity and ctx.game.character.physics.velocity.x,
            velocity_y = ctx and ctx.game and ctx.game.character and ctx.game.character.physics
                and ctx.game.character.physics.velocity and ctx.game.character.physics.velocity.y,
        }
    end
    return status, reason
end

return M
