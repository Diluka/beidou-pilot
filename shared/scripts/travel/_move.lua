-- 单地图执行器：给定平台图与目标坐标，逐边执行走、跳台、落层、绳梯并确认到达。
-- 由策略装载器拼接；调用方提供状态获取、失败回调与总期限，动作结果由调用方核对。
--
-- 调用约定：
--   move_to(graph, target, runtime)
--     graph    terrain_build 的平台图
--     target   { x, y, tolerance, plan_only, platform }
--     runtime  { state = fn, fail = fn(reason, stage), deadline = number, log = string, combat = table }
--     combat   { hp_item_id, heal_hp_ratio, min_hp_ratio, mob_strategy, skill_id, attack_range, clear_limit }
--   state() 由调用方实现，负责身份/地图/HP 检查并返回最新原生快照。
--   移动中按 HP 阈值持续用药；被近身怪物挡住时按策略选择喝药硬冲或清掉挡路怪物。
--   执行失败时调用 runtime.fail(reason, stage)；成功时返回稳定后的状态。

-- 入口与目标平台都允许角色身体半宽超出平台端点，和 terrain_platform_at 的边界一致。
local MOVE_PLATFORM_TOLERANCE = 25

local function move_to(graph, target, runtime)
    local state, fail, deadline = runtime.state, runtime.fail, runtime.deadline
    local prefix = runtime.log or "move"
    local platforms = graph.platforms
    local stage = "start"
    local stalled, last_hp = 0, nil

    local function fail_stage(reason) fail(reason, stage) end

    -- 移动中自保：低于阈值就用药；没有任何可用药品且低于下限时明确停止。
    local combat = runtime.combat or {}
    local heal_ratio = combat.heal_hp_ratio or 0.7
    local floor_ratio = combat.min_hp_ratio or 0.25
    local mob_strategy = combat.mob_strategy or "auto"
    local attack_range = combat.attack_range or 90
    local clear_limit = combat.clear_limit or 8
    local heal_at = 0
    local function potion_for(s)
        local candidates = combat.hp_item_id and { combat.hp_item_id } or { 2000006, 2000002, 2000001, 2000000 }
        for _, item_id in ipairs(candidates) do
            for _, item in ipairs(s.inventory or {}) do
                if item.item_id == item_id and (item.quantity or 0) > 0 then return item_id end
            end
        end
        return nil
    end
    local function sustain(s)
        if not s.character or not s.character.max_hp or s.character.max_hp <= 0 then return end
        local hp_ratio = s.character.hp / s.character.max_hp
        -- 危急先保命：HP 很低且库存有回城卷时直接撤离，避免继续挨打死亡。
        if hp_ratio < 0.22 then
            for _, item in ipairs(s.inventory or {}) do
                if item.item_id == 2030000 and (item.quantity or 0) > 0 then
                    travel_action(game.use_item(2030000), fail_stage)
                    game.sleep(1.2)
                    fail_stage("retreat_used")
                end
            end
        end
        if s.character.hp >= s.character.max_hp * heal_ratio or game.time() < heal_at then return end
        local item_id = potion_for(s)
        if not item_id then
            if s.character.hp < s.character.max_hp * floor_ratio then fail_stage("potion_exhausted") end
            return
        end
        travel_action(game.use_item(item_id), fail_stage)
        heal_at = game.time() + 0.8
    end
    -- 只把同一层附近、还在活动的怪物当作挡路目标。
    local function nearby_monster(s)
        local best, best_distance = nil, attack_range
        for _, mob in ipairs(s.monsters or {}) do
            if mob.active ~= false and mob.x and mob.y then
                local dx, dy = mob.x - s.position.x, mob.y - s.position.y
                if math.abs(dx) <= attack_range and math.abs(dy) <= 80 and math.abs(dx) < best_distance then
                    best, best_distance = mob, math.abs(dx)
                end
            end
        end
        return best
    end
    -- 清掉近身怪物：面向目标普攻或使用调用方指定技能，攻击次数有上限并持续自保。
    local function clear_monsters()
        local until_at = math.min(deadline, game.time() + 30)
        local attacks = 0
        while game.time() < until_at do
            local s = state()
            sustain(s)
            local mob = nearby_monster(s)
            if not mob then return true end
            if attacks >= clear_limit then return false end
            local direction = mob.x >= s.position.x and "right" or "left"
            if s.facing ~= direction then travel_action(game.face(direction), fail_stage) end
            if combat.skill_id then
                travel_action(game.skill(combat.skill_id), fail_stage)
            else
                travel_action(game.attack(), fail_stage)
            end
            attacks = attacks + 1
            sustain(state())
            game.sleep(0.45)
        end
        return false
    end
    -- 被挡住时的统一决策：血线充足则喝药硬冲重试，否则清掉挡路怪物；没有怪物时返回 nil。
    local function blocked_decision(after)
        local mob = nearby_monster(after)
        if not mob then return nil end
        local character = after.character or {}
        local hp_ratio = character.max_hp and character.max_hp > 0 and character.hp / character.max_hp or 1
        local hurt = last_hp and character.hp and character.max_hp and last_hp - character.hp > character.max_hp * 0.05
        if mob_strategy ~= "ignore" and (mob_strategy == "clear" or hp_ratio < 0.55 or hurt) then
            stage = "clear"
            game.log(
                string.format(
                    "%s_blocked_by_mob x=%.1f y=%.1f hp=%.0f%% strategy=%s",
                    prefix,
                    after.position.x,
                    after.position.y,
                    hp_ratio * 100,
                    mob_strategy
                )
            )
            if not clear_monsters() then fail_stage("mob_blocked") end
            return "cleared"
        end
        stalled = stalled + 1
        sustain(state())
        game.sleep(0.2)
        if stalled > 20 then fail_stage("mob_blocked") end
        return "retry"
    end
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
            sustain(state())
            game.sleep(0.05)
        end
        return state()
    end
    local function platform_of(s) return terrain_platform_at(graph, s.position.x, s.position.y, MOVE_PLATFORM_TOLERANCE) end
    -- 有界等待落地并复采平台；用于落层、跳台、绳索之后的空中状态。
    local function wait_grounded(limit)
        local until_at = math.min(deadline, game.time() + (limit or 3))
        local previous_y, stable = nil, 0
        while game.time() < until_at do
            local s = state()
            local platform = platform_of(s)
            if platform then
                local settled = settle(1)
                platform = platform_of(settled)
                if platform then return platform, settled end
            end
            -- 高度已经稳定但平台图没有覆盖时用最近平台继续，避免把可站立位置当成失败。
            if previous_y and math.abs(s.position.y - previous_y) <= 0.5 then
                stable = stable + 1
                if stable >= 2 then
                    local nearest = terrain_nearest_platform(graph, s.position.x, s.position.y)
                    if nearest then return nearest, s end
                end
            else
                stable = 0
            end
            previous_y = s.position.y
            sustain(state())
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
            sustain(s)
            local dx = x - s.position.x
            if math.abs(dx) <= tolerance then
                travel_action(game.stop(), fail_stage)
                sustain(state())
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
        sustain(state())
        game.sleep(0.15)
        for attempt = 1, 2 do
            local start_y = state().position.y
            travel_action(game.jump(), fail_stage)
            local until_at = math.min(deadline, game.time() + 1.5)
            while game.time() < until_at do
                local s = state()
                local platform = platform_of(s)
                if platform and platform.index == edge.to and s.position.y < start_y - 10 then return true end
                sustain(state())
                game.sleep(0.05)
            end
            if attempt == 1 then
                -- 起跳点可能落在平台接缝上，左右微调后重试一次。
                local s = state()
                travel_action(game.move(s.position.x < to_platform.left + 20 and "right" or "left", 0.08), fail_stage)
                sustain(state())
                game.sleep(0.1)
                travel_action(game.stop(), fail_stage)
            end
        end
        return false
    end
    local function step_up(edge)
        -- 窄台上跳需要满速起跳：在平台内预留助跑距离，跑到边缘瞬间起跳。
        local from_platform, to_platform = platforms[edge.from], platforms[edge.to]
        local target_y = terrain_height(to_platform, edge.destination_x)
        for attempt = 1, 3 do
            if attempt > 1 then
                local s = state()
                if s.position.y <= target_y + 6 then break end
                local current = platform_of(s)
                if current and current.index ~= edge.from then return false end
            end
            local s = state()
            local direction = edge.destination_x > s.position.x and "right" or "left"
            local sign = direction == "right" and 1 or -1
            local run_x = terrain_inside(from_platform, edge.x - sign * 32)
            if not move_toward_x(run_x, 6) then return false end
            travel_action(game.stop(), fail_stage)
            sustain(state())
            game.sleep(0.12)
            -- 跑到边缘的同时起跳，保留满速水平惯性。
            travel_action(game.move(direction, 0.25), fail_stage)
            travel_action(game.jump(), fail_stage)
            travel_action(game.move(direction, 0.2), fail_stage)
            local until_at = math.min(deadline, game.time() + 1.2)
            while game.time() < until_at do
                local after = state()
                local platform = platform_of(after)
                if platform and platform.index == edge.to and after.position.y <= target_y + 6 then return true end
                sustain(state())
                game.sleep(0.05)
            end
        end
        return false
    end
    local function drop(edge)
        local s = state()
        local direction = edge.destination_x > s.position.x and "right" or "left"
        if not move_toward_x(edge.x, 4) then return false end
        travel_action(game.stop(), fail_stage)
        sustain(state())
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
            sustain(state())
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
            sustain(state())
            game.sleep(0.2)
            local s = state()
            if math.abs(s.position.x - rope.x) > 3 then
                local dx = rope.x - s.position.x
                travel_action(game.move(dx > 0 and "right" or "left", 0.03), fail_stage)
                sustain(state())
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
            sustain(state())
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
        sustain(state())
        game.sleep(0.12)
        local platform = wait_grounded(3)
        return platform ~= nil and platform.index == edge.to
    end

    local starting_state = settle(2)
    local start = platform_of(starting_state)
    if not start then start = terrain_nearest_platform(graph, starting_state.position.x, starting_state.position.y) end
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
        for _ = 1, 6 do
            if move_toward_x(target.x, 8) then break end
            local after = state()
            local decision = blocked_decision(after)
            if decision == nil then fail_stage("target_align_stalled") end
        end
        travel_action(game.stop(), fail_stage)
        sustain(state())
        game.sleep(0.12)
        local aligned = state()
        -- 起点已在同一平台时也必须核对对齐结果，不能把被挡住的短距离当作到达。
        if math.abs(aligned.position.x - target.x) > target.tolerance + 3 then fail_stage("target_align_stalled") end
        return aligned
    end

    local attempts, edge_attempts, best_path, idle_rounds = 0, {}, math.huge, 0
    while game.time() < deadline do
        local s = state()
        sustain(s)
        local current = platform_of(s)
        if not current then
            current, s = wait_grounded(5)
            if not current then fail_stage("platform_unknown") end
        end
        if current.index == target.platform.index then
            if math.abs(s.position.x - target.x) <= 8 then
                -- 停止后仍可能带着惯性滑动，稳定在目标附近才报告到达。
                travel_action(game.stop(), fail_stage)
                sustain(state())
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
                    local decision = blocked_decision(after)
                    if decision == nil and math.abs(after.position.x - s.position.x) < 4 then
                        fail_stage("target_align_stalled")
                    end
                end
                travel_action(game.stop(), fail_stage)
                sustain(state())
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
                local decision = blocked_decision(after)
                if decision == "cleared" then
                    stalled = 0
                elseif decision == nil then
                    -- 本端实际尝试后没有前进且没有怪物挡路：本次会话禁用该边并重新规划。
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
                end
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
            if after.character then last_hp = after.character.hp end
        end
    end
    travel_action(game.stop(), fail_stage)
    fail_stage("budget_exhausted")
end
