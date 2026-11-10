-- 按需只读领域；不派发动作，也不通过主机文件取得状态。
local scene = game.observe("scene")
if scene.status ~= "ok" then
    game.log(scene.status .. ": " .. tostring(scene.error))
    return
end

game.log("地图：" .. tostring(scene.map_id))
for _, npc in ipairs(scene.data.npcs) do
    game.log("NPC：" .. tostring(npc.template_id) .. "，对象：" .. tostring(npc.object_id))
end

local inventory = game.observe("inventory")
if inventory.status == "ok" then
    -- unavailable/not_covered 同时保留；列出的条目不代表全部领域完整。
    for _, item in ipairs(inventory.data.equipped) do
        game.log("身上槽：" .. tostring(item.slot) .. "，物品：" .. tostring(item.item_id))
    end
end

local quests = game.observe("quests")
if quests.status == "ok" and quests.data.live_updates == false then
    game.log("任务为角色登录快照，来源更新时间未知")
end

local ui = game.observe("ui")
game.log("UI 领域：" .. ui.status) -- 无头端明确返回 unsupported。
