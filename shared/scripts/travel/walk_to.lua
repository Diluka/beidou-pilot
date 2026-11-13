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
    local initial = travel_initial(context, options.min_hp_ratio, error)
    local last = initial
    local function fail(reason, stage)
        error(
            string.format(
                "walk_to_failed map=%d x=%.1f y=%.1f stage=%s reason=%s platforms=%d walls=%d",
                scene.map_id,
                last.position.x,
                last.position.y,
                stage or "state",
                reason,
                #graph.platforms,
                #graph.walls
            )
        )
    end
    local function check_state()
        last = travel_state(initial, options.min_hp_ratio, deadline, false, fail)
        return last
    end
    local target = {
        x = options.target_x,
        y = options.target_y,
        tolerance = options.tolerance,
        plan_only = options.plan_only,
        platform = terrain_platform_at(graph, options.target_x, options.target_y, 25),
    }
    return move_to(graph, target, { state = check_state, fail = fail, deadline = deadline, log = "walk_to" })
end
