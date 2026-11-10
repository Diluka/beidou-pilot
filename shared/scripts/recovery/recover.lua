-- Repeated recovery is driven in the client; this script never controls GUI slots.
local initial = game.state()
assert(initial.ready and initial.character and initial.position, "use_context_unavailable")
local deadline = game.time() + options.seconds
local used = 0

local function observe()
    local s = game.state()
    assert(s.ready and s.instance_id == initial.instance_id and s.character and s.character.id == initial.character.id
        and s.map_id == initial.map_id and s.scene_generation == initial.scene_generation,
        "use_context_changed")
    assert(s.character.hp > 0, "dead")
    assert(s.inventory, "inventory_unavailable")
    local quantity = 0
    for _, item in ipairs(s.inventory) do
        if item.item_id == options.item_id then
            assert(item.quantity ~= nil, "inventory_unavailable")
            quantity = quantity + item.quantity
        end
    end
    return s, quantity
end

while used < options.count do
    local s, quantity = observe()
    local c = s.character
    if (options.target_hp or options.target_mp)
        and (not options.target_hp or c.hp >= options.target_hp)
        and (not options.target_mp or c.mp >= options.target_mp) then
        return
    end
    local hp_needed = (options.heals_hp or not options.healing_known) and c.hp < c.max_hp
        and (not options.target_hp or c.hp < options.target_hp)
    local mp_needed = (options.heals_mp or not options.healing_known) and c.mp < c.max_mp
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
            or not options.healing_known and
                ((hp_needed and after.character.hp > c.hp) or (mp_needed and after.character.mp > c.mp))
        if after_quantity == quantity - 1 and (options.consume_only or recovered) then break end
        assert(game.time() < confirm_until,
            after_quantity == quantity - 1 and "healing_not_confirmed" or "use_not_confirmed")
        game.sleep(0.05)
    end
    used = used + 1
    if used < options.count then game.sleep(0.7) end
end
