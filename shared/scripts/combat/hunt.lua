-- 单场景连续狩猎。地形是原客户端静态资料，实时目标与动作由本端观察决定。
local started = game.time()
local deadline = options.seconds and started + math.max(0, options.seconds - 0.25) or math.huge
local platforms, segments, by_id, edges = {}, {}, {}, {}
local terrain_left, terrain_right = math.huge, -math.huge
local function segment_height(segment, x)
    return segment.y1 + (segment.y2 - segment.y1) * (x - segment.left) / (segment.right - segment.left)
end
local function height(platform, x)
    for _, segment in ipairs(platform.segments) do
        if x <= segment.right then return segment_height(segment, x) end
    end
    return segment_height(platform.segments[#platform.segments], x)
end
local function inside(platform, x) return math.max(platform.left, math.min(platform.right, x)) end
for _, foothold in ipairs(options.terrain.footholds) do
    terrain_left = math.min(terrain_left, foothold.x1, foothold.x2)
    terrain_right = math.max(terrain_right, foothold.x1, foothold.x2)
    if foothold.x1 ~= foothold.x2 then
        local left, right = math.min(foothold.x1, foothold.x2), math.max(foothold.x1, foothold.x2)
        local y1, y2 = foothold.y1, foothold.y2
        if foothold.x1 > foothold.x2 then
            y1, y2 = y2, y1
        end
        local raw = { left = left, right = right, y1 = y1, y2 = y2 }
        left, right = math.max(left, options.min_x), math.min(right, options.max_x)
        if left < right then
            local segment = {
                id = foothold.id,
                prev = foothold.prev,
                next = foothold.next,
                left = left,
                right = right,
                y1 = segment_height(raw, left),
                y2 = segment_height(raw, right),
            }
            segments[#segments + 1], by_id[segment.id] = segment, segment
        end
    end
end
-- 原始段的接缝不是落边。只合并直接相连、端点相同的非竖直地面，保留各段高度。
local assigned = {}
for _, segment in ipairs(segments) do
    if not assigned[segment.id] then
        local parts, cursor = { segment }, 1
        assigned[segment.id] = true
        while cursor <= #parts do
            local part = parts[cursor]
            cursor = cursor + 1
            for _, id in ipairs({ part.prev, part.next }) do
                local neighbor = by_id[id]
                if neighbor and not assigned[id] then
                    local joins_right = part.right == neighbor.left and part.y2 == neighbor.y1
                    local joins_left = part.left == neighbor.right and part.y1 == neighbor.y2
                    if joins_right or joins_left then
                        assigned[id], parts[#parts + 1] = true, neighbor
                    end
                end
            end
        end
        table.sort(parts, function(a, b) return a.left < b.left end)
        local first, last = parts[1], parts[#parts]
        platforms[#platforms + 1] = {
            left = first.left,
            right = last.right,
            y1 = first.y1,
            y2 = last.y2,
            segments = parts,
        }
    end
end
table.sort(platforms, function(a, b) return a.y1 == b.y1 and a.left < b.left or a.y1 < b.y1 end)
for i in ipairs(platforms) do
    edges[i] = {}
end
local function connect(from, to, kind, x, destination_x, rope)
    if from ~= to then
        edges[from][#edges[from] + 1] =
            { from = from, to = to, kind = kind, x = x, destination_x = destination_x, rope = rope }
    end
end
-- 同高接缝和低台阶。竖墙两侧的高度差不会被当作平地。
for i, a in ipairs(platforms) do
    for j, b in ipairs(platforms) do
        if i ~= j then
            local direction = a.right <= b.left and 1 or -1
            local ax, bx = direction == 1 and a.right or a.left, direction == 1 and b.left or b.right
            local gap, rise = (bx - ax) * direction, height(a, ax) - height(b, bx)
            if gap >= 0 and gap <= 2 and math.abs(rise) <= 6 then
                connect(i, j, "walk", inside(a, ax - direction * 8), inside(b, bx + direction * 14))
            elseif gap >= 0 and gap <= 20 and rise > 6 and rise <= 75 then
                connect(i, j, "step", inside(a, ax - direction * 12), inside(b, bx + direction * 24))
            end
        end
    end
    -- 只落向离开边缘后脚下最近的一层，不能穿过中间平台。
    for _, direction in ipairs({ -1, 1 }) do
        local edge_x = direction == -1 and a.left or a.right
        local x, below, below_y = edge_x + direction * 12, nil, math.huge
        -- 仅为静态落边候选预留角色空间，不将地图原始极限当作可站立的实时边界。
        if x >= options.min_x and x <= options.max_x and x >= terrain_left + 30 and x <= terrain_right - 30 then
            for j, b in ipairs(platforms) do
                if j ~= i and x >= b.left and x <= b.right then
                    local y = height(b, x)
                    if y > height(a, edge_x) + 6 and y < below_y then
                        below, below_y = j, y
                    end
                end
            end
            if below then connect(i, below, "drop", inside(a, edge_x - direction * 8), x) end
        end
    end
end
for _, rope in ipairs(options.terrain.ropes) do
    local top, bottom, bottom_distance = nil, nil, math.huge
    for i, platform in ipairs(platforms) do
        if rope.x >= platform.left and rope.x <= platform.right then
            local y = height(platform, rope.x)
            if math.abs(y - rope.y1) <= 12 then top = i end
            local distance = y - rope.y2
            if distance >= -5 and distance <= 55 and distance < bottom_distance then
                bottom, bottom_distance = i, distance
            end
        end
    end
    if top and bottom then
        connect(bottom, top, "rope", rope.x, rope.x, rope)
        connect(top, bottom, "rope", rope.x, rope.x, rope)
    end
end

local attempts, dispatched, rejected, transitions = 0, 0, 0, 0
local move_seconds, attack_seconds, search_seconds = 0, 0, 0
local function finish(reason)
    game.stop()
    game.log(
        string.format(
            "hunt_summary reason=%s elapsed=%.2f attack_attempts=%d dispatched=%d rejected=%d transitions=%d move_s=%.2f attack_s=%.2f search_s=%.2f",
            reason,
            game.time() - started,
            attempts,
            dispatched,
            rejected,
            transitions,
            move_seconds,
            attack_seconds,
            search_seconds
        )
    )
end
local function current_state()
    local s = game.state()
    assert(s.ready and s.character and s.position, "hunt_state_unavailable")
    assert(
        s.instance_id == options.instance_id
            and s.character.id == options.character_id
            and s.map_id == options.map_id
            and s.scene_generation == options.scene_generation,
        "hunt_context_changed"
    )
    assert(
        s.character.hp and s.character.max_hp and s.character.level and s.character.experience,
        "hunt_character_unavailable"
    )
    assert(s.character.hp > 0, "dead")
    assert(s.character.hp / s.character.max_hp >= options.min_hp_ratio, "hunt_hp_limit")
    assert(s.position.x >= options.min_x and s.position.x <= options.max_x, "hunt_outside_area")
    assert(s.monsters, "hunt_monsters_unavailable")
    return s
end
local function platform_at(x, y, tolerance)
    local selected, nearest = nil, tolerance
    for i, platform in ipairs(platforms) do
        if x >= platform.left - 3 and x <= platform.right + 3 then
            local distance = math.abs(height(platform, x) - y)
            if distance <= nearest then
                selected, nearest = i, distance
            end
        end
    end
    return selected
end
-- 绳梯几何只给出恢复候选，不表示原生攀爬状态。到已知端点后，
-- 必须实际横移离开绳轴并复采平台位置，才能恢复找怪。
local function rope_at(s)
    local candidate
    for _, rope in ipairs(options.terrain.ropes) do
        if math.abs(s.position.x - rope.x) <= 5 and s.position.y >= rope.y1 - 6 and s.position.y <= rope.y2 + 6 then
            assert(not candidate, "hunt_rope_recovery_ambiguous")
            candidate = rope
        end
    end
    return candidate
end
local function recovery_action(result)
    assert(not result or result.reason ~= "control_preempted", "control_preempted")
end
local function recover_rope(s, rope)
    local destination, nearest = nil, math.huge
    for i, platform in ipairs(platforms) do
        if rope.x >= platform.left and rope.x <= platform.right then
            local y = height(platform, rope.x)
            local direction = math.abs(y - rope.y1) <= 12 and "up"
                or y >= rope.y2 - 5 and y <= rope.y2 + 55 and "down"
            local side = platform.right - rope.x >= rope.x - platform.left and 1 or -1
            local x = rope.x + side * 12
            if direction and x >= platform.left and x <= platform.right and math.abs(y - s.position.y) < nearest then
                destination, nearest = { platform = i, direction = direction, x = x, y = y }, math.abs(y - s.position.y)
            end
        end
    end
    assert(destination, "hunt_rope_recovery_no_safe_endpoint")
    game.log(string.format("hunt_rope_recovery start_x=%.1f start_y=%.1f rope_x=%.1f direction=%s goal_y=%.1f",
        s.position.x, s.position.y, rope.x, destination.direction, destination.y))
    recovery_action(game.stop())
    game.sleep(0.15)
    local until_at, progress_at, previous_y = math.min(deadline, game.time() + 12), game.time(), s.position.y
    while game.time() < until_at do
        s = current_state()
        assert(math.abs(s.position.x - rope.x) <= 18, "hunt_rope_recovery_left_rope")
        if math.abs(s.position.y - previous_y) > 2 then progress_at, previous_y = game.time(), s.position.y end
        if platform_at(s.position.x, s.position.y, 5) == destination.platform then
            local before_x = s.position.x
            recovery_action(game.move(destination.x > s.position.x and "right" or "left", 0.06))
            recovery_action(game.stop())
            game.sleep(0.15)
            local after = current_state()
            if math.abs(after.position.x - before_x) > 1 and math.abs(after.position.x - rope.x) >= 6
                and platform_at(after.position.x, after.position.y, 5) == destination.platform then
                game.log(string.format("hunt_rope_recovered x=%.1f y=%.1f", after.position.x, after.position.y))
                return after
            end
        end
        if game.time() - progress_at >= 3 then
            recovery_action(game.stop())
            error("hunt_rope_recovery_stalled")
        end
        if game.time() >= until_at then break end
        recovery_action(game.move(destination.direction, math.min(0.12, until_at - game.time())))
    end
    recovery_action(game.stop())
    error("hunt_rope_recovery_budget")
end
local last_experience, last_target_hp, combat_since, attack_target_id = nil, nil, nil, nil
local function try_attack(s, direction, seconds)
    local target, nearest = nil, math.huge
    for _, mob in ipairs(s.monsters) do
        local dx = mob.x - s.position.x
        if
            mob.active
            and (not options.mob_id or mob.template_id == options.mob_id)
            and mob.x >= options.min_x
            and mob.x <= options.max_x
            and math.abs(dx) <= options.attack_range
            and math.abs(mob.y - s.position.y) <= 45
            and (not direction or direction == (dx >= 0 and "right" or "left"))
        then
            if mob.object_id == attack_target_id then
                target = mob
                break
            end
            if math.abs(dx) < nearest then
                target, nearest = mob, math.abs(dx)
            end
        end
    end
    if not target then return false end
    local dx = target.x - s.position.x
    local facing = dx >= 0 and "Right" or "Left"
    if
        attack_target_id ~= target.object_id
        or last_experience ~= s.character.experience
        or last_target_hp and target.hp_percent and target.hp_percent < last_target_hp
    then
        combat_since = nil
    end
    attack_target_id, last_experience, last_target_hp = target.object_id, s.character.experience, target.hp_percent
    combat_since = combat_since or game.time()
    assert(game.time() - combat_since < 20, "hunt_combat_progress_unconfirmed")
    if s.facing ~= facing then
        assert(s.facing, "hunt_facing_unavailable")
        -- 原生攻击动画可能锁住转向。保留移动意图、暂不加攻击，再按新采样决定出手。
        if direction then
            game.move(direction, seconds)
        else
            game.face(dx >= 0 and "right" or "left")
        end
        game.sleep(0.05)
        return true
    end
    local before = game.time()
    local result = game.attack(seconds, direction, options.skill_id)
    attempts = attempts + 1
    local accepted = options.skill_id and result.skill_dispatched or not options.skill_id and result.dispatched
    if accepted then
        dispatched = dispatched + 1
    else
        rejected = rejected + 1
    end
    game.sleep(0.05)
    attack_seconds = attack_seconds + game.time() - before
    return true
end
local function move_x(s, x, allow_attack)
    local dx = x - s.position.x
    if math.abs(dx) <= 4 then return false, false end
    local direction, seconds = dx > 0 and "right" or "left", math.min(0.12, math.max(0.02, math.abs(dx) / 150))
    local attack_intent = allow_attack and try_attack(s, direction, seconds) or false
    if not attack_intent then game.move(direction, seconds) end
    return true, attack_intent
end
local target_id, travel, airborne_since = nil, nil, nil
local initial_rope_checked = false
local visited, patrol_direction = {}, 1
local heal_at, report_at = 0, started
local approach, unreachable_since
while game.time() < deadline do
    local s = current_state()
    if options.stop_level and s.character.level >= options.stop_level then
        finish("level_limit")
        return
    end
    if game.time() >= report_at then
        game.log(
            string.format(
                "hunt_state elapsed=%.2f level=%d experience=%d hp=%d x=%.1f y=%.1f target=%s",
                game.time() - started,
                s.character.level,
                s.character.experience,
                s.character.hp,
                s.position.x,
                s.position.y,
                tostring(target_id)
            )
        )
        report_at = game.time() + 5
    end
    if options.hp_item_id and s.character.hp < s.character.max_hp * 0.6 and game.time() >= heal_at then
        assert(s.inventory, "hunt_inventory_unavailable")
        local quantity = 0
        for _, item in ipairs(s.inventory) do
            if item.item_id == options.hp_item_id then
                assert(item.quantity, "hunt_hp_item_quantity_unknown")
                quantity = quantity + item.quantity
            end
        end
        assert(quantity > 0, "hunt_hp_item_depleted")
        game.use_item(options.hp_item_id)
        heal_at = game.time() + 0.8
        s = current_state()
    end
    local here = platform_at(s.position.x, s.position.y, 12)
    if not travel and (not initial_rope_checked or not here) then
        initial_rope_checked = true
        local rope = rope_at(s)
        if rope then
            s = recover_rope(s, rope)
            here, airborne_since, target_id, approach = platform_at(s.position.x, s.position.y, 12), nil, nil, nil
        end
    end
    if travel then
        local before = game.time()
        local destination = platforms[travel.to]
        if travel.stage ~= travel.last_stage then
            travel.last_stage, travel.stage_at, travel.progress_at, travel.nearest =
                travel.stage, game.time(), game.time(), math.huge
        end
        local remaining = travel.stage == "align" and math.abs(s.position.x - travel.x)
            or math.abs(s.position.x - travel.destination_x)
                + math.abs(s.position.y - height(destination, travel.destination_x))
        if remaining < travel.nearest - 2 then
            travel.progress_at, travel.nearest = game.time(), remaining
        end
        local grounded = here and math.abs(s.position.y - height(platforms[here], s.position.x)) <= 5
        local local_target = false
        if travel.stage == "align" and grounded then
            for _, mob in ipairs(s.monsters) do
                if
                    mob.active
                    and (not options.mob_id or mob.template_id == options.mob_id)
                    and mob.x >= options.min_x
                    and mob.x <= options.max_x
                    and platform_at(mob.x, mob.y, 45) == here
                then
                    local_target = true
                    break
                end
            end
        end
        if
            here
            and here ~= travel.from
            and here ~= travel.to
            and (travel.kind ~= "rope" or math.abs(s.position.x - travel.x) > 18)
            and grounded
        then
            game.stop()
            travel = nil
        elseif travel.stage == "settle" and here == travel.to and grounded then
            transitions, travel = transitions + 1, nil
        elseif local_target then
            -- 接近路段时先处理当前层的新目标，避免一直追逐过时的跨层目标。
            game.stop()
            travel, target_id = nil, nil
        elseif
            game.time() - travel.progress_at >= 3
            or travel.stage ~= "align" and game.time() - travel.stage_at >= 12
        then
            game.log(
                string.format(
                    "hunt_navigation_blocked kind=%s from=%d to=%d stage=%s x=%.1f y=%.1f goal_x=%.1f goal_y=%.1f target=%s idle_s=%.2f stage_s=%.2f",
                    travel.kind,
                    travel.from,
                    travel.to,
                    travel.stage,
                    s.position.x,
                    s.position.y,
                    travel.stage == "align" and travel.x or travel.destination_x,
                    height(destination, travel.destination_x),
                    tostring(target_id),
                    game.time() - travel.progress_at,
                    game.time() - travel.stage_at
                )
            )
            game.stop()
            assert(grounded, "hunt_navigation_stalled")
            -- 静态候选边经本端实际尝试失败后，本次会话不再重试该边。
            travel.edge.blocked = true
            travel, target_id, approach = nil, nil, nil
        elseif travel.stage == "settle" then
            if not try_attack(s, nil, 0.12) then game.sleep(0.05) end
        elseif travel.kind == "rope" then
            local upward = height(platforms[travel.from], travel.x) > height(destination, travel.x)
            local beyond = upward and s.position.y < travel.rope.y1 - 6
                or not upward
                    and (s.position.y > travel.rope.y2 + 6 or here == travel.to and s.position.y >= travel.rope.y2 - 2)
            if upward and here == travel.to and math.abs(s.position.y - height(destination, s.position.x)) <= 5 then
                -- 原生可能已越过绳顶并落回平台，采样未必保留过顶瞬间。
                -- 单独横向输入在攀爬中不会移动；向平台内部实际横移后再确认落层。
                local direction = destination.right - travel.x >= travel.x - destination.left and 1 or -1
                local x = inside(destination, travel.x + direction * 8)
                local dx = x - s.position.x
                if math.abs(dx) > 1 then
                    game.move(dx > 0 and "right" or "left", math.min(0.08, math.abs(dx) / 150))
                    local after = current_state()
                    if math.abs(after.position.x - s.position.x) > 1 then
                        game.stop()
                        travel.stage = "settle"
                    else
                        game.move("up", 0.12)
                    end
                else
                    game.move("up", 0.12)
                end
            elseif beyond then
                game.stop()
                travel.stage = "settle"
                game.sleep(0.1)
            elseif travel.stage == "align" then
                if move_x(s, travel.x) then
                    -- 接近绳索时卸去横向惯性，避免跳起后滑出抓绳范围。
                    if math.abs(s.position.x - travel.x) < 40 then
                        game.stop()
                        game.sleep(0.15)
                    end
                else
                    game.stop()
                    game.sleep(0.15)
                    local aligned = current_state()
                    if math.abs(aligned.position.x - travel.x) <= 5 then travel.stage = "climb" end
                end
            else
                if
                    upward
                    and s.position.y > travel.rope.y2 + 5
                    and (not travel.jump_at or game.time() - travel.jump_at >= 0.8)
                then
                    game.jump()
                    travel.jump_at = game.time()
                end
                travel.stage = "climb"
                game.move(upward and "up" or "down", 0.12)
            end
        elseif here == travel.to then
            game.stop()
            travel.stage = "settle"
        elseif travel.stage == "align" and move_x(s, travel.x, true) then
            -- 接近出发边缘。
        else
            if travel.stage == "align" and travel.kind == "step" then game.jump() end
            travel.stage = "cross"
            if not move_x(s, travel.destination_x, true) and not try_attack(s, nil, 0.12) then game.sleep(0.05) end
        end
        move_seconds = move_seconds + game.time() - before
    elseif not here then
        airborne_since = airborne_since or game.time()
        assert(game.time() - airborne_since < 3, "hunt_platform_unconfirmed")
        if not try_attack(s, nil, 0.12) then game.sleep(0.05) end
    else
        airborne_since = nil
        visited[here] = game.time()
        local parents, distance, queue = { [here] = false }, { [here] = 0 }, { here }
        local cursor = 1
        while cursor <= #queue do
            local from = queue[cursor]
            cursor = cursor + 1
            for _, edge in ipairs(edges[from]) do
                if not edge.blocked and distance[edge.to] == nil then
                    parents[edge.to], distance[edge.to] = edge, distance[from] + 1
                    queue[#queue + 1] = edge.to
                end
            end
        end
        local target, target_platform, nearest, nearest_hops = nil, nil, math.huge, math.huge
        local matching = 0
        for _, mob in ipairs(s.monsters) do
            if
                mob.active
                and (not options.mob_id or mob.template_id == options.mob_id)
                and mob.x >= options.min_x
                and mob.x <= options.max_x
            then
                matching = matching + 1
                local floor = platform_at(mob.x, mob.y, 45)
                if floor and distance[floor] ~= nil then
                    local cost = math.abs(mob.x - s.position.x)
                    if mob.object_id == target_id then cost = cost - options.attack_range end
                    if distance[floor] < nearest_hops or distance[floor] == nearest_hops and cost < nearest then
                        target, target_platform, nearest, nearest_hops = mob, floor, cost, distance[floor]
                    end
                end
            end
        end
        if target then
            unreachable_since = nil
            if target.object_id ~= target_id then approach = nil end
            target_id = target.object_id
            if target_platform == here then
                local dx = target.x - s.position.x
                -- 移动到交战距离和当前能否出手分别判断；同一窗口可以保持两个输入。
                if math.abs(dx) > options.attack_range * 0.6 then
                    local before = game.time()
                    local moving, attack_intent =
                        move_x(s, target.x - (dx > 0 and 1 or -1) * options.attack_range * 0.6, true)
                    if not moving then
                        attack_intent = try_attack(s, nil, 0.12)
                        if not attack_intent then game.sleep(0.05) end
                    end
                    if attack_intent then
                        -- 射程内的原生动画可以锁位移，此时只以战斗进展判定，不强求走近。
                        approach = nil
                    else
                        if
                            not approach
                            or math.abs(s.position.x - approach.x) + math.abs(s.position.y - approach.y) > 2
                        then
                            approach = { x = s.position.x, y = s.position.y, at = game.time() }
                        end
                        assert(game.time() - approach.at < 3, "hunt_chase_stalled")
                    end
                    move_seconds = move_seconds + game.time() - before
                else
                    approach = nil
                    if not try_attack(s, nil, 0.12) then game.sleep(0.05) end
                end
            end
        else
            target_id, approach = nil, nil
            if matching > 0 then
                unreachable_since = unreachable_since or game.time()
                assert(game.time() - unreachable_since < 5, "hunt_targets_unreachable")
            else
                unreachable_since = nil
            end
            local oldest = math.huge
            for floor in pairs(distance) do
                if floor ~= here and (visited[floor] or -math.huge) < oldest then
                    target_platform, oldest = floor, visited[floor] or -math.huge
                end
            end
            if not target_platform then
                assert(matching == 0, "hunt_targets_unreachable")
                local platform = platforms[here]
                local x = inside(platform, patrol_direction == 1 and platform.right - 12 or platform.left + 12)
                if math.abs(s.position.x - x) <= 6 then patrol_direction = -patrol_direction end
                local before = game.time()
                if not move_x(s, x) then game.sleep(0.1) end
                search_seconds = search_seconds + game.time() - before
            end
        end
        if target_platform and target_platform ~= here then
            local edge = parents[target_platform]
            while edge.from ~= here do
                edge = parents[edge.from]
            end
            travel = {
                edge = edge,
                from = edge.from,
                to = edge.to,
                kind = edge.kind,
                x = edge.x,
                destination_x = edge.destination_x,
                rope = edge.rope,
                stage = "align",
            }
            game.log(
                string.format(
                    "hunt_route kind=%s from=%d to=%d start_x=%.1f start_y=%.1f via_x=%.1f destination_x=%.1f destination_y=%.1f target=%s",
                    travel.kind,
                    travel.from,
                    travel.to,
                    s.position.x,
                    s.position.y,
                    travel.x,
                    travel.destination_x,
                    height(platforms[travel.to], travel.destination_x),
                    tostring(target_id)
                )
            )
            game.sleep(0)
        end
    end
end
finish("budget")
