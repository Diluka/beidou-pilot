-- 持久化状态存储合同：序列化/损坏恢复/命名空间/节流/超限。
package.path = "bot/?.lua;" .. package.path
local memory = require("lib.memory")

local path = "tmp/bot-test-memory-store.lua"
os.remove(path)
os.remove(path .. ".bak")
os.remove(path .. ".tmp")

-- 序列化 round-trip：嵌套/特殊字符/布尔/number
local store = { schema = 1, bot = { mode = "hunt", map_id = 104040000, patrol = 3,
    note = "a \"quoted\" line\nwith tab\t", active = true },
    supply = { red_goal = 25, items = { [2000000] = 3, [2060000] = 40 } } }
local text = assert(memory.serialize(store))
local decoded = assert(load(text))()
assert(decoded.bot.mode == "hunt" and decoded.bot.map_id == 104040000)
assert(decoded.bot.patrol == 3 and decoded.bot.active == true)
assert(decoded.bot.note == store.bot.note, "string escaping must round-trip")
assert(decoded.supply.items[2000000] == 3 and decoded.supply.items[2060000] == 40)

-- 保存/读取
assert(memory.save(store, path))
local loaded = assert(memory.load(path))
assert(loaded.bot.mode == "hunt" and loaded.supply.red_goal == 25)

-- 命名空间 get/set/unset
assert(memory.get(loaded, "bot", "patrol", 0) == 3)
assert(memory.get(loaded, "missing", "key", "fallback") == "fallback")
memory.set(loaded, "supply", "red_goal", 30)
assert(memory.get(loaded, "supply", "red_goal") == 30)
memory.unset(loaded, "supply", "red_goal")
assert(memory.get(loaded, "supply", "red_goal", "unset") == "unset")

-- 节流 flush：1 秒内二次 flush 被节流，强制 flush 写入
memory.set(loaded, "bot", "mode", "follow")
local flushed, reason = memory.flush(loaded, path, 10)
assert(flushed and reason == nil, "first flush must save")
memory.set(loaded, "bot", "patrol", 8)
local second, second_reason = memory.flush(loaded, path, 10.5)
assert(not second and second_reason == "throttled", "flush must throttle")
local forced = memory.flush(loaded, path, 12)
assert(forced, "flush after interval must save")

-- 损坏文件：备份 .bak 且返回 __corrupt 空表
local file = assert(io.open(path, "w")); file:write("return {{{"); file:close()
local corrupt, corrupt_reason = memory.load(path)
assert(corrupt_reason == "corrupt" and corrupt.__corrupt ~= nil)
assert(io.open(path .. ".bak", "r") ~= nil, "corrupt file must be backed up")

-- 客户端权威 + 自动修复：冲突字段被覆盖，未观测字段保留
memory.set(loaded, "bot", "mode", "hunt")
memory.set(loaded, "bot", "patrol", 7)
local repairs = memory.reconcile(loaded, "bot", { mode = "follow", map_id = 104040000, hp = 120 })
assert(#repairs == 2, "mode conflict and missing hp must be repaired")
assert(memory.get(loaded, "bot", "mode") == "follow")
assert(memory.get(loaded, "bot", "map_id") == 104040000)
assert(memory.get(loaded, "bot", "hp") == 120)
assert(memory.get(loaded, "bot", "patrol") == 7, "live 未出现的字段保留")
local same = memory.reconcile(loaded, "bot", { mode = "follow", map_id = 104040000 })
assert(#same == 0, "no repair when live matches memory")
local migrated, reason = memory.repair_meta(loaded, path, 2)
assert(migrated and reason:match("schema"), "schema mismatch must be repaired")
assert(loaded.schema == 2)

-- 超限拒绝
local huge = string.rep("x", 70 * 1024)
memory.set(loaded, "bot", "huge", huge)
local saved, save_reason = memory.save(loaded, path)
assert(not saved and save_reason:match("too_large"), "oversize store must be rejected")

-- 清理
os.remove(path)
os.remove(path .. ".bak")
os.remove(path .. ".tmp")
print("memory tests ok")
