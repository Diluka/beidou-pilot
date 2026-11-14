-- @mode tick
-- @option[type=string,default=right,choices=left|right] direction 移动方向

-- 连续移动跳砍：先助跑，再保持方向跳起，空中普攻并撤下保持，落地后停止。
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
        and character.action_idle == true
    then
        -- Y向下增大；原生动作已知空闲且已离开原平地，才接空中普攻。
        -- 此阶段不依赖速度/能力参考，缺失它们不应阻断这次攻击。
        assert(player.attack())
        state.phase = "attack_input" -- 只设置一次，保持由原生消费者处理。
    elseif state.phase == "attack_input" then
        local input = player.status()
        if input.action == "attack" and input.dispatched then
            -- 当前原生动作确为普攻且已派发才撤下，不把上次跳跃反馈当成普攻。
            -- 撤下槽不表示已放键，已经发生的攻击动画仍自然播放。
            -- 低频观察可能错过原生重复边界，本例不承诺精确出手次数。
            assert(player.skill(nil))
            state.phase = "landing"
        end
    elseif state.phase == "landing" and character.on_ground == true then
        player.move(nil) -- 只在落地后清方向，不用物理静止替代落地。
        state.phase = "stopping"
    elseif state.phase == "stopping" and velocity and movement and math.abs(velocity.x) < movement.max_speed * 0.01 then
        context.game.log("tick_jump_attack: landing observed; movement stopped")
        -- 会话结束会清除所属输入；此时动作意图已显式撤下。
        return "done"
    end

    -- 返回nil，下一次调度再观察；不要使用while/sleep阻塞主循环。
    -- 动作返回受理不等于命中，真实空中出手仍需原生事实/画面确认。
end
