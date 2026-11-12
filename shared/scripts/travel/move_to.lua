-- 同层移动策略。
-- @option[type=int] x 当前地图水平目标坐标
-- @option[type=number,opt,default=20,min=1,max=60] budget_seconds 策略运行预算，单位秒
-- @option[type=int,opt,default=8,min=1,max=50] tolerance 水平到达容差
-- @option[type=int,opt,default=45,min=1,max=150] y_tolerance 当前层高度容差
-- @option[type=number,opt,default=0,min=0,max=1] min_hp_ratio 生命值安全比例
local function main(context)
    local options = context.options
    local deadline = game.time() + options.budget_seconds
    local initial = travel_initial(context, options.min_hp_ratio)
    align_to_x(initial, options.x, options.tolerance, options.y_tolerance, deadline, options.min_hp_ratio)
    game.stop()
end
