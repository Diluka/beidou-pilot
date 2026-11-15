-- tick 旅行脚本包：自保层。
--
-- 每 tick 最先执行：HP 事实可用时按 heal_hp_ratio 尝试用普通恢复品；用药后短路
-- 后续层，避免同 tick 的移动/跳跃意图覆盖动作槽里的用药意图。达到目标比例后
-- 撤下用药意图。死亡、HP 低于下限或确认无药可救时上报失败，由入口终止会话。
--
-- 只读 context.game.character / context.game.inventory，只写 player 用药与方向清理。
-- 字段说明：docs/LUA_TICK_API.md 只声明 game.character 的 hp/max_hp 与 game.inventory
-- 领域本身，不枚举背包行字段；两端适配器当前都投影 items[] 的 inventory_type/
-- item_id/quantity，这里按「可读则读、不可读保持未知」处理，未知时不据此判定药尽，
-- 只用原生拒绝原因（player.status().reason）确认 item_not_in_inventory。
local safety = {}

local REHEAL_SECONDS = 1.0
local UNSUPPORTED_RETRY_SECONDS = 5.0
local REJECTED_RETRY_SECONDS = 0.5
-- 低于 HP 下限时，给已经在生效途中的用药一个短宽限，避免把「正在恢复」误判为无药。
local POTION_GRACE_SECONDS = 2.0

local function finite(value)
    return type(value) == "number" and value == value and value ~= math.huge and value ~= -math.huge
end

function safety.state(context)
    local state = context.state.safety
    if state == nil then
        state = { heals = 0 }
        context.state.safety = state
    end
    return state
end

local function fail(context, state, reason, detail)
    state.failure = reason
    state.failure_detail = detail
    context.game.player.stop()
    return "failed"
end

-- 背包里目标恢复品的可读数量；返回 nil 表示库存事实未知（不伪造为空）。
local function potion_stock(context, item_id)
    local inventory = context.game.inventory
    if type(inventory) ~= "table" or type(inventory.items) ~= "table" then return nil end
    local quantity, unknown = 0, false
    for _, item in ipairs(inventory.items) do
        if type(item) == "table" and item.item_id == item_id then
            if item.inventory_type == nil or item.inventory_type == 2 then
                if finite(item.quantity) then
                    quantity = quantity + item.quantity
                else
                    unknown = true
                end
            end
        end
    end
    if quantity > 0 then return quantity end
    if unknown then return nil end
    return 0
end

local function hp_ratio(character)
    local hp, max_hp = character.hp, character.max_hp
    if finite(hp) and finite(max_hp) and max_hp > 0 then return hp / max_hp end
    return nil
end

local function death_reason(character, world)
    if world ~= nil and world.dead == true then return "world_dead" end
    if finite(character.hp) and character.hp <= 0 then return "hp_zero" end
    return nil
end

-- 达到用药目标后必须撤下持续用药意图，否则原生会继续尝试消耗。
-- 只撤下本层确实请求过的用药意图，避免清掉其他会话/其他动作槽的输入。
local function withdraw_potion(context, state, item_id, ratio)
    if not state.potion_requested then return end
    local option = context.options
    if ratio ~= nil and ratio < option.heal_hp_ratio then return end
    local player = context.game.player
    local status = player.status()
    if status.input_action == "use_item" and status.input_item_id == item_id then player.skill(nil) end
    state.potion_requested = false
    state.heal_at = nil
    state.withdrawals = (state.withdrawals or 0) + 1
    context.game.log("travel_safety potion_withdrawn")
end

function safety.step(context)
    local state = safety.state(context)
    local character = context.game.character
    local world = context.game.world
    if type(character) ~= "table" then return nil end

    local death = death_reason(character, world)
    if death ~= nil then return fail(context, state, "death", death) end

    local options = context.options
    local ratio = hp_ratio(character)
    if ratio == nil then
        -- HP 事实未知：不据此用药，也不推断死亡；但已提交的用药意图不能无限保持。
        if state.potion_requested then
            context.game.player.skill(nil)
            state.potion_requested, state.heal_at = false, nil
            context.game.log("travel_safety potion_withdrawn reason=hp_unknown")
        end
        return nil
    end
    withdraw_potion(context, state, options.hp_item_id, ratio)
    if ratio >= options.heal_hp_ratio then return nil end

    -- 原生已经拒绝过本层请求的恢复品：不再重复派发，按药尽处理。
    local status = context.game.player.status()
    if state.potion_requested and status.reason == "item_not_in_inventory" then
        state.potion_requested = false
        state.stock_empty = true
    end
    if state.stock_empty then
        if ratio < options.min_hp_ratio then return fail(context, state, "potion_exhausted", "stock_empty") end
        return nil
    end

    local now = context.tick.time
    if state.heal_at ~= nil and now < state.heal_at then
        if ratio < options.min_hp_ratio then
            local grace = state.potion_requested
                and state.potion_requested_at ~= nil
                and now - state.potion_requested_at <= POTION_GRACE_SECONDS
            if not grace then return fail(context, state, "hp_limit", "heal_cooldown") end
        end
        return nil
    end

    local stock = potion_stock(context, options.hp_item_id)
    if stock == 0 then
        -- 库存可读且确认无药：低于下限时失败，否则记录后让移动继续。
        if ratio < options.min_hp_ratio then return fail(context, state, "potion_exhausted", "stock_empty") end
        if not state.no_potion_logged then
            state.no_potion_logged = true
            context.game.log("travel_safety no_potion item=" .. tostring(options.hp_item_id))
        end
        return nil
    end

    local ok, reason = context.game.player.use_item(options.hp_item_id)
    if ok then
        state.heal_at = now + REHEAL_SECONDS
        state.heals = (state.heals or 0) + 1
        state.potion_requested = true
        state.potion_requested_at = now
        -- 用药占用共享动作槽，本 tick 必须短路后续层，避免覆盖成移动/跳跃意图。
        return "halt"
    end
    if reason == "unsupported" then
        state.heal_at = now + UNSUPPORTED_RETRY_SECONDS
        state.use_item_unsupported = true
        if ratio < options.min_hp_ratio then return fail(context, state, "hp_limit", "use_item_unsupported") end
        return nil
    end
    state.heal_at = now + REJECTED_RETRY_SECONDS
    if ratio < options.min_hp_ratio then return fail(context, state, "hp_limit", tostring(reason)) end
    return nil
end

return safety
