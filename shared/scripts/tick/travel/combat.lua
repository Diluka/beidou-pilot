-- tick 旅行脚本包：战斗层骨架（#176 M1/M2 不启用）。
--
-- M1/M2 只交付最小骨架：状态表、未启用时每 tick 返回 nil，不产生任何攻击/技能/
-- 靠近输入，也不声称能清怪。真实挡路怪处理属于 M4：由 travel_core 在边反复被
-- 阻挡且近身存在威胁时按 block_policy 请求，同平台目标选择、接近、普攻/技能保持、
-- 命中核对、清怪上限与子预算都在那时接入。
--
-- TODO(M4)：
-- - 同平台目标选择与接近（复用 terrain 平台定位，不跨平台追击）；
-- - player.attack/skill 保持与撤下，命中/死亡核对（目标消失/失活/经验变化）；
-- - 清怪上限 clear_limit、子预算与完成交还；
-- - 与 locomotion 的动作槽顺序：请求前由 travel_core 先 clear 执行器方向。
local combat = {}

function combat.state(context)
    local state = context.state.combat
    if state == nil then
        state = { enabled = false, requested = false, target = nil, clears = 0, failure = nil }
        context.state.combat = state
    end
    return state
end

-- 任务层请求解围；返回 false 表示本阶段不接管。M1/M2 只记录请求并写一次日志，
-- 不产生战斗输入，也不把请求当成已清怪。
function combat.request(context, reason)
    local state = combat.state(context)
    if state.requested then return false end
    state.requested = true
    state.request_reason = reason
    local policy = state.mode or context.options.block_policy or "auto"
    context.game.log("travel_combat requested=1 policy=" .. tostring(policy) .. " reason=" .. tostring(reason))
    return false
end

function combat.clear(context)
    local state = combat.state(context)
    state.requested = false
    state.target = nil
    state.request_reason = nil
end

function combat.step(context)
    local state = combat.state(context)
    if not state.enabled then return nil end
    -- TODO(M4)：只有在任务层请求清怪且目标仍有效时接管动作槽；完成或失败后通过
    -- state.combat.failure 上报，由 travel_core 决定继续移动还是终止。
    return nil
end

return combat
