-- @mode tick
-- @option[type=int,min=1] skill_id 本角色已学会且本端支持的普通技能
-- @option[type=number,default=1,min=0.1,max=5] hold_seconds 保持输入的演示时长（不是动画时长）

-- 只设置一次技能意图；后续回调不重放技能，由原生消费者处理保持。
-- 会实际消耗MP；无动作锁技能每次保持只派发一次，GUI蓄力技能不支持。
local function main(context)
    local state = context.state
    local player = context.game.player
    if state.started == nil then
        local ok, reason = player.skill(context.options.skill_id)
        assert(ok, reason)
        state.started = context.tick.time
        return
    end
    if state.released then
        if player.status().input_settled then
            context.game.log("held_skill: input released; native animation may still be running")
            return "done"
        end
    elseif context.tick.time - state.started >= context.options.hold_seconds then
        -- 明确结束输入保持，不用这个时长推算技能动画何时完成。
        assert(player.clear_action())
        state.released = true
        return -- 下一次观察确认本次清空已被原生消费。
    end
end
