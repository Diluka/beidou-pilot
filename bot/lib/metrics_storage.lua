-- The caller supplies its complete append-only encoded rows; successful rotation
-- removes the archived prefix in place. state.rotation reports the last rotation
-- (generation and discarded_bytes); generation is local to this storage instance.
local M = {}
local LIMIT = 256 * 1024
local prefix, suffix = '{"schema":1,"records":[', ']}\n'

-- Validate JSON without evaluating it, retaining the exact record bytes on disk.
local function valid_json(text)
    local i, n = 1, #text
    local function whitespace()
        while i <= n and text:sub(i, i):match('[ \t\r\n]') do i = i + 1 end
    end
    local value
    local function string_value()
        if text:sub(i, i) ~= '"' then return false end
        i = i + 1
        while i <= n do
            local c = text:sub(i, i)
            if c == '"' then i = i + 1; return true end
            if c:byte() < 32 then return false end
            if c == '\\' then
                i = i + 1
                c = text:sub(i, i)
                if c == 'u' then
                    if not text:sub(i + 1, i + 4):match('^%x%x%x%x$') then return false end
                    i = i + 4
                elseif not c:match('^["\\/bfnrt]$') then return false end
            end
            i = i + 1
        end
        return false
    end
    value = function(depth)
        if depth > 100 then return false end
        whitespace()
        local c = text:sub(i, i)
        if c == '"' then return string_value() end
        if c == '{' or c == '[' then
            local closing = c == '{' and '}' or ']'
            i = i + 1; whitespace()
            if text:sub(i, i) == closing then i = i + 1; return true end
            while true do
                if c == '{' then
                    if not string_value() then return false end
                    whitespace()
                    if text:sub(i, i) ~= ':' then return false end
                    i = i + 1
                end
                if not value(depth + 1) then return false end
                whitespace()
                local next_char = text:sub(i, i)
                if next_char == closing then i = i + 1; return true end
                if next_char ~= ',' then return false end
                i = i + 1; whitespace()
            end
        end
        for _, literal in ipairs({'true', 'false', 'null'}) do
            if text:sub(i, i + #literal - 1) == literal then i = i + #literal; return true end
        end
        local rest = text:sub(i)
        local number = rest:match('^-?%d+%.%d+[eE][+-]?%d+') or rest:match('^-?%d+[eE][+-]?%d+')
            or rest:match('^-?%d+%.%d+') or rest:match('^-?%d+')
        if not number or number:match('^-?0%d') then return false end
        i = i + #number
        return true
    end
    if not value(0) then return false end
    whitespace()
    return i > n
end

local function read_file(path)
    local file, err, code = io.open(path, 'rb')
    if not file then
        if code == 2 then return nil end
        return nil, 'open_failed: ' .. tostring(err)
    end
    local data, read_err = file:read('*a')
    local closed, close_err = file:close()
    if not data or not closed then return nil, 'read_failed: ' .. tostring(read_err or close_err) end
    return data
end

local function write_file(path, content)
    local file, err = io.open(path, 'wb')
    if not file then return false, 'open_failed: ' .. tostring(err) end
    local written, write_err = file:write(content)
    local closed, close_err = file:close()
    if not written or not closed then return false, 'write_failed: ' .. tostring(write_err or close_err) end
    return true
end

function M.new(path)
    local archive = path:gsub('%.json$', '.1.json')
    if archive == path then return nil, 'invalid_path' end
    for _, backup_path in ipairs({path .. '.bak', archive .. '.bak'}) do
        local backup, backup_err = read_file(backup_path)
        if backup_err then return nil, backup_err end
        if backup then return nil, 'recovery_required: ' .. backup_path end
    end
    local text, err = read_file(path)
    if err then return nil, err end
    local old = ''
    if text then
        if #text > LIMIT or text:sub(1, #prefix) ~= prefix or text:sub(-#suffix) ~= suffix then
            return nil, 'invalid_snapshot'
        end
        old = text:sub(#prefix + 1, -#suffix - 1)
        if not valid_json('[' .. old .. ']') then return nil, 'invalid_snapshot' end
    end
    return {path=path, archive=archive, old=old, committed={}, first=1}
end

function M.save(state, rows)
    for _, backup_path in ipairs({state.path .. '.bak', state.archive .. '.bak'}) do
        local backup, err = read_file(backup_path)
        if err then return false, err end
        if backup then return false, 'recovery_required: ' .. backup_path end
    end
    for i, row in ipairs(rows) do
        -- Immutable committed strings were validated before the successful save.
        if state.committed[i] ~= row then
            if type(row) ~= 'string' or row:sub(1, 1) ~= '{' or not valid_json(row) then return false, 'invalid_record' end
            if state.committed[i] then return false, 'records_changed' end
        end
    end
    if #rows < #state.committed then return false, 'records_changed' end
    local function snapshot(first, old)
        local records = {}
        if old ~= '' then records[#records + 1] = old end
        for i = first, #rows do records[#records + 1] = rows[i] end
        return prefix .. table.concat(records, ',') .. suffix
    end
    local content = snapshot(state.first, state.old)
    if #content > LIMIT then
        local next_first = #state.committed + 1
        local fresh = snapshot(next_first, '')
        if #fresh > LIMIT then return false, 'snapshot_too_large' end
        local archive, err = read_file(state.archive)
        if err then return false, err end
        local backup, backup_err = read_file(state.archive .. '.bak')
        if backup_err then return false, backup_err end
        if backup then return false, 'recovery_required: ' .. state.archive .. '.bak' end
        local current, current_err = read_file(state.path)
        if current_err then return false, current_err end
        if not current then return false, 'snapshot_missing' end
        if archive and not os.rename(state.archive, state.archive .. '.bak') then return false, 'rotate_failed' end
        if not os.rename(state.path, state.archive) then
            if archive and not os.rename(state.archive .. '.bak', state.archive) then
                return false, 'recovery_required: ' .. state.archive .. '.bak'
            end
            return false, 'rotate_failed'
        end
        state.old, state.first = '', next_first
        state.rotation = {generation = (state.rotation and state.rotation.generation or 0) + 1,
            discarded_bytes = archive and #archive or 0}
        if archive and not os.remove(state.archive .. '.bak') then
            return false, 'recovery_required: ' .. state.archive .. '.bak'
        end
        content = fresh
    end
    local temporary = state.path .. '.tmp'
    local ok, err = write_file(temporary, content)
    if not ok then return false, err end
    if not os.rename(temporary, state.path) then
        -- Windows cannot replace an existing file. Move it aside first, never delete it.
        local current, read_err = read_file(state.path)
        if read_err then return false, read_err end
        if not current then return false, 'rename_failed' end
        if not os.rename(state.path, state.path .. '.bak') then return false, 'rename_failed' end
        if not os.rename(temporary, state.path) then
            if not os.rename(state.path .. '.bak', state.path) then return false, 'recovery_required' end
            return false, 'rename_failed'
        end
        if not os.remove(state.path .. '.bak') then return false, 'recovery_required' end
    end
    if state.first > 1 then
        local removed = state.first - 1
        for i = 1, #rows - removed do rows[i] = rows[i + removed] end
        for i = #rows, #rows - removed + 1, -1 do rows[i] = nil end
        state.first = 1
    end
    state.committed = {}
    for i, row in ipairs(rows) do state.committed[i] = row end
    return true
end

return M
