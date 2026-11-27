-- tick Lua 跨会话持久化状态：/work/bot/memory.lua（可读 Lua 表，原子写）。
-- 结构：{ schema = 1, updated_at = <tick 时间>, bot = {...}, supply = {...}, ... }
local M = {}

local MAX_BYTES = 64 * 1024
local FLUSH_INTERVAL = 1.0

local function is_identifier(key)
    return type(key) == "string" and key:match("^[%a_][%w_]*$") ~= nil and not key:match("^__")
end

local function escape(value)
    return (value:gsub("\\", "\\\\"):gsub("\"", "\\\""):gsub("\n", "\\n"):gsub("\r", "\\r"):gsub("\t", "\\t"))
end

local function serialize_value(value, depth, seen, out)
    if depth > 8 then return false, "depth" end
    local kind = type(value)
    if kind == "nil" then return true
    elseif kind == "boolean" or kind == "number" then
        out[#out + 1] = tostring(value)
        return true
    elseif kind == "string" then
        out[#out + 1] = "\"" .. escape(value) .. "\""
        return true
    elseif kind ~= "table" then
        return false, "unsupported:" .. kind
    end
    if seen[value] then return false, "cycle" end
    seen[value] = true
    out[#out + 1] = "{"
    local first = true
    for key, item in pairs(value) do
        if type(key) ~= "string" and type(key) ~= "number" then
            return false, "unsupported_key"
        end
        if not first then out[#out + 1] = "," end
        first = false
        if type(key) == "number" then
            out[#out + 1] = "[" .. tostring(key) .. "]="
        elseif is_identifier(key) then
            out[#out + 1] = key .. "="
        else
            out[#out + 1] = "[\"" .. escape(key) .. "\"]="
        end
        local ok, reason = serialize_value(item, depth + 1, seen, out)
        if not ok then return false, reason end
    end
    seen[value] = nil
    out[#out + 1] = "}"
    return true
end

function M.serialize(store)
    if type(store) ~= "table" then return nil, "store_not_table" end
    local parts = {}
    parts[#parts + 1] = "return "
    local ok, reason = serialize_value(store, 0, {}, parts)
    if not ok then return nil, reason end
    local text = table.concat(parts)
    if #text > MAX_BYTES then return nil, "too_large:" .. tostring(#text) end
    return text
end

-- 读取 store；文件不存在返回空表；损坏时备份为 .bak 并返回带 __corrupt 的空表。
function M.load(path, fallback_now)
    local store = { schema = 1, updated_at = fallback_now or 0 }
    local file = io.open(path, "r")
    if not file then return store, "missing" end
    local text = file:read("*a")
    file:close()
    local chunk, compile_error = load(text)
    if not chunk then
        os.rename(path, path .. ".bak")
        store.__corrupt = compile_error or "compile_failed"
        return store, "corrupt"
    end
    local ok, decoded = pcall(chunk)
    if not ok or type(decoded) ~= "table" then
        os.rename(path, path .. ".bak")
        store.__corrupt = tostring(decoded)
        return store, "corrupt"
    end
    for key, value in pairs(decoded) do store[key] = value end
    store.schema = store.schema or 1
    return store, nil
end

function M.get(store, namespace, key, default)
    local ns = store[namespace]
    if type(ns) ~= "table" then return default end
    local value = ns[key]
    if value == nil then return default end
    return value
end

function M.set(store, namespace, key, value)
    if type(store[namespace]) ~= "table" then store[namespace] = {} end
    store[namespace][key] = value
    store.__dirty = true
    return true
end

function M.unset(store, namespace, key)
    local ns = store[namespace]
    if type(ns) == "table" then ns[key] = nil; store.__dirty = true end
end

function M.save(store, path)
    local text, reason = M.serialize(store)
    if not text then return false, reason end
    local temporary = path .. ".tmp"
    local file = io.open(temporary, "w")
    if not file then return false, "open_failed" end
    local ok = file:write(text)
    file:close()
    if not ok then return false, "write_failed" end
    local renamed, rename_error = os.rename(temporary, path)
    if not renamed then
        local existing = io.open(path, "r")
        if not existing then return false, "rename_failed:" .. tostring(rename_error) end
        existing:close()
        local removed = os.remove(path)
        if not removed then return false, "rename_failed:" .. tostring(rename_error) end
        renamed, rename_error = os.rename(temporary, path)
        if not renamed then return false, "rename_failed:" .. tostring(rename_error) end
        print("bot memory rename retry: " .. path)
    end
    store.__dirty = nil
    store.__last_flush = store.__last_flush or 0
    return true
end

-- 节流保存：脏且距上次 ≥ interval 秒（使用调用方传入 now）才写。
function M.flush(store, path, now, interval)
    if not store.__dirty then return false, "clean" end
    interval = interval or FLUSH_INTERVAL
    if now and store.__last_flush and now - store.__last_flush < interval then
        return false, "throttled"
    end
    store.updated_at = now or store.updated_at
    store.__last_flush = now or 0
    return M.save(store, path)
end

function M.clear(store, namespace)
    store[namespace] = nil
    store.__dirty = true
end

-- 自动修复：live 是客户端权威状态。与 memory 冲突的字段一律覆盖为 live 值，
-- 并返回修复记录（供调用方发布 memory/repair 事件）。未在 live 出现的字段保留。
function M.reconcile(store, namespace, live)
    if type(store) ~= "table" or type(live) ~= "table" then return {} end
    if type(store[namespace]) ~= "table" then store[namespace] = {} end
    local repairs = {}
    for key, value in pairs(live) do
        if value ~= nil then
            local previous = store[namespace][key]
            if previous ~= value then
                store[namespace][key] = value
                store.__dirty = true
                repairs[#repairs + 1] = { key = key, previous = previous, current = value }
            end
        end
    end
    return repairs
end

-- 元数据自愈：schema 不符时迁移到当前版本；无法迁移则重置并备份。
function M.repair_meta(store, path, schema)
    schema = schema or 1
    if type(store) ~= "table" then return nil, "store_not_table" end
    if store.schema == schema then return false, nil end
    local previous = store.schema
    store.schema = schema
    store.__dirty = true
    return true, "schema:" .. tostring(previous) .. "->" .. tostring(schema)
end

return M
