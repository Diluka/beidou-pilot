package.path = 'bot/?.lua;bot/?/init.lua;' .. package.path
local storage = require('lib.metrics_storage')
local open, rename, remove = io.open, os.rename, os.remove
local files, fail_write, fail_rename, windows, fail_source = {}, false, false, false, nil
io.open = function(path, mode)
    if mode == 'rb' then
        if not files[path] then return nil, 'missing', 2 end
        return {read=function() return files[path] end, close=function() return true end}
    end
    assert(mode == 'wb')
    local data = ''
    return {write=function(_, text)
        if fail_write then return nil, 'disk full' end
        data = data .. text
        return true
    end, close=function() files[path] = data; return true end}
end
os.rename = function(from, to)
    if fail_rename or from == fail_source or not files[from] or (windows and files[to]) then return nil, 'rename failed' end
    files[to], files[from] = files[from], nil
    return true
end
os.remove = function(path) files[path] = nil; return true end

local path = '/metrics.json'
local first = assert(storage.new(path))
assert(storage.save(first, {'{"a":1}'}))
assert(storage.save(first, {'{"a":1}', '{"a":2}'}))
assert(files[path] == '{"schema":1,"records":[{"a":1},{"a":2}]}\n')
local second = assert(storage.new(path))
assert(storage.save(second, {'{"a":3}'}))
assert(files[path] == '{"schema":1,"records":[{"a":1},{"a":2},{"a":3}]}\n')
assert(storage.save(second, {'{"a":3}'}))
assert(files[path] == '{"schema":1,"records":[{"a":1},{"a":2},{"a":3}]}\n')
local previous = files[path]
fail_write = true
assert(not storage.save(second, {'{"a":3}', '{"a":4}'}))
assert(files[path] == previous)
fail_write = false
windows = true
assert(storage.save(second, {'{"a":3}', '{"a":4}'}))
assert(not files[path .. '.bak'] and files[path]:find('{"a":4}', 1, true))
fail_rename = true
previous = files[path]
assert(not storage.save(second, {'{"a":3}', '{"a":4}', '{"a":5}'}))
assert(files[path] == previous)
fail_rename = false
assert(storage.save(second, {'{"a":3}', '{"a":4}', '{"a":5}'}))
local ok, reason = storage.save(second, {'{"a":99}'})
assert(not ok and reason == 'records_changed')
ok, reason = storage.save(second, {'{"a":bad}'})
assert(not ok and reason == 'invalid_record')
assert(storage.save(second, {'{"a":3}', '{"a":4}', '{"a":5}'}))

files = {}
local big = '{"data":"' .. string.rep('x', 140000) .. '"}'
local rotating = assert(storage.new(path))
local rows = {big}
assert(storage.save(rotating, rows))
rows[2] = big
fail_write = true
assert(not storage.save(rotating, rows))
assert(#rows == 2 and files['/metrics.1.json'] and not files[path])
fail_write = false
assert(storage.save(rotating, rows))
assert(#rows == 1)
assert(files[path] == '{"schema":1,"records":[' .. big .. ']}\n')
assert(files['/metrics.1.json'] == files[path])
assert(storage.save(rotating, rows))
rows[2] = big
fail_source = path
assert(not storage.save(rotating, rows))
assert(#rows == 2 and files[path] and files['/metrics.1.json'] and not files['/metrics.1.json.bak'])
fail_source = nil
assert(storage.save(rotating, rows))
assert(#rows == 1 and rotating.rotation.generation == 2)
assert(rotating.rotation.discarded_bytes == #files['/metrics.1.json'])
assert(files[path] == files['/metrics.1.json'])
files[path] = '{"schema":1,"records":[os.execute("bad")]}\n'
assert(not storage.new(path))
files[path] = '{"schema":1,"records":[01]}\n'
assert(not storage.new(path))
files[path] = '{"schema":1,"records":[{"x":"\\u00ff"}]}\n'
assert(storage.new(path))
io.open, os.rename, os.remove = open, rename, remove
print('metrics storage tests ok')
