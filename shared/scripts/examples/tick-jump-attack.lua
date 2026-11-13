-- @mode tick
-- @option[type=string,default=right,choices=left|right] direction 移动方向

-- 连续移动跳砍：先助跑，再保持方向跳起，空中攻击一次，落地后停止。
-- 请从有足够空间的同高平地起步，装备可普攻的武器，且没有其他脚本控制角色。
-- 本例不寻路、不选怪、不保证命中，也不处理斜坡、台阶、绳梯或落层。
local function main(context)
    local state = context.state -- 本次会话跨调用保留；不是每次进入 main 都重新初始化。
    local world = context.game.world -- 每次调用重新读取当时的只读事实，不缓存领域表。
    local player = context.game.player
    local velocity = assert(world.velocity, "velocity_unavailable")
    local movement = assert(context.game.character.movement, "movement_reference_unavailable")
    assert(world.x ~= nil and world.y ~= nil, "position_unavailable")

    if state.phase == nil then
        assert(world.on_ground == true, "start_on_ground_required")
        state.ground_y = world.y
        state.phase = "run_up"

        -- 先设置持续方向并返回，让原生物理真正建立水平速度，不与 jump 同帧提交。
        assert(player.move(context.options.direction))
    elseif state.phase == "run_up" then
        local sign = context.options.direction == "right" and 1 or -1
        -- 速度为地图像素/秒；参考上限由当前有效属性和本端物理模型提供，不是固定常数。
        -- 摩擦使速度渐近稳态，以达到99%作为满速；不按固定时长、距离或低速平台起跳。
        if velocity.x * sign >= movement.max_speed * 0.99 and world.on_ground == true then
            assert(player.jump())
            state.phase = "air"
        end
    elseif
        state.phase == "air"
        and world.on_ground == false
        and world.y < state.ground_y
        and not player.status().busy
    then
        -- 屏幕 Y 向下增大，Y 变小表示已跳离原平地。
        -- jump 槽空闲只表示起跳输入已释放，不表示落地；现在可以接空中普攻。
        assert(player.attack())
        state.phase = "landing" -- 只提交一次，后续调用不再重复 attack。
    elseif state.phase == "landing" and world.on_ground == true then
        player.move(nil) -- 全程只在这里清除方向；不用 stop 打断跳跃来腾空动作槽。
        state.phase = "stopping"
    elseif state.phase == "stopping" and math.abs(velocity.x) < movement.max_speed * 0.01 then
        context.game.log("tick_jump_attack: landing observed; movement stopped")
        -- done 不再调用 main；运行时继续收尾已提交动作，确认所属输入释放后发布完成。
        return "done"
    end

    -- 返回 nil，下一次调度再观察和判断；不要使用 while/sleep 阻塞主循环。
    -- move/jump/attack 返回受理，不等于命中。真实空中出手仍应由原生事实/画面确认。
end
