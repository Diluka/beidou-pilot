-- 按次数或目标恢复，并逐次确认库存变化。
-- @option[type=int,min=1] item_id 要使用的物品 ID
-- @option[type=int,opt,default=1,min=1,max=100] count 最多尝试使用次数
-- @option[type=number,min=0] budget_seconds 策略运行预算，单位秒；允许零预算的无动作返回
-- @option[type=int,opt,min=1] target_hp 目标 HP；省略时不按 HP 目标停止
-- @option[type=int,opt,min=1] target_mp 目标 MP；省略时不按 MP 目标停止
-- @option[type=boolean,opt,default=false] heals_hp 调用方已知该物品恢复 HP
-- @option[type=boolean,opt,default=false] heals_mp 调用方已知该物品恢复 MP
-- @option[type=boolean,opt,default=false] healing_known 调用方已知物品恢复类型
-- @option[type=boolean,opt,default=false] consume_only 仅核对单次库存消费，不将其称为恢复
local function main(context)
    local options = context.options
    -- Repeated recovery is driven in the client; this script never controls GUI slots.
    local initial = game.state()
    assert(initial.ready and initial.character and initial.position, "use_context_unavailable")
    local deadline = game.time() + options.budget_seconds
    local used = 0

    local function observe()
        local s = game.state()
        assert(s.ready and s.character and s.position, "use_context_unavailable")
        -- 用药期间换图或角色变化时，库存和血量读数不再描述同一场景。
        assert(
            s.instance_id == initial.instance_id
                and s.character.id == initial.character.id
                and s.map_id == initial.map_id
                and s.scene_generation == initial.scene_generation,
            "use_context_changed"
        )
        assert(s.character.hp > 0, "dead")
        assert(s.inventory, "inventory_unavailable")
        local quantity = 0
        for _, item in ipairs(s.inventory) do
            if item.item_id == options.item_id then quantity = quantity + (item.quantity or 0) end
        end
        return s, quantity
    end

    while used < options.count do
        local s, quantity = observe()
        local c = s.character
        if
            (options.target_hp or options.target_mp)
            and (not options.target_hp or c.hp >= options.target_hp)
            and (not options.target_mp or c.mp >= options.target_mp)
        then
            return
        end
        local hp_needed = (options.heals_hp or not options.healing_known)
            and c.hp < c.max_hp
            and (not options.target_hp or c.hp < options.target_hp)
        local mp_needed = (options.heals_mp or not options.healing_known)
            and c.mp < c.max_mp
            and (not options.target_mp or c.mp < options.target_mp)
        if not hp_needed and not mp_needed and not options.consume_only then return end
        if game.time() >= deadline then return end
        if quantity == 0 then
            assert(used > 0, "item_missing")
            return
        end

        local result = game.use_item(options.item_id)
        assert(result.dispatched, "item_use_not_dispatched")
        local confirm_until = game.time() + 1.2
        local after, after_quantity
        while true do
            after, after_quantity = observe()
            local hp_confirmed = not hp_needed or after.character.hp > c.hp
            local mp_confirmed = not mp_needed or after.character.mp > c.mp
            local recovered = options.healing_known and hp_confirmed and mp_confirmed
                or not options.healing_known
                    and ((hp_needed and after.character.hp > c.hp) or (mp_needed and after.character.mp > c.mp))
            if after_quantity == quantity - 1 and (options.consume_only or recovered) then break end
            assert(
                game.time() < confirm_until,
                after_quantity == quantity - 1 and "healing_not_confirmed" or "use_not_confirmed"
            )
            game.sleep(0.05)
        end
        used = used + 1
        if used < options.count then game.sleep(0.7) end
    end
end
