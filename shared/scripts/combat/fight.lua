-- 同层有界战斗策略。
-- @option[type=int,min=1] mob_id 目标怪物模板 ID
-- @option[type=number,opt,default=60,min=5,max=300] budget_seconds 策略运行预算，单位秒
-- @option[type=int,min=1] stop_level 停止等级
-- @option[type=int] floor_y 当前战斗楼层高度
-- @option[type=int] min_x 安全范围最小水平坐标
-- @option[type=int] max_x 安全范围最大水平坐标
-- @option[type=int] retreat_x 结束时尝试返回的水平锚点
-- @option[type=int,opt,min=1] hp_item 低生命值时使用的明确物品 ID；省略时按库存选择回血量最大的普通药品
-- @option[type=boolean,opt,default=false] loot 默认关闭近距拾取；启用后才尝试拾取
local function main(context)
    local options = context.options
    local scene = context.scene
    -- 同层有界战斗，全部实时判断在客户端内部运行。
    local initial = game.state()
    assert(initial.ready and initial.character, "not_ready")
    assert(
        initial.instance_id == scene.instance_id
            and initial.character.id == scene.character_id
            and initial.map_id == scene.map_id
            and initial.scene_generation == scene.scene_generation,
        "strategy_scene_context_stale"
    )
    local deadline = game.time() + options.budget_seconds
    local combat_until = deadline - math.min(5, options.budget_seconds / 4)
    local attacks = 0
    local heal_at = 0
    while game.time() < combat_until do
        local s = game.state()
        assert(
            s.ready
                and s.instance_id == initial.instance_id
                and s.character.id == initial.character.id
                and s.map_id == initial.map_id
                and s.scene_generation == initial.scene_generation,
            "fight_context_changed"
        )
        assert(s.character.hp > 0, "dead")
        if s.character.level >= options.stop_level then break end
        assert(s.position.x >= options.min_x and s.position.x <= options.max_x, "outside_safe_x")
        assert(math.abs(s.position.y - options.floor_y) <= 45, "wrong_floor")
        if s.character.hp < s.character.max_hp * 0.6 then
            local potion = nil
            local function have(item_id)
                for _, item in ipairs(s.inventory or {}) do
                    if item.quantity and item.quantity > 0 and item.item_id == item_id then return true end
                end
                return false
            end
            if options.hp_item then
                assert(have(options.hp_item), "no_hp_potion")
                potion = options.hp_item
            else
                -- 未指定时按回血量从高到低挑库存里真实存在的普通 HP 药。
                for _, candidate in ipairs({ 2000002, 2000001, 2000000, 2000013 }) do
                    if have(candidate) then
                        potion = candidate
                        break
                    end
                end
            end
            assert(potion, "no_hp_potion")
            if game.time() >= heal_at then
                game.use_item(potion)
                heal_at = game.time() + 0.7
            end
            game.sleep(0.05)
        else
            local target = nil
            for _, mob in ipairs(s.monsters or {}) do
                if
                    mob.active
                    and mob.template_id == options.mob_id
                    and mob.x >= options.min_x
                    and mob.x <= options.max_x
                    and math.abs(mob.y - options.floor_y) <= 45
                then
                    if not target or math.abs(mob.x - s.position.x) < math.abs(target.x - s.position.x) then
                        target = mob
                    end
                end
            end
            if target then
                local distance = target.x - s.position.x
                if math.abs(distance) > 85 then
                    game.move(distance > 0 and "right" or "left", math.min(0.2, math.abs(distance) / 180))
                else
                    game.face(distance >= 0 and "right" or "left")
                    local attack = game.attack()
                    if attack.dispatched then attacks = attacks + 1 end
                    game.sleep(0.25)
                    if options.loot then game.pickup() end
                end
            else
                game.sleep(0.1)
            end
        end
    end
    game.stop()
    while game.time() < deadline do
        local s = game.state()
        if
            not s.ready
            or s.instance_id ~= initial.instance_id
            or s.character.id ~= initial.character.id
            or s.map_id ~= initial.map_id
            or s.scene_generation ~= initial.scene_generation
            or s.character.hp <= 0
        then
            return
        end
        local distance = options.retreat_x - s.position.x
        if math.abs(distance) <= 12 then break end
        game.move(distance > 0 and "right" or "left", math.min(0.2, math.max(0.02, math.abs(distance) / 180)))
    end
    game.stop()
    game.log("attack_attempts=" .. attacks)
end
