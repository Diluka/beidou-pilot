-- tick 旅行脚本包：任务层。
--
-- 消费 CLI 在启动会话前注入的 context.route（腿序列：每段 from/portal/to/portal_at）
-- 与 context.goal（{map_id,x,y}），维护 boot → leg/门户 → final → arrived 的任务
-- 状态机，调用 terrain 规划、locomotion 执行，并处理失败上报、重规划与到达判定。
--
-- 阶段范围（#176 M1/M2）：完整交付「起点图 == 目标图（legs 为空）→ 目标图内走到
-- 目标坐标 → arrived」，验证单图可达路径与安全层协作。leg/门户/换图相位是 M3 的
-- 骨架：按真实 API 实现状态迁移（post 门户、等待地图/代次变化、确认新图、剩余腿
-- 对齐），但尚未在真实客户端验证，也未实现 M3 的完备恢复（走错图改道、场景资料
-- 不可用的主动重试策略等）。
--
-- 注入形状（由 CLI `travel` 在启动会话前写入，客户端不再更新）：
--   context.route = { status="ok", start=<map>, goal=<map>,
--                     legs = { { from=<map>, portal=<name>, to=<map>,
--                                portal_at = { {x,y}, ... } }, ... } }
--   context.goal  = { map_id=<map>, x=<int>, y=<int> }
-- 路线腿来自原生只读世界门户图的有向 BFS；portal_at 是来源图上同名门户的坐标点，
-- 可能多于一个。没有注入 route/goal 时不伪造路线，明确 route_unavailable。
--
-- state.travel：唯一写者是 travel_core。phase / failed_phase / started / start_map /
-- map_id / goal / legs / leg_index / plan / portal / replans / settle_ticks /
-- platform_unknown_ticks / scene_wait_started / failure / failure_detail / goal_platform。
local terrain = require("terrain")
local locomotion = require("locomotion")

local travel_core = {}

local PLATFORM_TOLERANCE = 25
local TARGET_TOLERANCE = 40
local NEAREST_TOLERANCE = 120
local ALIGN_TOLERANCE = 8
local PORTAL_TOLERANCE = 10
local PORTAL_WAIT_SECONDS = 4
local PORTAL_RETRY_LIMIT = 2
local SCENE_WAIT_LIMIT = 15
local NO_PLATFORM_TICK_LIMIT = 120
local ARRIVE_TICKS = 2
local STILL_SPEED = 12

local function finite(value)
    return type(value) == "number" and value == value and value ~= math.huge and value ~= -math.huge
end

local function number_text(value)
    if finite(value) then return string.format("%.1f", value) end
    return "?"
end

local function fail(context, travel, reason, detail)
    travel.failed_phase = travel.failed_phase or travel.phase
    travel.phase = "failed"
    travel.failure = reason
    travel.failure_detail = detail
    return "failed"
end

-- 失败汇总文本：入口在终止会话前统一写日志并 error。
function travel_core.failure_text(context)
    local state = context.state
    local travel = state.travel or {}
    local safety = state.safety or {}
    local character = context.game.character or {}
    local scene = context.scene or {}
    local reason = travel.failure or safety.failure or "unknown"
    local detail = travel.failure_detail or safety.failure_detail or "none"
    local phase = travel.failed_phase or travel.phase or state.stage or "unknown"
    local leg = travel.leg_index ~= nil and tostring(travel.leg_index) or "-"
    local started = travel.started or state.first_tick or context.tick.time
    return string.format(
        "travel_failed phase=%s map=%s x=%s y=%s leg=%s reason=%s detail=%s heals=%d elapsed=%.2f",
        tostring(phase),
        tostring(scene.map_id),
        number_text(character.x),
        number_text(character.y),
        leg,
        tostring(reason),
        tostring(detail),
        safety.heals or 0,
        context.tick.time - started
    )
end

function travel_core.state(context)
    local travel = context.state.travel
    if travel == nil then
        travel = { phase = nil, replans = 0, settle_ticks = 0 }
        context.state.travel = travel
    end
    return travel
end

local function still(character)
    local velocity = character.velocity
    return velocity == nil or velocity.x == nil or math.abs(velocity.x) < STILL_SPEED
end

local function locate(graph, x, y)
    local platform = terrain.platform_at(graph, x, y, TARGET_TOLERANCE)
    if platform ~= nil then return platform end
    return terrain.nearest_platform(graph, x, y, NEAREST_TOLERANCE)
end

-- 地形不可用：转场等待有独立超时；其它不可用直接终止，不用链接图或另一后端补齐。
local function terrain_or_fail(context, travel)
    local graph, reason, detail = terrain.ensure(context)
    if graph ~= nil then
        travel.scene_wait_started = nil
        return graph, nil
    end
    if reason == "scene_pending" then
        travel.scene_wait_started = travel.scene_wait_started or context.tick.time
        if context.tick.time - travel.scene_wait_started > SCENE_WAIT_LIMIT then
            return nil, fail(context, travel, "terrain_unavailable", "scene_pending_timeout")
        end
        return nil, nil
    end
    return nil, fail(context, travel, "terrain_unavailable", tostring(detail))
end

-- 在当前图的剩余腿中查找当前地图（走错图 / 偏移腿的前向对齐；M3 骨架）。
local function align_leg(context, travel, map_id)
    for index = travel.leg_index, #travel.legs do
        local leg = travel.legs[index]
        if type(leg) == "table" and leg.from == map_id then
            travel.leg_index = index
            travel.map_id = map_id
            travel.plan, travel.settle_ticks = nil, 0
            travel.phase = "leg"
            return true
        end
    end
    return false
end

-- 执行层失败只上报，重规划或终止由这里决定。
local function recover(context, travel)
    local reason, detail = locomotion.take_failure(context)
    if reason == nil then return nil end
    travel.replans = (travel.replans or 0) + 1
    if reason == "action_stuck" then return fail(context, travel, "action_stuck", detail) end
    if travel.replans > context.options.max_replans then
        local terminal = reason == "edge_timeout" and "edge_timeout" or "no_viable_path"
        return fail(context, travel, terminal, detail or reason)
    end
    travel.plan, travel.settle_ticks = nil, 0
    context.game.log(string.format("travel_replan attempt=%d reason=%s", travel.replans, tostring(reason)))
    return nil
end

-- 门户坐标来自 context.route 腿的 portal_at（同名门户可能有多个点上图）；取最近可
-- 站立的一个。M3 骨架：未验证多入口、从上方/下方进入等实际触发条件。
local function choose_portal(context, leg, graph)
    local points = leg.portal_at
    if type(points) ~= "table" or #points == 0 then return nil, "portal_coordinates_missing" end
    local character = context.game.character
    local best, best_distance = nil, math.huge
    for _, point in ipairs(points) do
        if type(point) == "table" and finite(point[1]) and finite(point[2]) then
            local platform = locate(graph, point[1], point[2])
            if platform ~= nil then
                local distance = finite(character.x) and math.abs(point[1] - character.x) or 0
                if distance < best_distance then
                    best = { kind = "portal", x = point[1], y = point[2], platform = platform }
                    best_distance = distance
                end
            end
        end
    end
    if best == nil then return nil, "portal_platform_unknown" end
    return best
end

local function boot(context, travel)
    local goal = context.goal
    if type(goal) ~= "table" or not finite(goal.map_id) or not finite(goal.x) or not finite(goal.y) then
        return fail(context, travel, "route_unavailable", "goal_missing")
    end
    local route = context.route
    local legs = {}
    if route ~= nil then
        if type(route) ~= "table" then return fail(context, travel, "route_unavailable", "route_malformed") end
        if route.status ~= nil and route.status ~= "ok" then
            return fail(context, travel, "route_unavailable", "route_status_" .. tostring(route.status))
        end
        if route.legs ~= nil then
            if type(route.legs) ~= "table" then
                return fail(context, travel, "route_unavailable", "route_legs_malformed")
            end
            legs = route.legs
        end
    end
    local scene = context.scene
    travel.started = context.tick.time
    travel.start_map = scene.map_id
    travel.map_id = scene.map_id
    travel.goal = { map_id = goal.map_id, x = goal.x, y = goal.y }
    travel.legs = legs
    travel.leg_index = 1
    travel.replans = 0
    travel.settle_ticks = 0
    locomotion.reset(context)
    context.game.log(
        string.format(
            "travel_start map=%s goal=%s x=%s y=%s route_legs=%d",
            tostring(scene.map_id),
            tostring(goal.map_id),
            number_text(goal.x),
            number_text(goal.y),
            #legs
        )
    )
    if scene.map_id == goal.map_id then
        if #legs > 0 then
            -- 起点图已是目标图却仍有换图腿：调用方注入的路线与目标不一致。
            return fail(context, travel, "route_unavailable", "route_map_mismatch")
        end
        travel.phase = "final"
        return nil
    end
    if #legs == 0 then return fail(context, travel, "route_unavailable", "route_empty") end
    travel.phase = "leg"
    return nil
end

local function handle_leg(context, travel)
    local terminal = recover(context, travel)
    if terminal ~= nil then return terminal end
    local graph, failed = terrain_or_fail(context, travel)
    if failed ~= nil then return failed end
    if graph == nil then return nil end
    -- TODO(M3)：真实客户端验证多入口选择、不可达入口回退，以及腿 from 与当前图不符时的
    -- 前向对齐（当前只按剩余腿 from 匹配，无法改道时明确 map_mismatch）。
    local map_id = context.scene.map_id
    local leg = travel.legs[travel.leg_index]
    if type(leg) ~= "table" or not finite(leg.from) or not finite(leg.to) then
        return fail(context, travel, "route_unavailable", "leg_malformed")
    end
    if leg.from ~= map_id then
        if not align_leg(context, travel, map_id) then
            return fail(context, travel, "map_mismatch", "leg_from_mismatch")
        end
        leg = travel.legs[travel.leg_index]
        if type(leg) ~= "table" or not finite(leg.from) then
            return fail(context, travel, "route_unavailable", "leg_malformed")
        end
    end
    local plan = travel.plan
    if plan == nil or plan.leg_index ~= travel.leg_index or plan.generation ~= graph.generation then
        local target, reason = choose_portal(context, leg, graph)
        if target == nil then return fail(context, travel, "platform_unknown", tostring(reason)) end
        target.leg_index = travel.leg_index
        target.generation = graph.generation
        travel.plan = target
        plan = target
        context.game.log(
            string.format(
                "travel_leg index=%d map=%s portal=%s target_map=%s x=%s y=%s",
                travel.leg_index,
                tostring(map_id),
                tostring(leg.portal),
                tostring(leg.to),
                number_text(plan.x),
                number_text(plan.y)
            )
        )
    end
    local character = context.game.character
    local current = terrain.platform_at(graph, character.x, character.y, PLATFORM_TOLERANCE)
    if current == nil then
        travel.platform_unknown_ticks = (travel.platform_unknown_ticks or 0) + 1
        if travel.platform_unknown_ticks > NO_PLATFORM_TICK_LIMIT then
            return fail(context, travel, "platform_unknown", "current_platform")
        end
        return nil
    end
    travel.platform_unknown_ticks = 0
    if current.index == plan.platform.index then
        travel.phase = "portal_align"
        travel.settle_ticks = 0
        locomotion.walk_to(context, plan.x, ALIGN_TOLERANCE)
        return nil
    end
    local ok, reason = locomotion.plan(context, current.index, plan.platform.index)
    if not ok then return fail(context, travel, "no_viable_path", tostring(reason)) end
    return nil
end

local function handle_portal_align(context, travel)
    local terminal = recover(context, travel)
    if terminal ~= nil then return terminal end
    local graph, failed = terrain_or_fail(context, travel)
    if failed ~= nil then return failed end
    if graph == nil then return nil end
    local plan = travel.plan
    if plan == nil then return fail(context, travel, "route_unavailable", "plan_missing") end
    local character = context.game.character
    local current = terrain.platform_at(graph, character.x, character.y, PLATFORM_TOLERANCE)
    if current == nil or current.index ~= plan.platform.index then
        -- 对齐途中离开门户平台：清执行器并回到 leg 相位重新规划。
        locomotion.clear(context)
        travel.plan, travel.phase, travel.settle_ticks = nil, "leg", 0
        context.game.log("travel_replan attempt=" .. tostring(travel.replans) .. " reason=left_portal_platform")
        return nil
    end
    local dx = plan.x - character.x
    if math.abs(dx) > ALIGN_TOLERANCE then
        travel.settle_ticks = 0
        locomotion.walk_to(context, plan.x, ALIGN_TOLERANCE)
        return nil
    end
    if character.on_ground ~= true or not still(character) then
        travel.settle_ticks = 0
        return nil
    end
    travel.settle_ticks = (travel.settle_ticks or 0) + 1
    if travel.settle_ticks < ARRIVE_TICKS then return nil end
    travel.phase = "portal_enter"
    return nil
end

local function handle_portal_enter(context, travel)
    local plan = travel.plan
    if plan == nil then return fail(context, travel, "route_unavailable", "plan_missing") end
    local leg = travel.legs[travel.leg_index]
    locomotion.enter_portal(context, plan.x, PORTAL_TOLERANCE)
    travel.portal = {
        from_map = context.scene.map_id,
        from_generation = context.scene.scene_generation,
        started = context.tick.time,
        retries = 0,
    }
    context.game.log(
        string.format(
            "travel_portal_enter name=%s x=%s y=%s",
            tostring(leg and leg.portal),
            number_text(plan.x),
            number_text(plan.y)
        )
    )
    travel.phase = "portal_wait"
    return nil
end

-- TODO(M3)：门户按上后的触发条件需真实客户端验证（站姿、y 对齐、是否需要短按而非
-- 持续 up）；同图位置大幅移动（图内传送门）尚未区分，当前只按地图/代次变化确认换图。
local function handle_portal_wait(context, travel)
    local portal = travel.portal
    if portal == nil then return fail(context, travel, "route_unavailable", "portal_missing") end
    local scene = context.scene
    if scene.map_id ~= portal.from_map or scene.scene_generation ~= portal.from_generation then
        travel.phase = "map_confirm"
        return nil
    end
    if context.tick.time - portal.started > PORTAL_WAIT_SECONDS then
        portal.retries = (portal.retries or 0) + 1
        if portal.retries > PORTAL_RETRY_LIMIT then return fail(context, travel, "portal_unconfirmed", "timeout") end
        local plan = travel.plan
        if plan == nil then return fail(context, travel, "route_unavailable", "plan_missing") end
        locomotion.enter_portal(context, plan.x, PORTAL_TOLERANCE)
        portal.started = context.tick.time
        context.game.log(string.format("travel_portal_retry retries=%d", portal.retries))
    end
    return nil
end

-- TODO(M3)：换图确认后的身份核对（instance/character）由 Runtime 保证；地图不符时当前
-- 只做「剩余腿前向对齐」或明确 map_mismatch，Lua 侧没有跨图门户图，无法运行时改道。
local function handle_map_confirm(context, travel)
    local scene = context.scene
    local map_id = scene.map_id
    if not finite(map_id) then return nil end
    local leg = travel.legs[travel.leg_index]
    if type(leg) ~= "table" then return fail(context, travel, "route_unavailable", "leg_malformed") end
    local portal = travel.portal or {}
    locomotion.clear(context)
    travel.plan = nil
    if map_id == leg.to then
        travel.map_id = map_id
        travel.leg_index = travel.leg_index + 1
        travel.portal = nil
        context.game.log(
            string.format(
                "travel_transition from=%s to=%s expected=%s",
                tostring(portal.from_map),
                tostring(map_id),
                tostring(leg.to)
            )
        )
        if travel.leg_index > #travel.legs then
            if map_id == travel.goal.map_id then
                travel.phase = "final"
            else
                return fail(context, travel, "map_mismatch", "route_ended_at_" .. tostring(map_id))
            end
        else
            travel.phase = "leg"
        end
        return nil
    end
    if map_id == portal.from_map then
        portal.retries = (portal.retries or 0) + 1
        if portal.retries > PORTAL_RETRY_LIMIT then
            return fail(context, travel, "portal_unconfirmed", "still_in_source_map")
        end
        travel.portal = portal
        travel.phase = "leg"
        context.game.log(string.format("travel_portal_retry retries=%d reason=map_unchanged", portal.retries))
        return nil
    end
    if align_leg(context, travel, map_id) then
        travel.portal = nil
        context.game.log(
            string.format(
                "travel_transition from=%s to=%s expected=%s aligned=%d",
                tostring(portal.from_map),
                tostring(map_id),
                tostring(leg.to),
                travel.leg_index
            )
        )
        return nil
    end
    return fail(context, travel, "map_mismatch", "actual_" .. tostring(map_id))
end

local function handle_final(context, travel)
    local terminal = recover(context, travel)
    if terminal ~= nil then return terminal end
    local graph, failed = terrain_or_fail(context, travel)
    if failed ~= nil then return failed end
    if graph == nil then return nil end
    local character = context.game.character
    local goal = travel.goal
    if goal == nil then return fail(context, travel, "route_unavailable", "goal_missing") end
    local goal_platform = travel.goal_platform
    if goal_platform == nil or travel.goal_platform_generation ~= graph.generation then
        goal_platform = locate(graph, goal.x, goal.y)
        if goal_platform == nil then
            travel.platform_unknown_ticks = (travel.platform_unknown_ticks or 0) + 1
            if travel.platform_unknown_ticks > NO_PLATFORM_TICK_LIMIT then
                return fail(context, travel, "platform_unknown", "goal_platform")
            end
            return nil
        end
        travel.goal_platform, travel.goal_platform_generation = goal_platform, graph.generation
        travel.platform_unknown_ticks = 0
    end
    local current = terrain.platform_at(graph, character.x, character.y, PLATFORM_TOLERANCE)
    if current == nil then
        travel.platform_unknown_ticks = (travel.platform_unknown_ticks or 0) + 1
        if travel.platform_unknown_ticks > NO_PLATFORM_TICK_LIMIT then
            return fail(context, travel, "platform_unknown", "current_platform")
        end
        return nil
    end
    travel.platform_unknown_ticks = 0
    if current.index ~= goal_platform.index then
        travel.settle_ticks = 0
        local ok, reason = locomotion.plan(context, current.index, goal_platform.index)
        if not ok then return fail(context, travel, "no_viable_path", tostring(reason)) end
        return nil
    end
    -- 已在目标平台：水平对齐到目标点（目标落在平台外时先夹到可站立范围），
    -- 且 y 与平台高度差在 2 倍容差内、动作与速度稳定两 tick 才算到达。
    local target_x = terrain.platform_inside(goal_platform, goal.x)
    local walk_tolerance = math.max(1, math.min(ALIGN_TOLERANCE, context.options.arrive_tolerance))
    local dx = target_x - character.x
    if math.abs(dx) > context.options.arrive_tolerance then
        travel.settle_ticks = 0
        locomotion.walk_to(context, target_x, walk_tolerance)
        return nil
    end
    if character.on_ground ~= true or not still(character) then
        travel.settle_ticks = 0
        locomotion.walk_to(context, target_x, walk_tolerance)
        return nil
    end
    travel.settle_ticks = (travel.settle_ticks or 0) + 1
    if travel.settle_ticks < ARRIVE_TICKS then return nil end
    local height = terrain.platform_height(goal_platform, target_x)
    if
        finite(height)
        and finite(character.y)
        and math.abs(character.y - height) > context.options.arrive_tolerance * 2
    then
        travel.settle_ticks = 0
        return nil
    end
    travel.phase = "arrived"
    local safety = context.state.safety or {}
    context.game.log(
        string.format(
            "travel_arrived map=%s x=%s y=%s heals=%d elapsed=%.2f",
            tostring(context.scene.map_id),
            number_text(character.x),
            number_text(character.y),
            safety.heals or 0,
            context.tick.time - (travel.started or context.tick.time)
        )
    )
    return "done"
end

local HANDLERS = {
    leg = handle_leg,
    portal_align = handle_portal_align,
    portal_enter = handle_portal_enter,
    portal_wait = handle_portal_wait,
    map_confirm = handle_map_confirm,
    final = handle_final,
}

-- 计划都依赖当前图坐标：执行相位期间若地图意外变化，清执行器并前向对齐或失败。
-- portal_wait/map_confirm 本来就在等换图，由各自相位处理。
local function sync_map(context, travel)
    local map_id = context.scene.map_id
    if travel.map_id == nil then
        travel.map_id = map_id
        return nil
    end
    if travel.map_id == map_id then return nil end
    local phase = travel.phase
    if phase ~= "leg" and phase ~= "portal_align" and phase ~= "final" then return nil end
    local previous = travel.map_id
    travel.map_id = map_id
    locomotion.clear(context)
    travel.plan, travel.settle_ticks = nil, 0
    if map_id == travel.goal.map_id then
        travel.phase = "final"
        context.game.log(
            string.format("travel_transition from=%s to=%s expected=goal", tostring(previous), tostring(map_id))
        )
        return nil
    end
    if align_leg(context, travel, map_id) then
        context.game.log(
            string.format("travel_transition from=%s to=%s expected=leg", tostring(previous), tostring(map_id))
        )
        return nil
    end
    return fail(context, travel, "map_mismatch", "unexpected_map_" .. tostring(map_id))
end

function travel_core.step(context)
    local travel = travel_core.state(context)
    if travel.phase == "arrived" then return "done" end
    if travel.phase == "failed" then return "failed" end
    local world = context.game.world
    local character = context.game.character
    if type(character) ~= "table" or not finite(character.x) or not finite(character.y) then return nil end
    if type(world) ~= "table" or world.ready ~= true then return nil end
    local scene = context.scene
    if type(scene) ~= "table" or not finite(scene.map_id) then return nil end
    if travel.phase == nil then
        local result = boot(context, travel)
        if result ~= nil then return result end
    end
    local elapsed = context.tick.time - travel.started
    if elapsed > context.options.budget_seconds then
        return fail(context, travel, "budget_exhausted", string.format("elapsed=%.1f", elapsed))
    end
    local synced = sync_map(context, travel)
    if synced ~= nil then return synced end
    local handler = HANDLERS[travel.phase]
    if handler == nil then return fail(context, travel, "route_unavailable", "phase_" .. tostring(travel.phase)) end
    return handler(context, travel)
end

return travel_core
