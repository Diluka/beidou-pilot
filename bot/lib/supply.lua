local M = {}

-- 不存在配置时保持既有行为；只有明确配置的品种参与低水位检查。
function M.check(root, inventory)
    local file = io.open(root .. "/supply.conf", "r")
    if not file then return nil end
    local fields, invalid = {}, false
    for line in file:lines() do
        if not line:match("^%s*$") and not line:match("^%s*#") then
            local key, value = line:match("^%s*([%w_]+)%s*=%s*(%d+)%s*$")
            if not key or fields[key] then invalid = true else fields[key] = tonumber(value) end
        end
    end
    file:close()
    local allowed = {red_item = true, red_low = true, blue_item = true, blue_low = true,
        arrow_item = true, arrow_low = true}
    local count = 0
    for key in pairs(fields) do
        count = count + 1
        if not allowed[key] then invalid = true end
    end
    for _, kind in ipairs({"red", "blue", "arrow"}) do
        local id, threshold = fields[kind .. "_item"], fields[kind .. "_low"]
        if (id and not threshold) or (threshold and not id) or (id and (id <= 0 or threshold <= 0)) then
            invalid = true
        end
    end
    if invalid or count == 0 then return {reason = "invalid_config"} end
    local lows = {}
    for _, kind in ipairs({"red", "blue", "arrow"}) do
        local id, threshold = fields[kind .. "_item"], fields[kind .. "_low"]
        if id and threshold and id > 0 and threshold > 0 then
            if not inventory then return {reason = "inventory_unavailable"} end
            local quantity = 0
            for _, item in ipairs(inventory) do
                if item.item_id == id then
                    if type(item.quantity) ~= "number" or item.quantity < 0 then
                        return {reason = "inventory_unavailable", item_id = id}
                    end
                    quantity = quantity + item.quantity
                end
            end
            if quantity < threshold then
                lows[#lows + 1] = {kind = kind, item_id = id, quantity = quantity, threshold = threshold}
            end
        end
    end
    if #lows > 0 then return {reason = "low", items = lows} end
end

return M
