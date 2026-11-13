-- @mode tick
-- @option[type=string,default=right,choices=left|right] direction 移动方向

-- 连续移动跳砍：先助跑，再保持方向跳起，空中攻击一次，落地后停止。
-- 请从有足够空间的同高平地起步，装备可普攻的武器，且没有其他脚本控制角色。
-- 本例不寻路、不选怪、不保证命中，也不处理斜坡、台阶、绳梯或落层。
local function main(context)
    local state = context.state -- 本次会话跨调用保留；不是每次进入 main 都重新初始化。
    local character = context.game.character -- 每次调用重新读取角色自己的只读事实。
    local player = context.game.player -- 控制器；不是另一个可观测角色。
    local velocity = character.velocity
    local movement = character.movement -- 能力参考模型，与当前运动向量分开。

    if state.phase == nil then
        assert(velocity and movement, "motion_reference_required")
        assert(character.x ~= nil and character.y ~= nil, "position_unavailable")
        assert(character.on_ground == true, "start_on_ground_required")
        state.ground_y = character.y
        state.phase = "run_up"
        -- 先设置持续方向并返回，让原生物理建立水平速度，不与 jump 同帧提交。
        assert(player.move(context.options.direction))
    elseif state.phase == "run_up" then
        local sign = context.options.direction == "right" and 1 or -1
        -- 速度为地图像素/秒；参考上限来自当前有效属性和本端物理模型。
        -- 以达到99%作为满速，不按固定时长、距离或低速平台起跳。
        -- 运动事实暂不可用时只等待，不撤销已有方向，也不猜测速度。
        if velocity and movement and velocity.x * sign >= movement.max_speed * 0.99 and character.on_ground == true then
            assert(player.jump())
            state.phase = "air"
        end
    elseif
        state.phase == "air"
        and character.on_ground == false
        and character.y ~= nil
        and character.y < state.ground_y
        and not player.status().busy
    then
        -- Y向下增大；已离开原平地且起跳输入已释放，才接空中普攻。
        -- 此阶段不依赖速度/能力参考，缺失它们不应阻断这次攻击。
        assert(player.attack())
        state.phase = "landing" -- 只提交一次。
    elseif state.phase == "landing" and character.on_ground == true then
        player.move(nil) -- 全程只在这里清方向，不用 stop 打断跳跃腾空动作槽。
        state.phase = "stopping"
    elseif state.phase == "stopping" and velocity and movement and math.abs(velocity.x) < movement.max_speed * 0.01 then
        context.game.log("tick_jump_attack: landing observed; movement stopped")
        -- done后运行时继续收尾已提交动作，确认所属输入释放后发布完成。
        return "done"
    end

    -- 返回nil，下一次调度再观察；不要使用while/sleep阻塞主循环。
    -- 动作返回受理不等于命中，真实空中出手仍需原生事实/画面确认。
end
