-- 同一脚本可顺序在原版与无头端执行；不要求随机结果或轨迹完全一致。
local initial = game.state()
assert(initial.ready and initial.character.hp > 0, "character_not_ready")

game.move("right", 0.2)
game.face("left")
game.jump()
game.sleep(0.6)

local current = game.state()
assert(current.ready and current.character.id == initial.character.id, "character_changed")
assert(current.map_id == initial.map_id, "map_changed")
game.attack()
game.pickup()

current = game.state()
if current.character.hp < current.character.max_hp * 0.8 then
    for _, item in ipairs(current.inventory or {}) do
        if item.quantity and item.quantity > 0 and
            (item.item_id == 2000013 or item.item_id == 2000000) then
            game.use_item(item.item_id)
            break
        end
    end
end
game.stop()
game.log("common_basic_returned")
