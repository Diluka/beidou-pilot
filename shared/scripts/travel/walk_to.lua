-- 单地图跨平台移动策略：按静态地形图（走、跳台上升、落层、绳梯）走到目标坐标。
-- 只读取本端实时状态与动作；不攻击、不拾取、不消费。
-- @option[type=int] target_x 目标世界坐标x
-- @option[type=int] target_y 目标世界坐标y
-- @option[type=number,opt,default=30,min=1,max=120] budget_seconds 本次移动预算
-- @option[type=number,opt,default=0.25,min=0,max=1] min_hp_ratio 生命值安全比例
-- @option[type=int,opt,default=12,min=1,max=40] tolerance 到达水平容差
-- @option[type=boolean,default=false] plan_only 只输出平台路径，不移动
local function main(context)
    local options = context.options
    local scene = context.scene
    local terrain = scene.terrain
    if terrain.status ~= "available" then error("walk_to_terrain_" .. tostring(terrain.status)) end
    local deadline = game.time() + options.budget_seconds

    -- 对话窗口占用输入时原地不动，明确报告而不是静默停留。
    local dialog = game.observe("dialog")
    if dialog.status == "ok" and dialog.data and dialog.data.dialog_open == true then error("walk_to_dialog_open") end

    local graph = terrain_build(terrain, {})
    local platforms = graph.platforms
    local initial = travel_initial(context, options.min_hp_ratio, error)
    local last = initial
    local stage = "start"
    local function fail(reason)
        error(
            string.format(
                "walk_to_failed map=%d x=%.1f y=%.1f stage=%s reason=%s platforms=%d walls=%d",
                scene.map_id,
                last.position.x,
                last.position.y,
                stage,
                reason,
                #platforms,
                #graph.walls
            )
        )
    end
    local function check_state()
        last = travel_state(initial, options.min_hp_ratio, deadline, false, fail)
        return last
    end
    -- 落地稳定：连续两次采样高度不变才认为站在平台上，避免刚落图或跳跃中被当成无平台。
    local function settle(limit)
        local previous, stable = nil, 0
        local until_at = math.min(deadline, game.time() + (limit or 2))
        while game.time() < until_at do
            local s = check_state()
            if previous and math.abs(s.position.y - previous) <= 0.5 then
                stable = stable + 1
                if stable >= 2 then return s end
            else
                stable = 0
            end
            previous = s.position.y
            game.sleep(0.05)
        end
        return check_state()
    end
    local function platform_of(s) return terrain_platform_at(graph, s.position.x, s.position.y, 25) end
    -- 有界等待落地并复采平台；用于落层、跳台、绳索之后的空中状态。
    local function wait_grounded(limit)
        local until_at = math.min(deadline, game.time() + (limit or 3))
        while game.time() < until_at do
            local s = check_state()
            local platform = platform_of(s)
            if platform then
                local stable = settle(1)
                platform = platform_of(stable)
                if platform then return platform, stable end
            end
            game.sleep(0.05)
        end
        return nil, check_state()
    end

    local goal, start
    local function plan_path(from)
        local path = terrain_plan(graph, from.index, goal.index)
        return path
    end
    local starting_state = settle(2)
    start = platform_of(starting_state)
    if not start then fail("start_platform_unknown") end
    goal = terrain_platform_at(graph, options.target_x, options.target_y, 25)
    if not goal then fail("target_not_on_foothold") end

    local planned = plan_path(start)
    if not planned then fail("no_viable_path") end
    for index, edge in ipairs(planned) do
        game.log(
            string.format(
                "walk_to_plan step=%d kind=%s from=%d to=%d rise=%s x=%.1f destination_x=%.1f",
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
    if options.plan_only then return end

    local function move_toward_x(x, tolerance)
        local until_at = math.min(deadline, game.time() + 12)
        local previous, stalled = nil, 0
        while game.time() < until_at do
            local s = check_state()
            local dx = x - s.position.x
            if math.abs(dx) <= tolerance then
                travel_action(game.stop(), fail)
                game.sleep(0.12)
                local settled = check_state()
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
                    fail
                )
            end
        end
        return false
    end
    local function jump_up(edge)
        local to_platform = platforms[edge.to]
        local jump_x = edge.x
        if not move_toward_x(jump_x, 5) then return false end
        travel_action(game.stop(), fail)
        game.sleep(0.15)
        for attempt = 1, 2 do
            local start_y = check_state().position.y
            travel_action(game.jump(), fail)
            local until_at = math.min(deadline, game.time() + 1.5)
            while game.time() < until_at do
                local s = check_state()
                local platform = platform_of(s)
                if platform and platform.index == edge.to and s.position.y < start_y - 10 then return true end
                game.sleep(0.05)
            end
            if attempt == 1 then
                -- 起跳点可能落在平台接缝上，左右微调后重试一次。
                local s = check_state()
                travel_action(game.move(s.position.x < to_platform.left + 20 and "right" or "left", 0.08), fail)
                game.sleep(0.1)
                travel_action(game.stop(), fail)
            end
        end
        return false
    end
    local function step_up(edge)
        -- 相邻高差在客户端里是一串窄台，需要走到边缘后反复起跳，逐级落地。
        if math.abs(check_state().position.x - edge.x) > 10 and not move_toward_x(edge.x, 8) then return false end
        local target_y = terrain_height(platforms[edge.to], edge.destination_x)
        for jump_index = 1, 12 do
            local s = check_state()
            if s.position.y <= target_y + 6 then break end
            if jump_index == 12 then return false end
            travel_action(game.jump(), fail)
            local stable, previous = 0, nil
            local until_at = math.min(deadline, game.time() + 1.2)
            while game.time() < until_at do
                local y = check_state().position.y
                if previous and math.abs(y - previous) < 0.5 then
                    stable = stable + 1
                    if stable >= 2 then break end
                else
                    stable = 0
                end
                previous = y
                game.sleep(0.05)
            end
            local landed = check_state()
            if landed.position.y > s.position.y - 6 then
                travel_action(game.move(jump_index % 2 == 0 and "right" or "left", 0.12), fail)
                game.sleep(0.1)
                travel_action(game.stop(), fail)
            end
        end
        return move_toward_x(edge.destination_x, 6)
    end
    local function drop(edge)
        local s = check_state()
        local direction = edge.destination_x > s.position.x and "right" or "left"
        if not move_toward_x(edge.x, 4) then return false end
        travel_action(game.stop(), fail)
        game.sleep(0.15)
        local start_y = check_state().position.y
        local until_at = math.min(deadline, game.time() + 4)
        while game.time() < until_at do
            s = check_state()
            if s.position.y > start_y + 20 then break end
            travel_action(game.move(direction, 0.1), fail)
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
        if math.abs(check_state().position.x - rope.x) > 10 then
            move_toward_x(rope.x, 10)
            travel_action(game.stop(), fail)
            game.sleep(0.15)
        end
        for _ = 1, 2 do
            -- 绳轴对齐需要小幅脉冲反复收敛，单次移动会因惯性越过绳索。
            local align_until = math.min(deadline, game.time() + 6)
            while game.time() < align_until do
                local s = check_state()
                local dx = rope.x - s.position.x
                if math.abs(dx) <= 3 then break end
                travel_action(game.move(dx > 0 and "right" or "left", 0.03), fail)
            end
            travel_action(game.stop(), fail)
            game.sleep(0.2)
            local s = check_state()
            if math.abs(s.position.x - rope.x) > 3 then
                local dx = rope.x - s.position.x
                travel_action(game.move(dx > 0 and "right" or "left", 0.03), fail)
                game.sleep(0.1)
                s = check_state()
            end
            local stop_y = upward and (rope.y1 + 2) or (rope_bottom - 2)
            local hold = math.max(0.3, math.min(9, math.abs(stop_y - s.position.y) / 90 + 1.5))
            -- 绳底高于站立平台时需要跳起才能抓住；已在绳段内则直接按方向。
            local standing_on_rope = s.position.y >= rope.y1 - 6 and s.position.y <= rope.y2 + 6
            if upward and not standing_on_rope then travel_action(game.jump(), fail) end
            travel_action(game.move(upward and "up" or "down", hold), fail)
            travel_action(game.stop(), fail)
            game.sleep(0.25)
            local after = check_state()
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
        travel_action(game.stop(), fail)
        game.sleep(0.12)
        local platform = wait_grounded(3)
        return platform ~= nil and platform.index == edge.to
    end

    local attempts, stalled = 0, 0
    while game.time() < deadline do
        local s = check_state()
        local current = platform_of(s)
        if not current then
            current, s = wait_grounded(3)
            if not current then fail("platform_unknown") end
        end
        if current.index == goal.index then
            if math.abs(s.position.x - options.target_x) <= 8 then
                -- 停止后仍可能带着惯性滑动，稳定在目标附近才报告到达。
                travel_action(game.stop(), fail)
                game.sleep(0.25)
                local settled = check_state()
                local settled_platform = platform_of(settled)
                if
                    settled_platform
                    and settled_platform.index == goal.index
                    and math.abs(settled.position.x - options.target_x) <= options.tolerance
                    and math.abs(settled.position.y - options.target_y) <= 45
                then
                    game.log(string.format("walk_to_arrived x=%.1f y=%.1f", settled.position.x, settled.position.y))
                    return
                end
            else
                -- 同一平台内的长距离对齐可能超过单次移动窗口；有进展就继续下一轮。
                if not move_toward_x(options.target_x, 8) then
                    local after = check_state()
                    if math.abs(after.position.x - s.position.x) < 4 then fail("target_align_stalled") end
                end
                travel_action(game.stop(), fail)
                game.sleep(0.12)
            end
        else
            local next_path = plan_path(current)
            if not next_path then fail("no_viable_path_from_current") end
            local edge = next_path[1]
            stage = edge.kind
            attempts = attempts + 1
            if attempts > 60 then fail("attempt_limit") end
            local before_x, before_y = s.position.x, s.position.y
            game.log(
                string.format(
                    "walk_to_exec attempt=%d kind=%s from=%d to=%d x=%.1f y=%.1f",
                    attempts,
                    edge.kind,
                    edge.from,
                    edge.to,
                    before_x,
                    before_y
                )
            )
            local succeeded = run_edge(edge)
            local after = check_state()
            local after_platform = platform_of(after)
            if not after_platform then
                after_platform, after = wait_grounded(3)
                if not after_platform then fail("platform_unknown_after_" .. edge.kind) end
            end
            if after_platform.index == edge.to then
                stalled = 0
            elseif math.abs(after.position.x - before_x) < 4 and math.abs(after.position.y - before_y) < 4 then
                -- 本端实际尝试后没有前进：本次会话禁用该边并重新规划，不重试同一条。
                edge.blocked = true
                stalled = stalled + 1
                game.log(
                    string.format(
                        "walk_to_edge_blocked kind=%s from=%d to=%d x=%.1f y=%.1f",
                        edge.kind,
                        edge.from,
                        edge.to,
                        after.position.x,
                        after.position.y
                    )
                )
                if stalled > 8 then fail("no_progress") end
            else
                stalled = 0
            end
            if not succeeded and after_platform.index == edge.to then succeeded = true end
        end
    end
    travel_action(game.stop(), fail)
    fail("budget_exhausted")
end
