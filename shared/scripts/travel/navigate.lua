-- 跨场景导航策略：按调用方给出的静态路线逐段走到门户、按上换图并核对落点。
-- 路线与每张地图地形由 CLI 从本地只读资料打包；本策略不计算跨图路线。
-- @option[type=number,opt,default=90,min=1,max=580] budget_seconds 整体导航预算
-- @option[type=number,opt,default=0.25,min=0,max=1] min_hp_ratio 生命值安全比例
-- @option[type=int,opt] goal_x 目的地图内目标水平坐标；与goal_y同时给出时继续走到该坐标
-- @option[type=int,opt] goal_y 目的地图内目标世界高度
-- @option[type=int,opt,default=12,min=1,max=40] tolerance 到达水平容差
-- @option[type=int,opt,min=1] hp_item_id 移动中低生命值时使用的明确药品 ID；省略时按库存挑恢复量最大的普通药
-- @option[type=number,opt,default=0.7,min=0,max=1] heal_hp_ratio 移动中开始用药的生命值比例
-- @option[type=string,opt,default="auto",choices=auto|ignore|clear] mob_strategy 被近身怪物挡住时：auto 按血线决定、ignore 只喝药硬冲、clear 先清怪
-- @option[type=int,opt,min=1] skill_id 清怪时使用的已学技能 ID；省略时使用普攻
-- @option[type=int,opt,default=90,min=20,max=300] attack_range 近身清怪距离
-- @option[type=int,opt,default=8,min=1,max=60] clear_limit 单次移动最多清怪攻击次数
local function main(context)
    local options = context.options
    local route = context.route
    if type(route) ~= "table" or type(route.legs) ~= "table" then error("navigate_route_missing") end
    local deadline = game.time() + options.budget_seconds
    local dialog = game.observe("dialog")
    if dialog.status == "ok" and dialog.data and dialog.data.dialog_open == true then error("navigate_dialog_open") end
    local initial = travel_initial(context, options.min_hp_ratio, error)
    local last = initial
    local combat = {
        hp_item_id = options.hp_item_id,
        heal_hp_ratio = options.heal_hp_ratio,
        min_hp_ratio = options.min_hp_ratio,
        mob_strategy = options.mob_strategy,
        skill_id = options.skill_id,
        attack_range = options.attack_range,
        clear_limit = options.clear_limit,
    }
    -- 路线地形按数组打包以控制脚本体积；这里转回平台图需要的字段。
    local function expand(raw)
        local footholds, ropes = {}, {}
        for index, row in ipairs(raw.footholds or {}) do
            footholds[index] = {
                id = row[1],
                x1 = row[2],
                x2 = row[3],
                y1 = row[4],
                y2 = row[5],
                prev = row[6],
                next = row[7],
            }
        end
        for index, row in ipairs(raw.ropes or {}) do
            ropes[index] = { index = row[1], x = row[2], y1 = row[3], y2 = row[4] }
        end
        return { footholds = footholds, ropes = ropes }
    end
    -- 身份与存活跨段保持；当前地图由每段单独核对。
    -- HP 下限由执行器在每段移动中判断；这里只核对身份与存活。
    local function check_state()
        last = travel_state(initial, 0, deadline, true, error)
        return last
    end
    local function segment_state(expected_map, leg_index)
        local s = check_state()
        if s.map_id ~= expected_map then
            error(
                string.format(
                    "navigate_failed leg=%d expected_map=%d actual_map=%s reason=navigate_map_mismatch x=%.1f y=%.1f",
                    leg_index,
                    expected_map,
                    tostring(s.map_id),
                    s.position.x,
                    s.position.y
                )
            )
        end
        return s
    end
    for index, leg in ipairs(route.legs) do
        local graph = terrain_build(expand(leg.terrain), {})
        local portal_platform = terrain_platform_at(graph, leg.portal_x, leg.portal_y, 55)
        if not portal_platform then
            error(
                string.format(
                    "navigate_failed leg=%d map=%d portal=%s reason=portal_not_on_foothold",
                    index,
                    leg.map_id,
                    tostring(leg.portal)
                )
            )
        end
        local function fail(reason, stage)
            error(
                string.format(
                    "navigate_failed leg=%d map=%d portal=%s stage=%s reason=%s x=%.1f y=%.1f",
                    index,
                    leg.map_id,
                    tostring(leg.portal),
                    stage or "state",
                    reason,
                    last.position.x,
                    last.position.y
                )
            )
        end
        segment_state(leg.map_id, index)
        game.log(
            string.format(
                "navigate_leg index=%d map=%d portal=%s target=%d",
                index,
                leg.map_id,
                tostring(leg.portal),
                leg.target_map
            )
        )
        local leg_deadline = math.min(deadline, game.time() + 90)
        move_to(
            graph,
            { x = leg.portal_x, y = leg.portal_y, tolerance = options.tolerance, platform = portal_platform },
            { state = check_state, fail = fail, deadline = leg_deadline, log = "navigate", combat = combat }
        )
        -- 到达平台后精确对齐门户坐标，确认在触发范围内才按上。
        local align_until = math.min(deadline, game.time() + 5)
        local aligned = false
        while game.time() < align_until do
            local s = check_state()
            local dx = leg.portal_x - s.position.x
            if math.abs(dx) <= 8 and math.abs(s.position.y - leg.portal_y) <= 40 then
                aligned = true
                break
            end
            travel_action(
                game.move(dx > 0 and "right" or "left", math.min(0.15, math.max(0.03, math.abs(dx) / 150))),
                fail
            )
            game.sleep(0.12)
        end
        if not aligned then fail("portal_align_stalled", "align") end
        -- 对齐后只按一次上；转场期间只等待原生状态，不重发。
        travel_action(game.stop(), fail)
        game.sleep(0.2)
        travel_action(game.move("up", 0.18), fail)
        local until_at = math.min(deadline, game.time() + 4)
        local transitioned = false
        while game.time() < until_at do
            local s = check_state()
            if s.map_id == leg.target_map then
                transitioned = true
                last = s
                break
            end
            -- 换到了非预期地图时立即报告，不把它当成门户未触发。
            if s.map_id ~= leg.map_id then fail("navigate_map_mismatch", "portal") end
            game.sleep(0.05)
        end
        if not transitioned then fail("portal_unconfirmed", "portal") end
        game.log(string.format("navigate_transition leg=%d map=%d", index, leg.target_map))
        game.sleep(0.3)
    end
    -- 目的地图内继续走到目标坐标（调用方给出时）。
    local final = route.final
    if options.goal_x and options.goal_y and type(final) == "table" then
        local graph = terrain_build(expand(final.terrain), {})
        local platform = terrain_platform_at(graph, options.goal_x, options.goal_y, 25)
        if not platform then
            error(string.format("navigate_failed map=%d reason=target_not_on_foothold", final.map_id))
        end
        local function fail(reason, stage)
            error(
                string.format(
                    "navigate_failed map=%d stage=%s reason=%s x=%.1f y=%.1f",
                    final.map_id,
                    stage or "state",
                    reason,
                    last.position.x,
                    last.position.y
                )
            )
        end
        segment_state(final.map_id, #route.legs + 1)
        move_to(
            graph,
            { x = options.goal_x, y = options.goal_y, tolerance = options.tolerance, platform = platform },
            { state = check_state, fail = fail, deadline = deadline, log = "navigate", combat = combat }
        )
    end
    local settled = check_state()
    game.log(
        string.format(
            "navigate_arrived map=%s expected=%s x=%.1f y=%.1f",
            tostring(settled.map_id),
            tostring(route.goal),
            settled.position.x,
            settled.position.y
        )
    )
end
