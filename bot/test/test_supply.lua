package.path = "bot/?.lua;bot/?/init.lua;" .. package.path
local supply = require("lib.supply")
local real_open = io.open
local config
io.open = function(path, mode)
    if path == "/supply-test/supply.conf" then
        if not config then return nil end
        local lines = {}
        for line in config:gmatch("[^\n]+") do lines[#lines + 1] = line end
        local index = 0
        return {lines = function() return function() index = index + 1; return lines[index] end end,
            close = function() end}
    end
    return real_open(path, mode)
end
assert(supply.check("/supply-test", {}) == nil)
config = "red_item=2000000\nred_low=5\narrow_item=2060000\narrow_low=50\n"
local low = supply.check("/supply-test", {{item_id=2000000, quantity=5}, {item_id=2060000, quantity=49}})
assert(low.reason == "low" and #low.items == 1 and low.items[1].kind == "arrow")
assert(supply.check("/supply-test", nil).reason == "inventory_unavailable")
config = "red_item=2000000\nred_low=oops\n"
assert(supply.check("/supply-test", {}).reason == "invalid_config")
io.open = real_open
print("supply tests passed")
