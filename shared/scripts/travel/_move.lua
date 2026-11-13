-- 单地图执行器：给定平台图与目标坐标，逐边执行走、跳台、落层、绳梯并确认到达。
-- 由策略装载器拼接；调用方提供状态获取、失败回调与总期限，动作结果由调用方核对。
--
-- 调用约定：
--   move_to(graph, target, runtime)
--     graph    terrain_build 的平台图
--     target   { x, y, tolerance, plan_only, platform }
--     runtime  { state = fn, fail = fn(reason, stage), deadline = number, log = string }
--   state() 由调用方实现，负责身份/地图/HP 检查并返回最新原生快照。
--   执行失败时调用 runtime.fail(reason, stage)；成功时返回稳定后的状态。

-- 入口与目标平台都允许角色身体半宽超出平台端点，和 terrain_platform_at 的边界一致。
local MOVE_PLATFORM_TOLERANCE = 25

local function move_to(graph, target, runtime)
    local state, fail, deadline = runtime.state, runtime.fail, runtime.deadline
    local prefix = runtime.log or "move"
    local platforms = graph.platforms
    local stage = "start"

    local function fail_stage(reason) fail(reason, stage) end
    -- 落地稳定：连续两次采样高度不变才认为站在平台上，避免刚落图或跳跃中被当成无平台。
    local function settle(limit)
        local previous, stable = nil, 0
        local until_at = math.min(deadline, game.time() + (limit or 2))
        while game.time() < until_at do
            local s = state()
            if previous and math.abs(s.position.y - previous) <= 0.5 then
                stable = stable + 1
                if stable >= 2 then return s end
            else
                stable = 0
            end
            previous = s.position.y
            game.sleep(0.05)
        end
        return state()
    end
    local function platform_of(s) return terrain_platform_at(graph, s.position.x, s.position.y, MOVE_PLATFORM_TOLERANCE) end
    -- 有界等待落地并复采平台；用于落层、跳台、绳索之后的空中状态。
    local function wait_grounded(limit)
        local until_at = math.min(deadline, game.time() + (limit or 3))
        while game.time() < until_at do
            local s = state()
            local platform = platform_of(s)
            if platform then
                local stable = settle(1)
                platform = platform_of(stable)
                if platform then return platform, stable end
            end
            game.sleep(0.05)
        end
        return nil, state()
    end
    local function plan_path(from)
        local goal = target.platform
        if not goal then return nil end
        return terrain_plan(graph, from.index, goal.index)
    end
    local function move_toward_x(x, tolerance)
        local until_at = math.min(deadline, game.time() + 12)
        local previous, stalled = nil, 0
        while game.time() < until_at do
            local s = state()
            local dx = x - s.position.x
            if math.abs(dx) <= tolerance then
                travel_action(game.stop(), fail_stage)
                game.sleep(0.12)
                local settled = state()
                if math.abs(settled.position.x - x) <= tolerance + 3 then return true end
            else
                if previous and math.abs(s.position.x - previous) < 1 then
                    stalled = stalled + 1
                    if stalled > 10 then return false end
                else
                    stalled = 0
                end
                previous = s.position.x
                travel_action(
                    game.move(dx > 0 and "right" or "left", math.min(0.12, math.max(0.03, math.abs(dx) / 150))),
                    fail_stage
                )
            end
        end
        return false
    end
    local function jump_up(edge)
        local to_platform = platforms[edge.to]
        if not move_toward_x(edge.x, 5) then return false end
        travel_action(game.stop(), fail_stage)
        game.sleep(0.15)
        for attempt = 1, 2 do
            local start_y = state().position.y
            travel_action(game.jump(), fail_stage)
            local until_at = math.min(deadline, game.time() + 1.5)
            while game.time() < until_at do
                local s = state()
                local platform = platform_of(s)
                if platform and platform.index == edge.to and s.position.y < start_y - 10 then return true end
                game.sleep(0.05)
            end
            if attempt == 1 then
                -- 起跳点可能落在平台接缝上，左右微调后重试一次。
                local s = state()
                travel_action(game.move(s.position.x < to_platform.left + 20 and "right" or "left", 0.08), fail_stage)
                game.sleep(0.1)
                travel_action(game.stop(), fail_stage)
            end
        end
        return false
    end
    local function step_up(edge)
        -- 相邻高差在客户端里是一串窄台，需要走到边缘后反复起跳，逐级落地。
        if math.abs(state().position.x - edge.x) > 10 and not move_toward_x(edge.x, 8) then return false end
        local target_y = terrain_height(platforms[edge.to], edge.destination_x)
        for jump_index = 1, 12 do
            local s = state()
            if s.position.y <= target_y + 6 then break end
            if jump_index == 12 then return false end
            travel_action(game.jump(), fail_stage)
            local stable, previous = 0, nil
            local until_at = math.min(deadline, game.time() + 1.2)
            while game.time() < until_at do
                local y = state().position.y
                if previous and math.abs(y - previous) < 0.5 then
                    stable = stable + 1
                    if stable >= 2 then break end
                else
                    stable = 0
                end
                previous = y
                game.sleep(0.05)
            end
            local landed = state()
            if landed.position.y > s.position.y - 6 then
                travel_action(game.move(jump_index % 2 == 0 and "right" or "left", 0.12), fail_stage)
                game.sleep(0.1)
                travel_action(game.stop(), fail_stage)
            end
        end
        return move_toward_x(edge.destination_x, 6)
    end
    local function drop(edge)
        local s = state()
        local direction = edge.destination_x > s.position.x and "right" or "left"
        if not move_toward_x(edge.x, 4) then return false end
        travel_action(game.stop(), fail_stage)
        game.sleep(0.15)
        local start_y = state().position.y
        local until_at = math.min(deadline, game.time() + 4)
        while game.time() < until_at do
            s = state()
            if s.position.y > start_y + 20 then break end
            travel_action(game.move(direction, 0.1), fail_stage)
        end
        local platform = wait_grounded(3)
        return platform ~= nil and platform.index == edge.to
    end
    local function climb(edge)
        local rope = edge.rope
        local upward = (edge.rise or 0) < 0
        local to_platform = platforms[edge.to]
        local target_y = terrain_height(to_platform, rope.x)
        local rope_bottom = math.max(rope.y2, target_y)
        if math.abs(state().position.x - rope.x) > 10 then
            move_toward_x(rope.x, 10)
            travel_action(game.stop(), fail_stage)
            game.sleep(0.15)
        end
        for _ = 1, 2 do
            -- 绳轴对齐需要小幅脉冲反复收敛，单次移动会因惯性越过绳索。
            local align_until = math.min(deadline, game.time() + 6)
            while game.time() < align_until do
                local s = state()
                local dx = rope.x - s.position.x
                if math.abs(dx) <= 3 then break end
                travel_action(game.move(dx > 0 and "right" or "left", 0.03), fail_stage)
            end
            travel_action(game.stop(), fail_stage)
            game.sleep(0.2)
            local s = state()
            if math.abs(s.position.x - rope.x) > 3 then
                local dx = rope.x - s.position.x
                travel_action(game.move(dx > 0 and "right" or "left", 0.03), fail_stage)
                game.sleep(0.1)
                s = state()
            end
            local stop_y = upward and (rope.y1 + 2) or (rope_bottom - 2)
            local hold = math.max(0.3, math.min(9, math.abs(stop_y - s.position.y) / 90 + 1.5))
            -- 绳底高于站立平台时需要跳起才能抓住；已在绳段内则直接按方向。
            local standing_on_rope = s.position.y >= rope.y1 - 6 and s.position.y <= rope.y2 + 6
            if upward and not standing_on_rope then travel_action(game.jump(), fail_stage) end
            travel_action(game.move(upward and "up" or "down", hold), fail_stage)
            travel_action(game.stop(), fail_stage)
            game.sleep(0.25)
            local after = state()
            local reached = upward and after.position.y <= target_y + 10 or after.position.y >= target_y - 10
            if math.abs(after.position.x - rope.x) <= 18 and reached then return true end
        end
        local platform = wait_grounded(3)
        return platform ~= nil and platform.index == edge.to
    end
    local function run_edge(edge)
        if edge.kind == "walk" then
            if not move_toward_x(edge.destination_x, 6) then return false end
        elseif edge.kind == "step" then
            return step_up(edge)
        elseif edge.kind == "jumpup" then
            return jump_up(edge)
        elseif edge.kind == "drop" then
            return drop(edge)
        elseif edge.kind == "rope" then
            return climb(edge)
        end
        travel_action(game.stop(), fail_stage)
        game.sleep(0.12)
        local platform = wait_grounded(3)
        return platform ~= nil and platform.index == edge.to
    end

    local starting_state = settle(2)
    local start = platform_of(starting_state)
    if not start then fail_stage("start_platform_unknown") end
    if not target.platform then fail_stage("target_not_on_foothold") end
    local planned = plan_path(start)
    if not planned then fail_stage("no_viable_path") end
    for index, edge in ipairs(planned) do
        game.log(
            string.format(
                "%s_plan step=%d kind=%s from=%d to=%d rise=%s x=%.1f destination_x=%.1f",
                prefix,
                index,
                edge.kind,
                edge.from,
                edge.to,
                tostring(edge.rise and math.floor(edge.rise)),
                edge.x,
                edge.destination_x or edge.x
            )
        )
    end
    if target.plan_only then return starting_state end
    if start.index == target.platform.index then
        if math.abs(starting_state.position.x - target.x) <= 8 then return starting_state end
        stage = "align"
        move_toward_x(target.x, 8)
        travel_action(game.stop(), fail_stage)
        game.sleep(0.12)
        return state()
    end

    local attempts, stalled, edge_attempts, best_path, idle_rounds = 0, 0, {}, math.huge, 0
    while game.time() < deadline do
        local s = state()
        local current = platform_of(s)
        if not current then
            current, s = wait_grounded(3)
            if not current then fail_stage("platform_unknown") end
        end
        if current.index == target.platform.index then
            if math.abs(s.position.x - target.x) <= 8 then
                -- 停止后仍可能带着惯性滑动，稳定在目标附近才报告到达。
                travel_action(game.stop(), fail_stage)
                game.sleep(0.25)
                local settled = state()
                local settled_platform = platform_of(settled)
                if
                    settled_platform
                    and settled_platform.index == target.platform.index
                    and math.abs(settled.position.x - target.x) <= target.tolerance
                    and math.abs(settled.position.y - target.y) <= 45
                then
                    game.log(string.format("%s_arrived x=%.1f y=%.1f", prefix, settled.position.x, settled.position.y))
                    return settled
                end
            else
                -- 同一平台内的长距离对齐可能超过单次移动窗口；有进展就继续下一轮。
                stage = "align"
                if not move_toward_x(target.x, 8) then
                    local after = state()
                    if math.abs(after.position.x - s.position.x) < 4 then fail_stage("target_align_stalled") end
                end
                travel_action(game.stop(), fail_stage)
                game.sleep(0.12)
            end
        else
            local next_path = plan_path(current)
            if not next_path then fail_stage("no_viable_path_from_current") end
            -- 路径长度长期不下降说明在平台图里绕圈，按无进展停止而不是耗尽预算。
            if #next_path < best_path then
                best_path, idle_rounds = #next_path, 0
            else
                idle_rounds = idle_rounds + 1
                if idle_rounds > 15 then fail_stage("no_progress") end
            end
            local edge = next_path[1]
            stage = edge.kind
            attempts = attempts + 1
            if attempts > 60 then fail_stage("attempt_limit") end
            local before_x, before_y = s.position.x, s.position.y
            local edge_key = edge.from .. ":" .. edge.to .. ":" .. edge.kind
            edge_attempts[edge_key] = (edge_attempts[edge_key] or 0) + 1
            game.log(
                string.format(
                    "%s_exec attempt=%d kind=%s from=%d to=%d x=%.1f y=%.1f",
                    prefix,
                    attempts,
                    edge.kind,
                    edge.from,
                    edge.to,
                    before_x,
                    before_y
                )
            )
            local succeeded = run_edge(edge)
            local after = state()
            local after_platform = platform_of(after)
            if not after_platform then
                after_platform, after = wait_grounded(3)
                if not after_platform then fail_stage("platform_unknown_after_" .. edge.kind) end
            end
            if after_platform.index == edge.to then
                edge_attempts[edge_key], stalled = nil, 0
            elseif math.abs(after.position.x - before_x) < 4 and math.abs(after.position.y - before_y) < 4 then
                -- 本端实际尝试后没有前进：本次会话禁用该边并重新规划，不重试同一条。
                edge.blocked = true
                stalled = stalled + 1
                game.log(
                    string.format(
                        "%s_edge_blocked kind=%s from=%d to=%d x=%.1f y=%.1f",
                        prefix,
                        edge.kind,
                        edge.from,
                        edge.to,
                        after.position.x,
                        after.position.y
                    )
                )
                if stalled > 8 then fail_stage("no_progress") end
            elseif (edge_attempts[edge_key] or 0) >= 3 then
                -- 位置在变但始终到不了这条边的目标平台，说明该边在本端不可执行。
                edge.blocked = true
                game.log(
                    string.format(
                        "%s_edge_blocked kind=%s from=%d to=%d attempts=%d x=%.1f y=%.1f",
                        prefix,
                        edge.kind,
                        edge.from,
                        edge.to,
                        edge_attempts[edge_key],
                        after.position.x,
                        after.position.y
                    )
                )
            else
                stalled = 0
            end
            if not succeeded and after_platform.index == edge.to then succeeded = true end
        end
    end
    travel_action(game.stop(), fail_stage)
    fail_stage("budget_exhausted")
end
