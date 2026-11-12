-- 进入一个已解析的当前地图门户。
-- @option[type=number] x 门户水平坐标
-- @option[type=number] y 门户世界高度
-- @option[type=int,min=0] target_map 门户目的地图 ID；未知目的地使用约定哨兵值
-- @option[type=number,opt,min=0] destination_x 同图传送目的地水平坐标
-- @option[type=number,opt] destination_y 同图传送目的地世界高度
-- @option[type=number,opt,default=20,min=1,max=60] budget_seconds 策略运行预算，单位秒
-- @option[type=int,opt,default=10,min=1,max=50] tolerance 水平对齐容差
-- @option[type=int,opt,default=55,min=1,max=150] y_tolerance 平台高度容差
-- @option[type=number,opt,default=0.25,min=0,max=1] min_hp_ratio 生命值安全比例
local function main(context)
    local options = context.options
    local initial = travel_initial(context, options.min_hp_ratio)
    local deadline = game.time() + options.budget_seconds
    local function transitioned(s)
        if s.map_id ~= initial.map_id then
            assert(options.target_map == 999999999 or s.map_id == options.target_map, "portal_unexpected_map")
            return true
        end
        return options.destination_x
            and options.destination_y
            and math.abs(s.position.x - options.destination_x) <= 80
            and math.abs(s.position.y - options.destination_y) <= 80
            and math.abs(s.position.x - options.x) + math.abs(s.position.y - options.y) > 60
    end
    local state, _, arrived = align_to_x(
        initial,
        options.x,
        options.tolerance,
        options.y_tolerance,
        deadline,
        options.min_hp_ratio,
        transitioned
    )
    if arrived then
        game.stop()
        return
    end
    assert(math.abs(state.position.y - options.y) <= options.y_tolerance, "portal_other_layer")
    assert(deadline - game.time() >= 0.4, "travel_budget_exhausted")
    -- 只派发一次进入动作；转场期间只等待原生状态，不重发Up。
    game.move("up", 0.18)
    game.sleep(0.15)
    local confirmation_deadline = math.max(deadline, game.time() + 2.5)
    while game.time() < confirmation_deadline do
        state = travel_state(initial, options.min_hp_ratio, confirmation_deadline, true)
        if transitioned(state) then
            game.stop()
            return
        end
        game.sleep(0.05)
    end
    error("portal_transition_unconfirmed")
end
