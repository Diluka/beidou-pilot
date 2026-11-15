-- tick 旅行脚本包：逐边/逐段执行层。
--
-- 消费 terrain 生成的可执行边与平台图，按相位机驱动 walk/step/jumpup/drop/rope，
-- 并提供同平台 walk_to 与门户 enter_portal；只写方向/动作输入，不选路、不做任务
-- 决策。执行失败只写 state.loco.failure 上报，转由 travel_core 决定重规划或终止。
local terrain = require("terrain")

local locomotion = {}

local WALK_TOLERANCE = 12
local ALIGN_TOLERANCE = 8
local PLATFORM_TOLERANCE = 25
local EDGE_ATTEMPT_LIMIT = 5
local EDGE_TICK_LIMIT = 150
local SETTLE_TICKS = 2
local STILL_SPEED = 12
local ACTION_STUCK_TICKS = 90
local PORTAL_TOLERANCE = 10

local function finite(value)
    return type(value) == "number" and value == value and value ~= math.huge and value ~= -math.huge
end

-- state.loco：唯一写者是 locomotion；travel_core 只读（失败由 take_failure 取走）。
function locomotion.state(context)
    local loco = context.state.loco
    if loco == nil then
        loco = { blocked = {}, blocked_count = 0, edge_attempts = 0, edge_ticks = 0 }
        context.state.loco = loco
    end
    return loco
end

local function current_platform(graph, character)
    if graph == nil or character == nil or not finite(character.x) or not finite(character.y) then return nil end
    return terrain.platform_at(graph, character.x, character.y, PLATFORM_TOLERANCE)
end

local function still(character)
    local velocity = character.velocity
    return velocity == nil or velocity.x == nil or math.abs(velocity.x) < STILL_SPEED
end

-- 动作忙时等待；长时间忙死则撤下动作槽并上报 action_stuck，由任务层终止或重试。
local function action_ready(loco, player)
    local status = player.status()
    if status.busy == true then
        loco.busy_ticks = (loco.busy_ticks or 0) + 1
        if loco.busy_ticks > ACTION_STUCK_TICKS then
            loco.busy_ticks = 0
            player.skill(nil)
            player.move(nil)
            loco.failure = "action_stuck"
            loco.failure_detail = "native action busy too long"
            loco.path, loco.index, loco.edge, loco.edge_phase = nil, nil, nil, nil
            return "stuck"
        end
        return false
    end
    loco.busy_ticks = 0
    return true
end

-- 助跑距离：按角色有效移速缩放（130px/s 时约 78px，与已验证单图执行器的 80px 一致）。
local function run_up_distance(character)
    local movement = character.movement
    local speed = type(movement) == "table" and movement.max_speed or nil
    if finite(speed) and speed > 0 then return math.max(40, math.min(120, speed * 0.6)) end
    return 80
end

local function direction_of(from_x, to_x)
    if to_x >= from_x then return "right" end
    return "left"
end

local function move_toward(player, character, target_x)
    local dx = target_x - character.x
    if math.abs(dx) <= ALIGN_TOLERANCE then
        player.move(nil)
        return true
    end
    player.move(dx > 0 and "right" or "left")
    return false
end

local function begin_edge(context, loco, edge)
    loco.edge = edge
    loco.edge_phase = "align"
    loco.edge_ticks = 0
    loco.edge_attempts = 0
    loco.airborne = false
    context.game.log(
        string.format(
            "travel_edge kind=%s from=%d to=%d x=%.1f dest=%.1f climb=%.1f",
            edge.kind,
            edge.from,
            edge.to,
            edge.x,
            edge.destination,
            edge.climb or 0
        )
    )
end

local function clear_active(loco)
    loco.path, loco.index = nil, nil
    loco.edge, loco.edge_phase = nil, nil
    loco.edge_ticks = 0
end

local function block_edge(context, loco, edge)
    local key = terrain.edge_key(edge)
    if not loco.blocked[key] then
        loco.blocked[key] = true
        loco.blocked_count = (loco.blocked_count or 0) + 1
    end
    context.game.log(
        string.format(
            "travel_edge_blocked kind=%s from=%d to=%d attempts=%d",
            edge.kind,
            edge.from,
            edge.to,
            loco.edge_attempts
        )
    )
    loco.failure = "edge_timeout"
    loco.failure_detail = edge.kind
    clear_active(loco)
    context.game.player.move(nil)
end

-- 单条边的逐 tick 相位机。返回：
-- "completed" 完成 | "retry" 失败可重试 | "replan" 已不在起点平台需重新规划 |
-- "stuck" 动作忙死（已写 failure） | nil 继续执行。
local function handle_edge(loco, character, player, graph)
    loco.edge_ticks = loco.edge_ticks + 1
    if loco.edge_ticks > EDGE_TICK_LIMIT then return "retry" end
    local edge = loco.edge
    local phase = loco.edge_phase
    -- 对齐阶段必须仍在起点平台；walk 直接走跨平台接缝，不做起点平台校验。
    if phase == "align" and edge.kind ~= "walk" then
        local platform = current_platform(graph, character)
        if platform == nil or platform.index ~= edge.from then return "replan" end
    end

    if edge.kind == "jumpup" then
        local from_platform = graph.platforms[edge.from]
        if phase == "align" then
            local target_x = from_platform and terrain.platform_inside(from_platform, edge.x) or edge.x
            if move_toward(player, character, target_x) and character.on_ground == true then
                loco.edge_phase = "settle"
                loco.settle_ticks = 0
            end
        elseif phase == "settle" then
            loco.settle_ticks = (loco.settle_ticks or 0) + 1
            player.move(nil)
            local ready = action_ready(loco, player)
            if ready == "stuck" then return "stuck" end
            if ready and character.on_ground == true and still(character) and loco.settle_ticks >= SETTLE_TICKS then
                if player.jump() then
                    loco.edge_phase = "air"
                    loco.airborne = false
                end
            end
        elseif phase == "air" then
            if character.on_ground == false then
                loco.airborne = true
            elseif loco.airborne and character.on_ground == true then
                local platform = current_platform(graph, character)
                if platform ~= nil and platform.index == edge.to then return "completed" end
                return "retry"
            end
        end
    elseif edge.kind == "step" then
        local direction = direction_of(character.x, edge.destination)
        local sign = direction == "right" and 1 or -1
        if phase == "align" then
            -- 助跑距离足以加速到参考满速：按有效移速缩放，平台不够宽时贴到平台另一端。
            local from_platform = graph.platforms[edge.from]
            local run_x = edge.x
            if from_platform ~= nil then
                run_x = terrain.platform_inside(from_platform, edge.x - sign * run_up_distance(character))
                if math.abs(run_x - edge.x) < 30 then
                    run_x = sign > 0 and from_platform.left + 6 or from_platform.right - 6
                end
            end
            if move_toward(player, character, run_x) and character.on_ground == true then
                player.move(direction)
                loco.edge_phase = "run"
                loco.run_ticks = 0
            end
        elseif phase == "run" then
            loco.run_ticks = (loco.run_ticks or 0) + 1
            local at_edge = character.x ~= nil and (character.x - edge.x) * sign >= 0
            if character.on_ground == false then
                loco.edge_phase = "air"
                loco.airborne = true
            elseif at_edge then
                -- 起跳必须保持满速水平惯性；动作槽忙时先停下等待，避免冲出平台。
                local status = player.status()
                if status.busy == true then
                    player.move(nil)
                else
                    player.move(direction)
                    if player.jump() then
                        loco.edge_phase = "air"
                        loco.airborne = false
                    end
                end
            else
                player.move(direction)
            end
        elseif phase == "air" then
            -- 水平惯性决定落点：方向保持贯穿整个腾空，落地后才清。
            player.move(direction)
            if character.on_ground == false then
                loco.airborne = true
            elseif loco.airborne and character.on_ground == true then
                player.move(nil)
                local platform = current_platform(graph, character)
                if platform ~= nil and platform.index == edge.to then return "completed" end
                return "retry"
            end
        end
    elseif edge.kind == "drop" then
        local direction = direction_of(character.x, edge.destination)
        local sign = direction == "right" and 1 or -1
        if phase == "align" then
            if move_toward(player, character, edge.x) then loco.edge_phase = "walk_off" end
        elseif phase == "walk_off" then
            player.move(direction)
            local outside = character.x ~= nil and (character.x - edge.x) * sign >= 4
            if outside and character.on_ground == false then
                loco.edge_phase = "air"
                loco.airborne = true
            end
        elseif phase == "air" then
            if character.on_ground == true then
                player.move(nil)
                local platform = current_platform(graph, character)
                if platform ~= nil and platform.index == edge.to then return "completed" end
                return "retry"
            end
        end
    elseif edge.kind == "rope" then
        local rope_x = edge.rope_x or edge.x
        if phase == "align" then
            local from_platform = graph.platforms[edge.from]
            local target_x = from_platform and terrain.platform_inside(from_platform, rope_x) or rope_x
            if move_toward(player, character, target_x) and character.on_ground == true then
                loco.edge_phase = "settle"
                loco.settle_ticks = 0
            end
        elseif phase == "settle" then
            -- 抓绳要求起跳时没有水平惯性，否则会漂离绳轴；先停稳再起跳并按住上。
            loco.settle_ticks = (loco.settle_ticks or 0) + 1
            player.move(nil)
            local ready = action_ready(loco, player)
            if ready == "stuck" then return "stuck" end
            if ready and character.on_ground == true and still(character) and loco.settle_ticks >= SETTLE_TICKS then
                if player.jump() then
                    player.move("up")
                    loco.edge_phase = "climb"
                    loco.climb_ticks = 0
                end
            end
        elseif phase == "climb" then
            loco.climb_ticks = (loco.climb_ticks or 0) + 1
            player.move("up")
            local platform = current_platform(graph, character)
            if platform ~= nil and platform.index == edge.to then
                player.move(nil)
                return "completed"
            end
            if character.on_ground == true and loco.climb_ticks > 5 then return "retry" end
        end
    elseif edge.kind == "walk" then
        local dx = edge.destination - character.x
        if math.abs(dx) <= WALK_TOLERANCE then
            player.move(nil)
            return "completed"
        end
        player.move(direction_of(character.x, edge.destination))
    else
        return "retry"
    end
    return nil
end

-- 完成一条边后推进路径：还有下一条则开始它并继续占用本 tick。
local function advance_path(context, loco)
    loco.edge, loco.edge_phase = nil, nil
    loco.index = (loco.index or 0) + 1
    local edge = loco.path and loco.path[loco.index] or nil
    if edge ~= nil then
        begin_edge(context, loco, edge)
        return true
    end
    clear_active(loco)
    return false
end

function locomotion.plan(context, from_platform, to_platform)
    local loco = locomotion.state(context)
    local graph = terrain.cached(context.state)
    if graph == nil then return false, "terrain_unavailable" end
    clear_active(loco)
    if from_platform == to_platform then return true end
    local path = terrain.plan(graph, from_platform, to_platform, loco.blocked)
    if path == nil or #path == 0 then return false, "no_viable_path" end
    loco.path, loco.index = path, 1
    begin_edge(context, loco, path[1])
    return true
end

function locomotion.walk_to(context, target_x, tolerance)
    local loco = locomotion.state(context)
    loco.walk_target = target_x
    loco.walk_tolerance = tolerance or WALK_TOLERANCE
end

-- 门户：站到门户坐标、停稳后保持 up；实际换图由原生引擎处理。
function locomotion.enter_portal(context, portal_x, tolerance)
    local loco = locomotion.state(context)
    loco.portal = { x = portal_x, tolerance = tolerance or PORTAL_TOLERANCE, settle_ticks = 0 }
    loco.portal_holding = false
end

-- 任务层取走失败上报，并把执行器恢复到可重新规划状态。
function locomotion.take_failure(context)
    local loco = locomotion.state(context)
    local reason, detail = loco.failure, loco.failure_detail
    loco.failure, loco.failure_detail = nil, nil
    return reason, detail
end

function locomotion.clear(context)
    local loco = locomotion.state(context)
    clear_active(loco)
    loco.walk_target, loco.walk_tolerance = nil, nil
    loco.portal, loco.portal_holding = nil, false
    loco.settle_ticks, loco.run_ticks, loco.climb_ticks = nil, nil, nil
    context.game.player.move(nil)
end

-- 会话初始化：清空执行器状态与代次禁边；只应由任务层 boot 调用一次。
function locomotion.reset(context)
    local loco = locomotion.state(context)
    locomotion.clear(context)
    loco.failure, loco.failure_detail = nil, nil
    loco.blocked = {}
    loco.blocked_count = 0
    loco.edge_attempts = 0
    loco.busy_ticks = 0
    loco.generation = nil
end

local function update_walk_target(context, loco, character, player)
    local dx = loco.walk_target - character.x
    if math.abs(dx) <= (loco.walk_tolerance or WALK_TOLERANCE) then
        player.move(nil)
        loco.walk_target = nil
        return true
    end
    player.move(dx > 0 and "right" or "left")
    return false
end

local function update_portal(context, loco, character, player)
    local portal = loco.portal
    local dx = portal.x - character.x
    if math.abs(dx) > portal.tolerance then
        loco.portal_holding = false
        portal.settle_ticks = 0
        player.move(dx > 0 and "right" or "left")
        return
    end
    player.move(nil)
    if character.on_ground == true and still(character) then
        portal.settle_ticks = portal.settle_ticks + 1
    else
        portal.settle_ticks = 0
    end
    if portal.settle_ticks >= SETTLE_TICKS then
        player.move("up")
        loco.portal_holding = true
    end
end

function locomotion.step(context)
    local loco = locomotion.state(context)
    local generation = context.scene and context.scene.scene_generation
    if loco.generation ~= generation then
        -- 场景代次变化：旧图路径与按代次禁边全部失效；换图时引擎已清旧输入。
        loco.generation = generation
        clear_active(loco)
        loco.walk_target, loco.walk_tolerance = nil, nil
        loco.portal, loco.portal_holding = nil, false
        loco.failure, loco.failure_detail = nil, nil
        loco.blocked, loco.blocked_count = {}, 0
        loco.busy_ticks = 0
    end
    if loco.failure ~= nil then return nil end

    local character = context.game.character
    if character == nil or not finite(character.x) or not finite(character.y) then
        if loco.edge ~= nil or loco.path ~= nil or loco.walk_target ~= nil or loco.portal ~= nil then return "halt" end
        return nil
    end
    local player = context.game.player

    if loco.portal ~= nil then
        update_portal(context, loco, character, player)
        -- 门户等待由任务层判定超时，因此本层不让出调度。
        return nil
    end
    if loco.edge ~= nil then
        local graph = terrain.cached(context.state)
        if graph == nil then
            loco.failure = "terrain_unavailable"
            loco.failure_detail = "platform_graph_missing"
            clear_active(loco)
            player.move(nil)
            return nil
        end
        local result = handle_edge(loco, character, player, graph)
        if result == "completed" then
            if advance_path(context, loco) then return "halt" end
            return nil
        elseif result == "retry" then
            loco.edge_attempts = (loco.edge_attempts or 0) + 1
            player.move(nil)
            if loco.edge_attempts > EDGE_ATTEMPT_LIMIT then
                block_edge(context, loco, loco.edge)
                return nil
            end
            loco.edge_phase, loco.edge_ticks = "align", 0
            return "halt"
        elseif result == "replan" then
            loco.failure = "edge_replan"
            loco.failure_detail = "left_start_platform"
            clear_active(loco)
            player.move(nil)
            return nil
        elseif result == "stuck" then
            return nil
        end
        return "halt"
    end
    if loco.path ~= nil then
        -- 正常不会出现「有路径但没有活动边」；推进下一条，避免静默卡死。
        if advance_path(context, loco) then return "halt" end
        return nil
    end
    if loco.walk_target ~= nil then
        local done = update_walk_target(context, loco, character, player)
        if done then return nil end
        return "halt"
    end
    return nil
end

return locomotion
