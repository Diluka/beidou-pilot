-- 单根绳梯攀爬策略。
-- @option[type=int] x 绳梯水平坐标
-- @option[type=int] y 目标世界高度
-- @option[type=number,opt,default=20,min=1,max=60] budget_seconds 策略运行预算，单位秒
-- @option[type=int,opt,default=10,min=1,max=40] tolerance 目标位置容差
-- @option[type=number,opt,default=0.25,min=0,max=1] min_hp_ratio 生命值安全比例
-- @option[type=string,opt,choices=up|down] direction 绳梯攀爬方向；省略时按目标高度推断
-- @option[type=number,opt] rope_top 已知绳梯顶部坐标；未知时省略
local function main(context)
    local options = context.options
    local initial = travel_initial(context, options.min_hp_ratio)
    local deadline = game.time() + options.budget_seconds
    local direction = options.direction or (options.y < initial.position.y and "up" or "down")
    local state = align_to_x(initial, options.x, 5, 45, deadline, options.min_hp_ratio)
    if math.abs(state.position.y - options.y) <= options.tolerance then return end
    local stop_y = options.y
    if direction == "up" and options.rope_top then stop_y = math.min(stop_y, options.rope_top - 2) end
    for attempt = 1, 2 do
        if deadline - game.time() < 1 then break end
        local hold =
            math.max(0.05, math.min(9, deadline - game.time() - 0.7, math.abs(stop_y - state.position.y) / 90 + 1.5))
        if direction == "up" then game.jump() end
        local hold_deadline = math.min(deadline, game.time() + hold)
        while game.time() < hold_deadline do
            state = travel_state(initial, options.min_hp_ratio, deadline, false)
            assert(math.abs(state.position.x - options.x) <= 18, "outside_safe_x")
            if
                (direction == "up" and state.position.y <= stop_y)
                or (direction == "down" and state.position.y >= stop_y)
            then
                break
            end
            game.move(direction, math.max(0.05, math.min(0.15, hold_deadline - game.time())))
        end
        game.stop()
        game.sleep(0.3)
        state = travel_state(initial, options.min_hp_ratio, deadline, false)
        if
            math.abs(state.position.y - options.y) <= options.tolerance
            and math.abs(state.position.x - options.x) <= 18
        then
            return
        end
        if attempt == 1 and math.abs(state.position.y - initial.position.y) <= 35 then
            state = align_to_x(initial, options.x, 5, 45, deadline, options.min_hp_ratio)
        else
            break
        end
    end
    error("climb_not_confirmed")
end
