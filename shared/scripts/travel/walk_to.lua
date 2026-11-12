-- 单地图跨平台移动策略：按静态地形平台图（走、跳台上升、落层、绳梯）走到目标坐标。
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
    local function fail(reason) error("walk_to_failed reason=" .. reason) end
    local function check(condition, reason)
        if not condition then fail(reason) end
    end
    -- 对话窗口占用输入时原地不动，明确报告而不是静默停留。
    local dialog = game.observe("dialog")
    if dialog.status == "ok" and dialog.data and dialog.data.dialog_open == true then
        error("walk_to_dialog_open")
    end

    local platforms, segments, by_id, edges = {}, {}, {}, {}
    local function segment_height(segment, x)
        if segment.right == segment.left then return segment.y1 end
        return segment.y1 + (segment.y2 - segment.y1) * (x - segment.left) / (segment.right - segment.left)
    end
    local function height(platform, x)
        for _, segment in ipairs(platform.segments) do
            if x <= segment.right then return segment_height(segment, x) end
        end
        return segment_height(platform.segments[#platform.segments], x)
    end
    local function inside(platform, x) return math.max(platform.left, math.min(platform.right, x)) end
    -- 手工归并排序：平台数量大的地图上 table.sort 的比较回调会落在不可让出的C调用里。
    local function sort_by(list, less)
        local width = 1
        while width < #list do
            local merged, index = {}, 1
            while index <= #list do
                local left_end = math.min(index + width - 1, #list)
                local right_end = math.min(index + 2 * width - 1, #list)
                local left, right = index, left_end + 1
                while left <= left_end or right <= right_end do
                    if right > right_end or (left <= left_end and not less(list[right], list[left])) then
                        merged[#merged + 1], left = list[left], left + 1
                    else
                        merged[#merged + 1], right = list[right], right + 1
                    end
                end
                index = right_end + 1
            end
            list, width = merged, width * 2
            game.sleep(0)
        end
        return list
    end

    for _, foothold in ipairs(terrain.footholds) do
        if foothold.x1 ~= foothold.x2 then
            local left, right = math.min(foothold.x1, foothold.x2), math.max(foothold.x1, foothold.x2)
            local y1, y2 = foothold.y1, foothold.y2
            if foothold.x1 > foothold.x2 then y1, y2 = y2, y1 end
            local segment = {
                id = foothold.id, prev = foothold.prev, next = foothold.next,
                left = left, right = right, y1 = y1, y2 = y2,
            }
            segments[#segments + 1], by_id[segment.id] = segment, segment
        end
    end
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
            parts = sort_by(parts, function(a, b) return a.left < b.left end)
            local first, last = parts[1], parts[#parts]
            platforms[#platforms + 1] = {
                left = first.left, right = last.right,
                y1 = first.y1, y2 = last.y2, segments = parts,
            }
        end
    end
    for i in ipairs(platforms) do edges[i] = {} end
    local function connect(from, to, kind, x, destination_x, rope, rise)
        if from == to then return end
        edges[from][#edges[from] + 1] =
            { from = from, to = to, kind = kind, x = x, destination_x = destination_x, rope = rope, rise = rise }
    end
    for i, a in ipairs(platforms) do
        for j, b in ipairs(platforms) do
            if i ~= j then
                local direction = a.right <= b.left and 1 or -1
                local ax, bx = direction == 1 and a.right or a.left, direction == 1 and b.left or b.right
                local gap, rise = (bx - ax) * direction, height(a, ax) - height(b, bx)
                if gap >= 0 and gap <= 2 and math.abs(rise) <= 6 then
                    connect(i, j, "walk", inside(a, ax - direction * 8), inside(b, bx + direction * 14), nil, rise)
                elseif gap >= 0 and gap <= 20 and rise > 6 and rise <= 75 then
                    connect(i, j, "step", inside(a, ax - direction * 12), inside(b, bx + direction * 24), nil, rise)
                end
            end
        end
        for _, direction in ipairs({ -1, 1 }) do
            local edge_x = direction == -1 and a.left or a.right
            local x, below, below_y = edge_x + direction * 12, nil, math.huge
            for j, b in ipairs(platforms) do
                if j ~= i and x >= b.left and x <= b.right then
                    local y = height(b, x)
                    if y > height(a, edge_x) + 6 and y < below_y then below, below_y = j, y end
                end
            end
            if below then
                connect(i, below, "drop", inside(a, edge_x - direction * 8), x, nil,
                    height(platforms[below], x) - height(a, edge_x))
            end
        end
        -- 跳台上行：与上方平台有足够重叠、高差在起跳可及范围内；站在其下原地起跳即可落下。
        for j, b in ipairs(platforms) do
            if j ~= i then
                local overlap_left, overlap_right = math.max(a.left, b.left), math.min(a.right, b.right)
                if overlap_right - overlap_left >= 10 then
                    local probe = (overlap_left + overlap_right) / 2
                    local rise = height(a, probe) - height(b, probe)
                    if rise > 6 and rise <= 80 then
                        connect(i, j, "jumpup", inside(a, probe), inside(b, probe), nil, rise)
                    end
                end
            end
        end
    end
    for _, rope in ipairs(terrain.ropes) do
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
            connect(bottom, top, "rope", rope.x, rope.x, rope, height(platforms[bottom], rope.x) - height(platforms[top], rope.x))
            connect(top, bottom, "rope", rope.x, rope.x, rope, height(platforms[top], rope.x) - height(platforms[bottom], rope.x))
        end
    end

    local initial = travel_initial(context, options.min_hp_ratio, fail)
    local function state()
        return travel_state(initial, options.min_hp_ratio, deadline, false, fail)
    end
    local function platform_at(x, y, tolerance)
        local selected, nearest = nil, tolerance
        for i, platform in ipairs(platforms) do
            if x >= platform.left - 3 and x <= platform.right + 3 then
                local distance = math.abs(height(platform, x) - y)
                if distance <= nearest then selected, nearest = i, distance end
            end
        end
        return selected
    end
    local function here(s) return platform_at(s.position.x, s.position.y, 12) end
    local goal = platform_at(options.target_x, options.target_y, 12)
    check(goal ~= nil, "target_not_on_foothold")
    local start = here(initial)
    check(start ~= nil, "start_platform_unknown")

    local function plan(from)
        local distance, queue, parents = { [from] = 0 }, { from }, { [from] = false }
        local cursor = 1
        while cursor <= #queue do
            local current = queue[cursor]
            cursor = cursor + 1
            for _, edge in ipairs(edges[current]) do
                if distance[edge.to] == nil then
                    parents[edge.to], distance[edge.to] = edge, distance[current] + 1
                    queue[#queue + 1] = edge.to
                end
            end
        end
        if distance[goal] == nil then return nil end
        local path, node = {}, goal
        while parents[node] do
            table.insert(path, 1, parents[node])
            node = parents[node].from
        end
        return path
    end
    local path = plan(start)
    if path == nil then error("walk_to_failed reason=no_path") end
    for index, edge in ipairs(path) do
        game.log(string.format(
            "walk_to_plan step=%d kind=%s from=%d to=%d rise=%s x=%.1f destination_x=%.1f",
            index, edge.kind, edge.from, edge.to, tostring(edge.rise and math.floor(edge.rise)),
            edge.x, edge.destination_x or edge.x
        ))
    end
    if options.plan_only then return end

    local function move_toward_x(x, tolerance)
        local until_at = math.min(deadline, game.time() + 5)
        while game.time() < until_at do
            local s = state()
            local dx = x - s.position.x
            if math.abs(dx) <= tolerance then return true end
            travel_action(game.move(dx > 0 and "right" or "left", math.min(0.12, math.max(0.03, math.abs(dx) / 150))), fail)
        end
        return false
    end
    local function step_edge(edge)
        if edge.kind == "walk" then
            move_toward_x(edge.destination_x, 6)
        elseif edge.kind == "step" then
            if math.abs(state().position.x - edge.x) > 10 then move_toward_x(edge.x, 8) end
            travel_action(game.jump(), fail)
            game.sleep(0.05)
            move_toward_x(edge.destination_x, 6)
        elseif edge.kind == "jumpup" then
            local s = state()
            local to = platforms[edge.to]
            -- 站到目标平台正下方，原地起跳后自然落回上层。
            local target_x = math.max(math.min(s.position.x, to.right - 10), to.left + 10)
            target_x = inside(platforms[edge.from], target_x)
            if math.abs(s.position.x - target_x) > 6 then
                move_toward_x(target_x, 4)
                travel_action(game.stop(), fail)
                game.sleep(0.12)
            end
            local start_y = state().position.y
            travel_action(game.jump(), fail)
            local until_at = math.min(deadline, game.time() + 1.5)
            while game.time() < until_at do
                local now = state()
                if platform_at(now.position.x, now.position.y, 4) and now.position.y < start_y - 10 then return end
                game.sleep(0.06)
            end
        elseif edge.kind == "drop" then
            local s = state()
            local direction = edge.destination_x > s.position.x and "right" or "left"
            local until_at = math.min(deadline, game.time() + 4)
            local start_y = s.position.y
            while game.time() < until_at do
                s = state()
                if s.position.y > start_y + 20 then break end
                travel_action(game.move(direction, 0.12), fail)
            end
            until_at = math.min(deadline, game.time() + 3)
            while game.time() < until_at do
                s = state()
                if platform_at(s.position.x, s.position.y, 8) then break end
                game.sleep(0.05)
            end
        elseif edge.kind == "rope" then
            local rope = edge.rope
            local upward = height(platforms[edge.from], rope.x) > height(platforms[edge.to], rope.x)
            local stop_y = upward and (rope.y1 + 2) or (rope.y2 - 2)
            for _ = 1, 2 do
                local s = state()
                local dx = rope.x - s.position.x
                if math.abs(dx) > 2 then
                    travel_action(
                        game.move(dx > 0 and "right" or "left", math.min(0.12, math.max(0.02, math.abs(dx) / 150))), fail)
                    game.sleep(0.05)
                    s = state()
                end
                local hold = math.max(0.3, math.min(9, math.abs(stop_y - s.position.y) / 90 + 1.5))
                if upward then travel_action(game.jump(), fail) end
                travel_action(game.move(upward and "up" or "down", hold), fail)
                travel_action(game.stop(), fail)
                game.sleep(0.25)
                local after = state()
                if math.abs(after.position.x - rope.x) <= 18
                    and (upward and after.position.y <= stop_y + 6 or not upward and after.position.y >= stop_y - 6)
                then
                    break
                end
            end
            local s = state()
            local direction = inside(platforms[edge.to], rope.x + 12) > s.position.x and "right" or "left"
            travel_action(game.move(direction, 0.1), fail)
        end
        travel_action(game.stop(), fail)
        game.sleep(0.1)
    end

    local attempts = 0
    while game.time() < deadline do
        local s = state()
        local current = here(s)
        check(current ~= nil, "platform_unknown")
        if current == goal then
            if math.abs(s.position.x - options.target_x) <= 8 then
                -- 停止后仍可能带着惯性滑动，稳定在目标附近才报告到达。
                travel_action(game.stop(), fail)
                game.sleep(0.25)
                local settled = state()
                if here(settled) == goal and math.abs(settled.position.x - options.target_x) <= options.tolerance
                    and math.abs(settled.position.y - options.target_y) <= 45 then
                    game.log(string.format("walk_to_arrived x=%.1f y=%.1f", settled.position.x, settled.position.y))
                    return
                end
            else
                move_toward_x(options.target_x, 8)
                travel_action(game.stop(), fail)
                game.sleep(0.1)
            end
        else
            local next_path = plan(current)
            check(next_path ~= nil, "no_path_from_current")
            local edge = next_path[1]
            attempts = attempts + 1
            check(attempts <= 40, "attempt_limit")
            game.log(string.format(
                "walk_to_exec attempt=%d kind=%s from=%d to=%d x=%.1f y=%.1f",
                attempts, edge.kind, edge.from, edge.to, s.position.x, s.position.y
            ))
            step_edge(edge)
            if here(state()) == nil then
                local until_at = math.min(deadline, game.time() + 2)
                while game.time() < until_at and here(state()) == nil do game.sleep(0.1) end
            end
        end
    end
    travel_action(game.stop(), fail)
    error("walk_to_failed reason=budget_exhausted")
end
