-- @mode tick
-- @option[type=string,default=right,choices=left|right] direction 移动方向

-- 连续移动跳砍：保持方向并跳起，空中攻击一次，落地后停止。
-- 请从有足够空间的同高平地起步，装备可普攻的武器，且没有其他脚本控制角色。
-- 本例不寻路、不选怪、不保证命中，也不处理斜坡、台阶、绳梯或落层。
local function main(context)
    local state = context.state -- 本次会话跨调用保留；不是每次进入 main 都重新初始化。
    local world = context.game.world -- 每次调用重新读取当时的只读事实，不缓存领域表。
    local player = context.game.player
    assert(world.x ~= nil and world.y ~= nil, "position_unavailable")

    if state.phase == nil then
        assert(world.on_ground ~= false, "start_on_ground_required")
        state.ground_y = world.y
        state.phase = "air"

        -- 同一次调用设置方向和跳跃，返回后统一提交。方向会持续保持，不必逐帧重发。
        assert(player.move(context.options.direction))
        assert(player.jump())
    elseif state.phase == "air" and world.y < state.ground_y and not player.status().busy then
        -- 屏幕 Y 向下增大，Y 变小表示已跳离原平地。
        -- jump 槽空闲只表示起跳输入已释放，不表示落地；现在可以接空中普攻。
        assert(player.attack())
        state.phase = "landing" -- 只提交一次，后续调用不再重复 attack。
    elseif state.phase == "landing" then
        local landed = world.on_ground -- 无头端的真实物理事实；GUI 未知时为 nil。
        if landed == nil then
            -- GUI 示例限定同高平地：回到起点高度且连续两次高度不变，作为落地判断。
            -- 这是本例的场景约束，不应把它照搬成通用地形检测，也不能用 settled 判断。
            landed = world.y == state.ground_y and world.y == state.previous_y
        end
        if landed then
            player.move(nil) -- 全程只在这里清除方向；不用 stop 打断跳跃来腾空动作槽。
            context.game.log("tick_jump_attack: landed; movement cleared")
            -- done 不再调用 main；运行时继续收尾已提交动作，确认所属输入释放后发布完成。
            return "done"
        end
    end

    state.previous_y = world.y
    -- 返回 nil，下一次调度再观察和判断；不要使用 while/sleep 阻塞主循环。
    -- move/jump/attack 返回受理，不等于命中。真实空中出手仍应由原生事实/画面确认。
end
