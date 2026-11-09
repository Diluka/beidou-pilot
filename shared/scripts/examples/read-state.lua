-- 只读分支与有界循环：观察期间不发按键或技能。
local initial = game.state()
if not initial.ready or not initial.character then
    return
end

for sample = 1, 3 do
    local current = game.state()
    if not current.ready or current.map_id ~= initial.map_id then
        return
    end
    if current.character.hp <= 0 then
        return
    end
    game.sleep(0.05)
end
