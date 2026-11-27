package.path = "bot/?.lua;" .. package.path
os.execute("mkdir -p tmp")
local memory = require("lib.memory")
local equipment = require("lib.equipment")

os.remove("tmp/bot-test-equipment.lua")
local store = { schema = 1 }
memory.set(store, "equipment", "equipped", { [-11] = 1302000 }) -- 旧剑
memory.set(store, "equipment", "sell_list", {})
memory.set(store, "equipment", "candidates", {})

-- 换装：旧剑 → 待卖清单（approved=false），新弓记录为已装备
local repairs = equipment.reconcile(store, {
    inventory = { 1302000, 1452051, 4000999 },
    equipped = { [-11] = 1452051 },
})
local approve_count = 0
for _, entry in ipairs(store.equipment.sell_list) do if entry.item_id == 1302000 then approve_count = approve_count + 1 end end
assert(approve_count == 1, "old equipped weapon must enter sell list")
assert(store.equipment.equipped[-11] == 1452051, "equipped snapshot must follow client")
assert(#repairs >= 1 and repairs[1].key == "swap")

-- 离线重登后：清单里已被卖掉/不存在的装备自动移除
memory.set(store, "equipment", "sell_list", { { item_id = 1302000, approved = true } })
local repairs2 = equipment.reconcile(store, { inventory = { 1452051 }, equipped = { [-11] = 1452051 } })
assert(#store.equipment.sell_list == 0, "sold item must leave sell list")
assert(#repairs2 >= 1 and repairs2[1].key == "sell_list_stale")

-- 人工确认 → 自动清包清单；标记卖掉后清理
assert(equipment.approve(store, 4000999))
memory.set(store, "equipment", "sell_list", { { item_id = 4000999, approved = true } })
assert(equipment.approved_items(store)[1] == 4000999)
assert(equipment.mark_sold(store, 4000999))
assert(#store.equipment.sell_list == 0)

-- 保护的一转弓不进待卖清单
assert(not equipment.add_candidate(store, 1452051))

-- 持久化 round-trip：重登后清单仍在
memory.set(store, "equipment", "sell_list", { { item_id = 4000998, approved = true } })
assert(memory.save(store, "tmp/bot-test-equipment.lua"))
local reloaded = assert(memory.load("tmp/bot-test-equipment.lua"))
assert(#equipment.state(reloaded).sell_list == 1, "sell list must survive relogin")
os.remove("tmp/bot-test-equipment.lua")
print("equipment tests ok")
