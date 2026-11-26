local M = {}
local EVENT_LIMIT = 1024 * 1024

M.platform_error = package.config:sub(1, 1) == "\\" and "unsupported_platform: bot_package_requires_posix" or nil
local JSON_NULL = {}
local recent_ids, recent_order = {}, {}
local ready_roots, last_publish = {}, nil

local function root_for(ctx)
    return ctx.state and ctx.state.bot_root or "/work/bot"
end

local function shell_quote(value)
    return "'" .. value:gsub("'", "'\\''") .. "'"
end

local function ensure_directories(root)
    if ready_roots[root] then return true end
    local ok = os.execute("mkdir -p " .. shell_quote(root .. "/queue/done") .. " " .. shell_quote(root .. "/queue/rejected"))
    if not ok then return false, "mkdir_failed" end
    ready_roots[root] = true
    return true
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
    file:close()
    if size + #line > EVENT_LIMIT then
        os.remove(root .. "/events.1.jsonl")
        if exists(path) and not os.rename(path, root .. "/events.1.jsonl") then
            return false, "events_rotate_failed"
        end
    end
    file = io.open(path, "a")
    if not file then return false, "events_open_failed" end
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
        if key ~= "id" and key ~= "kind" and key ~= "target" and key ~= "ttl" and key ~= "source" then
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
    local seq, filename_id = path:match("/(%d+)%-([%w_-]+)%.cmd$")
    if not seq or filename_id ~= fields.id then return fields, "filename_mismatch" end
    fields.ttl = ttl
    fields.sequence = tonumber(seq)
    return fields
end

local function receipt(ctx, command)
    local root = root_for(ctx)
    local destination = command._ok and root .. "/queue/done/" .. command.id
        or root .. "/queue/rejected/" .. command.id
    local ok, reason = ensure_directories(root)
    if not ok then return false, reason end
    if exists(destination) then
        os.remove(command._path)
        return true
    end
    if not os.rename(command._path, destination) then return false, "receipt_move_failed" end
    local content = command._ok and "ok\n" or "rejected=" .. tostring(command._reason or "rejected") .. "\n"
    local file = io.open(destination, "w")
    if not file then return false, "receipt_write_failed" end
    local written = file:write(content)
    local closed = file:close()
    if not written or not closed then return false, "receipt_write_failed" end
    return true
end

function M.poll(ctx, now)
    local root = root_for(ctx)
    local ok, reason = ensure_directories(root)
    if not ok then return nil, reason end
    local queue = root .. "/queue"
    local listing_path, clock_path = queue .. "/.scan.tmp", queue .. "/.clock.tmp"
    local scan_ok = os.execute("find " .. shell_quote(queue) .. " -maxdepth 1 -type f -name '*.cmd' -printf '%T@ %p\\n' > "
        .. shell_quote(listing_path) .. " && date +%s.%N > " .. shell_quote(clock_path))
    if not scan_ok then return nil, "queue_scan_failed" end
    local clock = io.open(clock_path, "r")
    if not clock then
        os.remove(listing_path)
        return nil, "queue_clock_read_failed"
    end
    local scan_now = tonumber(clock:read("*l"))
    clock:close()
    os.remove(clock_path)
    if not scan_now then
        os.remove(listing_path)
        return nil, "queue_clock_invalid"
    end
    local listing = io.open(listing_path, "r")
    if not listing then return nil, "queue_scan_read_failed" end
    local paths = {}
    for line in listing:lines() do
        local modified_at, path = line:match("^(%d+%.?%d*) (.+)$")
        if modified_at and path then
            paths[#paths + 1] = {modified_at = tonumber(modified_at), path = path}
        end
    end
    listing:close()
    os.remove(listing_path)
    table.sort(paths, function(left, right)
        local left_seq = tonumber(left.path:match("/(%d+)%-")) or math.huge
        local right_seq = tonumber(right.path:match("/(%d+)%-")) or math.huge
        if left_seq == right_seq then return left.path < right.path end
        return left_seq < right_seq
    end)

    local commands = {}
    for _, entry in ipairs(paths) do
        local path = entry.path
        local fields, parse_error = parse_command(path)
        local _, filename_id = path:match("/(%d+)%-([%w_-]+)%.cmd$")
        local id = filename_id or (fields and fields.id)
        if id and id:match("^[%w_-]+$") then
            local command = fields or {id = id}
            command._path = path
            if recent_ids[id] or exists(root .. "/queue/done/" .. id)
                or exists(root .. "/queue/rejected/" .. id) then
                command._ok, command._reason, command._skip_receipt = false, "duplicate_id", true
                os.remove(path)
            elseif parse_error then
                command._ok, command._reason = false, parse_error
                remember(id)
            else
                if command.ttl > 0 and scan_now - entry.modified_at >= command.ttl then
                    command._ok, command._reason = false, "expired"
                    remember(id)
                else
                    command._ok = true
                    remember(id)
                end
            end
            commands[#commands + 1] = command
        end
    end
    return commands
end

function M.publish(ctx, world, now)
    local bot = ctx.state and ctx.state.bot or {}
    local directories_ok, directory_error = ensure_directories(root_for(ctx))
    if not directories_ok then return false, directory_error end
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
    if not os.rename(temporary, root .. "/state.json") then return false, "state_rename_failed" end
    last_publish = now
    if ctx.state then ctx.state.force_publish = nil end

    for _, command in ipairs(ctx.state and ctx.state.pending_receipts or {}) do
        local receipt_ok, receipt_error = receipt(ctx, command)
        if not receipt_ok then
            bot.last_error = receipt_error
            append_event(root, {ts_ms = os.time() * 1000, type = "error", data = {reason = receipt_error, id = command.id}})
        end
    end
    if ctx.state then ctx.state.pending_receipts = {} end
    return true
end

function M.event(ctx, kind, data)
    if type(kind) ~= "string" or kind == "" then return false, "invalid_event_type" end
    local root = root_for(ctx)
    local directories_ok, directory_error = ensure_directories(root)
    if not directories_ok then return false, directory_error end
    local ok, reason = append_event(root, {
        ts_ms = os.time() * 1000, type = kind, data = data or {},
    })
    return ok, reason
end

return M
