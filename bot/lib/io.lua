local M = {}
local EVENT_LIMIT = 1024 * 1024

local JSON_NULL = {}
local recent_ids, recent_order, inflight = {}, {}, {}
local last_publish = nil

local function root_for(ctx)
    return ctx.state and ctx.state.bot_root or "/work/bot"
end

local function exists(path)
    local file = io.open(path, "r")
    if not file then return false end
    file:close()
    return true
end

local function escape_string(value)
    return '"' .. value:gsub('[%z\1-\31\\"]', function(char)
        local escapes = {['\\'] = '\\\\', ['"'] = '\\"', ['\b'] = '\\b', ['\f'] = '\\f', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t'}
        return escapes[char] or string.format("\\u%04x", char:byte())
    end) .. '"'
end

local function encode(value)
    if value == JSON_NULL then return "null" end
    local kind = type(value)
    if value == nil then return "null" end
    if kind == "boolean" then return value and "true" or "false" end
    if kind == "number" then
        if value ~= value or value == math.huge or value == -math.huge then return "null" end
        return string.format("%.14g", value)
    end
    if kind == "string" then return escape_string(value) end
    if kind ~= "table" then return "null" end

    local count, max_index, array = 0, 0, true
    for key in pairs(value) do
        count = count + 1
        if type(key) ~= "number" or key < 1 or key % 1 ~= 0 then
            array = false
        elseif key > max_index then
            max_index = key
        end
    end
    if count > 0 and array and count == max_index then
        local items = {}
        for i = 1, max_index do items[#items + 1] = encode(value[i]) end
        return "[" .. table.concat(items, ",") .. "]"
    end
    local keys = {}
    for key in pairs(value) do
        if type(key) == "string" then keys[#keys + 1] = key end
    end
    table.sort(keys)
    local items = {}
    for _, key in ipairs(keys) do items[#items + 1] = escape_string(key) .. ":" .. encode(value[key]) end
    return "{" .. table.concat(items, ",") .. "}"
end

local function event_path(root)
    return root .. "/events.jsonl"
end

local function append_event(root, record)
    local path = event_path(root)
    local line = encode(record) .. "\n"
    if #line > EVENT_LIMIT then return false, "event_too_large" end
    local file = io.open(path, "a+")
    if not file then return false, "events_open_failed" end
    local size = file:seek("end") or 0
    if size + #line > EVENT_LIMIT then
        file:close()
        os.remove(root .. "/events.1.jsonl")
        if exists(path) and not os.rename(path, root .. "/events.1.jsonl") then
            return false, "events_rotate_failed"
        end
        file = io.open(path, "a")
        if not file then return false, "events_open_failed" end
    end
    file:write(line)
    file:close()
    return true
end

local function remember(id)
    if recent_ids[id] then return end
    recent_ids[id] = true
    recent_order[#recent_order + 1] = id
    if #recent_order > 100 then
        recent_ids[table.remove(recent_order, 1)] = nil
    end
end

local function parse_command(path)
    local file = io.open(path, "r")
    if not file then return nil, "read_failed" end
    local fields = {}
    for line in file:lines() do
        if line ~= "" then
            local key, value = line:match("^([%w_]+)=(.*)$")
            if not key then
                file:close()
                return nil, "invalid_line"
            end
            if fields[key] ~= nil then
                file:close()
                return nil, "duplicate_field"
            end
            fields[key] = value
        end
    end
    file:close()

    for key in pairs(fields) do
        if key ~= "id" and key ~= "kind" and key ~= "target" and key ~= "ttl" and key ~= "source" and key ~= "created_ms" then
            return fields, "unknown_field"
        end
    end
    if not fields.id or not fields.id:match("^[%w_-]+$") then return fields, "invalid_id" end
    if not fields.kind then return fields, "missing_kind" end
    if fields.kind ~= "follow" and fields.kind ~= "hunt" and fields.kind ~= "stay"
        and fields.kind ~= "status" and fields.kind ~= "stop" then
        return fields, "unknown_kind"
    end
    local ttl = fields.ttl and tonumber(fields.ttl)
    if ttl == nil or ttl ~= ttl or ttl < 0 or ttl == math.huge or ttl == -math.huge then
        return fields, "invalid_ttl"
    end
    if fields.source ~= "host" and fields.source ~= "cli" then return fields, "invalid_source" end
    local created = tonumber(fields.created_ms)
    if ttl > 0 and (not created or created ~= created or created < 0 or created == math.huge) then
        return fields, "invalid_created_ms"
    end
    fields.ttl, fields.created_ms = ttl, created
    return fields
end

local function receipt(ctx, command)
    local root = root_for(ctx)
    local destination = command._ok and root .. "/queue/done/" .. command.id
        or root .. "/queue/rejected/" .. command.id
    if exists(destination) then
        os.remove(command._path)
        inflight[command._path] = nil
        return true
    end
    local temporary = destination .. ".tmp"
    local file = io.open(temporary, "w")
    if not file then return false, "receipt_write_failed" end
    local content = command._ok and "ok\n" or "rejected=" .. tostring(command._reason or "rejected") .. "\n"
    local written = file:write(content)
    local closed = file:close()
    if not written or not closed then return false, "receipt_write_failed" end
    if not os.rename(temporary, destination) then return false, "receipt_move_failed" end
    os.remove(command._path)
    inflight[command._path] = nil
    return true
end

function M.poll(ctx, now)
    local root = root_for(ctx)
    local commands = {}
    for slot = 1, 8 do
        local path = root .. "/queue/slot" .. slot .. ".cmd"
        local claimed = root .. "/queue/slot" .. slot .. ".processing"
        local processing = exists(claimed)
        local interrupted = processing and not inflight[claimed]
        local acquired = false
        if not processing and exists(path) then acquired = os.rename(path, claimed) and true or false end
        if acquired or interrupted then
            local fields, parse_error = parse_command(claimed)
            local id = fields and fields.id
            if id and id:match("^[%w_-]+$") then
                local command = fields
                command._path = claimed
                if recent_ids[id] or exists(root .. "/queue/done/" .. id)
                    or exists(root .. "/queue/rejected/" .. id) then
                    command._ok, command._reason, command._skip_receipt = false, "duplicate_id", true
                    os.remove(claimed)
                elseif interrupted then
                    command._ok, command._reason = false, "interrupted"
                    remember(id)
                elseif parse_error then
                    command._ok, command._reason = false, parse_error
                    remember(id)
                elseif command.ttl > 0 and os.time() * 1000 - command.created_ms >= command.ttl * 1000 then
                    command._ok, command._reason = false, "expired"
                    remember(id)
                else
                    command._ok = true
                    remember(id)
                end
                if not command._skip_receipt then inflight[claimed] = true end
                commands[#commands + 1] = command
            else
                os.remove(claimed)
            end
        end
    end
    return commands
end

function M.publish(ctx, world, now)
    local bot = ctx.state and ctx.state.bot or {}
    local force = ctx.state and ctx.state.force_publish
    if not force and last_publish ~= nil and now - last_publish < 1 then return true end

    local character, owner = world.character or {}, world.owner
    local status = {
        schema = 1, ts_ms = os.time() * 1000,
        session_id = ctx.tick and ctx.tick.script_id or JSON_NULL,
        version = "bot-0.1.0", mode = bot.mode or "recover",
        map_id = world.map_id or JSON_NULL, scene_generation = world.scene_generation or JSON_NULL,
        x = character.x or JSON_NULL, y = character.y or JSON_NULL,
        hp = character.hp or JSON_NULL, max_hp = character.max_hp or JSON_NULL,
        mp = character.mp or JSON_NULL, max_mp = character.max_mp or JSON_NULL,
        owner = owner and {
            present = owner.present == nil and JSON_NULL or owner.present,
            name = owner.name or JSON_NULL, distance = owner.distance or JSON_NULL,
        } or JSON_NULL,
        target = bot.target or JSON_NULL, last_command = bot.last_command or JSON_NULL,
        last_error = bot.last_error or JSON_NULL,
        uptime_s = now - (ctx.state and ctx.state.started_at or now),
    }
    local root = root_for(ctx)
    local temporary = root .. "/state.json.tmp"
    local file = io.open(temporary, "w")
    if not file then return false, "state_open_failed" end
    file:write(encode(status), "\n")
    file:close()
    local destination = root .. "/state.json"
    if not os.rename(temporary, destination) then
        if not exists(destination) or not os.remove(destination) or not os.rename(temporary, destination) then
            return false, "state_rename_failed"
        end
        local state = ctx.state
        if state then
            state.rename_retry_count = (state.rename_retry_count or 0) + 1
            if not state.rename_retry_reported_at or now - state.rename_retry_reported_at >= 60 then
                local ok = append_event(root, {ts_ms = os.time() * 1000, type = "io/rename_retry",
                    data = {path = "state.json", count = state.rename_retry_count}})
                if ok then state.rename_retry_count, state.rename_retry_reported_at = 0, now end
            end
        end
    end
    last_publish = now
    if ctx.state then ctx.state.force_publish = nil end

    local remaining = {}
    for _, command in ipairs(ctx.state and ctx.state.pending_receipts or {}) do
        local receipt_ok, receipt_error = receipt(ctx, command)
        if not receipt_ok then
            remaining[#remaining + 1] = command
            bot.last_error = receipt_error
            append_event(root, {ts_ms = os.time() * 1000, type = "error", data = {reason = receipt_error, id = command.id}})
        end
    end
    if ctx.state then ctx.state.pending_receipts = remaining end
    return true
end

function M.event(ctx, kind, data)
    if type(kind) ~= "string" or kind == "" then return false, "invalid_event_type" end
    local root = root_for(ctx)
    local ok, reason = append_event(root, {
        ts_ms = os.time() * 1000, type = kind, data = data or {},
    })
    return ok, reason
end

return M
