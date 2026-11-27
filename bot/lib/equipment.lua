-- 装备换装/待卖清单的持久化状态机（配合 lib.memory，客户端观察始终权威）。
-- store.equipment = { equipped = {slot=item_id}, sell_list = { {item_id, slot, source, approved} }, candidates = {item_id} }
local memory = require("lib.memory")

local M = {}

local PROTECTED = {
    [1452051] = true, -- 一转奖励弓：不自动进待卖清单
}

local function protected(item_id)
    return PROTECTED[item_id] == true
end

function M.state(store)
    if type(store.equipment) ~= "table" then store.equipment = { equipped = {}, sell_list = {}, candidates = {} } end
    local state = store.equipment
    state.equipped = state.equipped or {}
    state.sell_list = state.sell_list or {}
    state.candidates = state.candidates or {}
    return state
end

local function in_sell_list(state, item_id)
    for _, entry in ipairs(state.sell_list) do
        if entry.item_id == item_id then return entry end
    end
    return nil
end

-- 与客户端观察对账：换装后旧装备自动进待卖清单；清单/候选里不存在的物品自动移除。
function M.reconcile(store, live)
    local state = M.state(store)
    local repairs = {}
    local live_items = {}
    for _, item_id in ipairs(live.inventory or {}) do live_items[item_id] = true end

    -- 1. 已装备变化：旧装备（曾在 equipped 里、现在被替换）→ 待卖清单
    for slot, live_item in pairs(live.equipped or {}) do
        local previous = state.equipped[slot]
        if previous and previous ~= live_item then
            if not protected(previous) and not in_sell_list(state, previous) then
                state.sell_list[#state.sell_list + 1] = {
                    item_id = previous, slot = slot, source = "equipped_change", approved = false,
                }
                repairs[#repairs + 1] = { key = "swap", slot = slot, previous = previous, current = live_item }
            end
        end
        if previous ~= live_item then
            state.equipped[slot] = live_item
            store.__dirty = true
        end
    end

    -- 2. 待卖清单/候选物品已不在背包（卖掉/消耗/离线被处理）→ 移除，保持清单与客户端一致
    local kept_sell = {}
    for _, entry in ipairs(state.sell_list) do
        if live_items[entry.item_id] then kept_sell[#kept_sell + 1] = entry
        else repairs[#repairs + 1] = { key = "sell_list_stale", item_id = entry.item_id } end
    end
    if #kept_sell ~= #state.sell_list then state.sell_list = kept_sell; store.__dirty = true end

    local kept_candidates = {}
    for _, item_id in ipairs(state.candidates) do
        if live_items[item_id] then kept_candidates[#kept_candidates + 1] = item_id
        else repairs[#repairs + 1] = { key = "candidate_stale", item_id = item_id } end
    end
    if #kept_candidates ~= #state.candidates then state.candidates = kept_candidates; store.__dirty = true end

    state.last_reconcile_now = live.now
    return repairs
end

-- 人工确认待卖物品（离线重登后仍保留）；返回可交给自动清包的清单。
function M.approve(store, item_id)
    local state = M.state(store)
    local entry = in_sell_list(state, item_id)
    if not entry then
        entry = { item_id = item_id, source = "manual", approved = false }
        state.sell_list[#state.sell_list + 1] = entry
    end
    entry.approved = true
    store.__dirty = true
    return true
end

function M.add_candidate(store, item_id)
    local state = M.state(store)
    if protected(item_id) or in_sell_list(state, item_id) then return false end
    for _, existing in ipairs(state.candidates) do
        if existing == item_id then return false end
    end
    state.candidates[#state.candidates + 1] = item_id
    store.__dirty = true
    return true
end

function M.approved_items(store)
    local state = M.state(store)
    local result = {}
    for _, entry in ipairs(state.sell_list) do
        if entry.approved then result[#result + 1] = entry.item_id end
    end
    return result
end

function M.mark_sold(store, item_id)
    local state = M.state(store)
    local kept = {}
    local removed = false
    for _, entry in ipairs(state.sell_list) do
        if entry.item_id == item_id then removed = true
        else kept[#kept + 1] = entry end
    end
    if removed then state.sell_list = kept; store.__dirty = true end
    return removed
end

return M
