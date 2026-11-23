package.path = "bot/?.lua;bot/?/init.lua;" .. package.path

local io_module = require("lib.io")
local state_module = require("lib.state")
local world_module = require("lib.world")
local saved_open = io.open
local saved_execute, saved_rename, saved_remove, saved_time = os.execute, os.rename, os.remove, os.time
local files, queue_paths, modified_at = {}, {}, {}
local root = "tmp/bot-io-test"

local function open_fake(path, mode)
    mode = mode or "r"
    if mode:find("r") and files[path] == nil and not mode:find("+") then return nil end
    local buffer = mode:find("r") and files[path] or mode:find("a") and (files[path] or "") or ""
    local cursor = 1
    local handle = {}
    function handle:lines()
        return function()
            if cursor > #buffer then return nil end
            local ending = buffer:find("\n", cursor, true) or (#buffer + 1)
            local line = buffer:sub(cursor, ending - 1)
            cursor = ending + 1
            return line
        end
    end
    function handle:read(format)
        if format == "*a" then return buffer end
        if format == "*l" then
            if cursor > #buffer then return nil end
            local ending = buffer:find("\n", cursor, true) or (#buffer + 1)
            local line = buffer:sub(cursor, ending - 1)
            cursor = ending + 1
            return line
        end
        return nil
    end
    function handle:write(value)
        buffer = buffer .. tostring(value)
        return self
    end
    function handle:seek(whence)
        if whence == "end" then return #buffer end
    end
    function handle:close()
        files[path] = buffer
        return true
    end
    return handle
end

io.open = open_fake
os.execute = function(command)
    local listing_path = command:match(" > '([^']+)' && date")
    local clock_path = command:match("date %S+ > '([^']+)'$")
    if listing_path then
        local lines = {}
        for _, path in ipairs(queue_paths) do
            if files[path] ~= nil then
                lines[#lines + 1] = tostring(modified_at[path] or saved_time()) .. " " .. path
            end
        end
        table.sort(lines)
        files[listing_path] = #lines > 0 and table.concat(lines, "\n") .. "\n" or ""
    end
    if clock_path then files[clock_path] = string.format("%.9f\n", saved_time() + 0.25) end
    return true
end
os.rename = function(source, destination)
    if files[source] == nil then return nil, "missing source" end
    files[destination] = files[source]
    modified_at[destination] = modified_at[source]
    files[source], modified_at[source] = nil, nil
    return true
end
os.remove = function(path)
    files[path] = nil
    return true
end

local function add_command(seq, id, body, mtime)
    local path = root .. "/queue/" .. seq .. "-" .. id .. ".cmd"
    files[path] = body
    modified_at[path] = mtime or saved_time()
    queue_paths[#queue_paths + 1] = path
    return path
end

local context = {state = {bot_root = root, bot = {mode = "recover"}, started_at = 1}}
local valid_path = add_command(1, "c1", "id=c1\nkind=status\nttl=0\nsource=host\n")
local commands = assert(io_module.poll(context, 1))
assert(#commands == 1 and commands[1].id == "c1" and commands[1].kind == "status")
commands[1]._ok = true
context.state.pending_receipts = commands
context.state.force_publish = true
assert(io_module.publish(context, {character = {}}, 1))
assert(files[root .. "/queue/done/c1"] == "ok\n" and files[valid_path] == nil)
assert(files[root .. "/state.json"]:find('"last_command":null', 1, true))

local duplicate_path = add_command(2, "c1", "id=c1\nkind=stop\nttl=0\nsource=host\n")
commands = assert(io_module.poll(context, 2))
assert(#commands == 1 and not commands[1]._ok and commands[1]._reason == "duplicate_id" and commands[1]._skip_receipt)
assert(files[duplicate_path] == nil and files[root .. "/queue/done/c1"] == "ok\n")

local invalid_path = add_command(3, "c2", "id=c2\nkind=unknown\nttl=0\nsource=host\n")
commands = assert(io_module.poll(context, 2))
assert(#commands == 1 and not commands[1]._ok and commands[1]._reason == "unknown_kind")
context.state.pending_receipts = commands
context.state.force_publish = true
assert(io_module.publish(context, {character = {}}, 2))
assert(files[root .. "/queue/rejected/c2"] == "rejected=unknown_kind\n" and files[invalid_path] == nil)

local fresh_path = add_command(4, "c4", "id=c4\nkind=hunt\nttl=1\nsource=cli\n", saved_time() - 0.5)
commands = assert(io_module.poll(context, 2.5))
assert(#commands == 1 and commands[1]._ok)
context.state.pending_receipts = commands
context.state.force_publish = true
assert(io_module.publish(context, {character = {}}, 2.5))
assert(files[root .. "/queue/done/c4"] == "ok\n" and files[fresh_path] == nil)

local expired_path = add_command(5, "c3", "id=c3\nkind=hunt\nttl=1\nsource=cli\n", saved_time() - 5)
commands = assert(io_module.poll(context, 3))
assert(#commands == 1 and not commands[1]._ok and commands[1]._reason == "expired")
context.state.pending_receipts = commands
context.state.force_publish = true
assert(io_module.publish(context, {character = {}}, 3))
assert(files[root .. "/queue/rejected/c3"] == "rejected=expired\n" and files[expired_path] == nil)

files["/work/bot/config.conf"] = "owner_name=Owner\nowner_character_id=12\nfollow_distance=99\n"
files["/work/bot/checkpoint.conf"] = "mode=hunt\ntarget=12\nmap_id=7\n"
local state = state_module.new()
assert(state.mode == "recover" and state.config.follow_distance == 99)
assert(state.checkpoint.mode == "hunt" and state.last_error == nil)
files["/work/bot/checkpoint.conf"] = nil
assert(state_module.new().last_error == "checkpoint_invalid_or_missing")
assert(state_module.apply(state, {kind = "follow"}))
assert(state.mode == "follow" and state.target == "12")
assert(state_module.apply(state, {kind = "status"}) and state.mode == "follow")
assert(state_module.apply(state, {kind = "hunt"}) and state.mode == "hunt" and state.target == nil)
assert(state_module.apply(state, {kind = "follow"}) and state.mode == "follow" and state.target == "12")
local stopped = 0
state.player = {stop = function() stopped = stopped + 1; return true end}
assert(state_module.apply(state, {kind = "stay"}) and state.mode == "idle" and stopped == 1)
assert(state_module.apply(state, {kind = "stop"}) and state.mode == "idle" and state.target == nil and stopped == 2)
assert(not state_module.transition(state, "invalid", "test"))
assert(state_module.transition(state, "dead", "test") and state.mode == "dead")

files[root .. "/config.conf"] = "owner_name=Owner\nowner_character_id=12\n"
local world = world_module.observe({
    tick = {time = 1}, state = {bot_root = root, bot = {target = "Other"}},
    game = {
        world = {ready = true, map_id = 7, scene_generation = 2},
        character = {x = 2, y = 3, hp = 9},
        scene = {
            players_complete = true,
            players = {
                {id = 12, name = "Owner", x = 5, y = 7},
                {id = 13, name = "Other", x = 2, y = 8},
            },
            monsters = {{id = 20, template_id = 100, x = 10, y = 11, hp = 5, max_hp = 10}},
            drops = {{id = 30, item_id = 400, x = 12, y = 13, landed = true}},
        },
        inventory = {items = {{item_id = 200, quantity = 4}}},
    },
})
assert(world.ready and world.map_id == 7 and world.scene_generation == 2)
assert(world.owner.present and world.owner.name == "Other" and world.owner.distance == 5)
assert(world.mobs[1].hp_percent == 50 and world.drops[1].landed and world.inventory[1].quantity == 4)
assert(world.character.max_hp == nil and world.character.platform == nil)
local unavailable_owner = world_module.observe({
    state = {bot_root = root, bot = {target = "Missing"}},
    game = {world = {ready = true}, scene = {players = {}, players_complete = false}},
})
assert(unavailable_owner.owner == nil)
local absent_owner = world_module.observe({
    state = {bot_root = root, bot = {target = "Missing"}},
    game = {world = {ready = true}, scene = {players = {}, players_complete = true}},
})
assert(absent_owner.owner.present == false)

local event_path = root .. "/events.jsonl"
local large_event = {text = string.rep("x", 600 * 1024)}
assert(io_module.event(context, "test", large_event))
assert(io_module.event(context, "test", large_event))
assert(files[root .. "/events.1.jsonl"]:find('"type":"test"', 1, true))
assert(files[event_path]:find('"type":"test"', 1, true))

local main_file = assert(saved_open("bot/main.lua", "r"))
local main_source = main_file:read("*a")
main_file:close()
local rewritten_source, replacements = main_source:gsub("local function main%(context%)", "function __test_main(context)", 1)
assert(replacements == 1, "main entry signature changed")
local calls, selected_mob, selected_drop = {}, {}, {}
local sustain_handled, movement_result = false, "done"
local combat_result, combat_reason, follow_action = "done", nil, nil
local target_platform, mover_stopped, pending_commands = 1, false, {}
local fake_modules = {
    ["lib.io"] = {
        event = function() calls[#calls + 1] = "event"; return true end,
        poll = function()
            calls[#calls + 1] = "poll"
            local commands = pending_commands
            pending_commands = {}
            return commands
        end,
        publish = function() calls[#calls + 1] = "publish"; return true end,
    },
    ["lib.state"] = {
        new = function() error("unexpected state initialization") end,
        apply = function(state, command)
            if command.kind == "follow" then
                state.mode, state.target = "follow", command.target or state.owner_target
            elseif command.kind == "hunt" then
                state.mode, state.target = "hunt", nil
            else
                state.mode = command.kind
            end
            return true
        end,
    },
    ["lib.world"] = {observe = function() calls[#calls + 1] = "observe"; return {
        ready = true, scene_generation = 1, character = {x = 1, y = 2, hp = 50},
    } end},
    ["lib.terrain"] = {
        build = function() error("unexpected terrain build") end,
        platform_at = function(_, x) return x == 1 and 1 or target_platform end,
        plan = function() calls[#calls + 1] = "plan"; return {} end,
    },
    ["lib.move"] = {
        new = function() error("unexpected mover creation") end,
        set_path = function()
            calls[#calls + 1] = "set_path"
            mover_stopped = false
            return true
        end,
        step = function()
            calls[#calls + 1] = "move"
            return mover_stopped and "done" or movement_result
        end,
        stop = function()
            calls[#calls + 1] = "stop"
            mover_stopped = true
            return true
        end,
    },
    ["lib.follow"] = {update = function()
        calls[#calls + 1] = "follow"
        return follow_action
    end},
    ["lib.combat"] = {
        select = function() calls[#calls + 1] = "select"; return selected_mob end,
        step = function(_, _, mob)
            assert(mob == selected_mob, "selected mob must reach combat.step")
            calls[#calls + 1] = "combat"
            return combat_result, combat_reason
        end,
    },
    ["lib.sustain"] = {step = function()
        calls[#calls + 1] = "sustain"
        return sustain_handled
    end},
    ["lib.loot"] = {
        select = function() calls[#calls + 1] = "loot_select"; return selected_drop end,
        step = function(_, _, drop)
            assert(drop == selected_drop, "selected drop must reach loot.step")
            calls[#calls + 1] = "loot_step"
            return "done"
        end,
    },
    defaults = {},
}
local runtime_require = require
local environment = setmetatable({require = function(name)
    return fake_modules[name] or runtime_require(name)
end}, {__index = _G})
local main_chunk = assert(load(rewritten_source, "bot/main.lua", "t", environment))
main_chunk()
local pipeline_context = {
    tick = {time = 10},
    state = {
        bot = {mode = "hunt", config = {}}, graph = {}, graph_generation = 1,
        mover = {}, last_poll = 10, started_at = 1,
    },
    game = {character = {movement = {max_speed = 100, max_jump_height = 50}}},
    scene = {terrain = {status = "available", navigation = {model = {stand_height = 5}}}},
}
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,sustain,select,move,combat,publish")
calls, movement_result = {}, "running"
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,sustain,select,move,publish")
calls, movement_result, selected_mob, selected_drop = {}, "done", nil, {}
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,sustain,select,move,loot_select,loot_step,publish")
calls, sustain_handled = {}, true
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,sustain,publish")

local bot_memory = pipeline_context.state
bot_memory.bot.mode, sustain_handled = "follow", false
bot_memory.path_target = {platform = 1, scene_generation = 1}
follow_action, calls = {kind = "wait", reason = "within_distance"}, {}
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,sustain,follow,stop,publish")
assert(bot_memory.path_target == nil)

follow_action, bot_memory.path_target, calls = {kind = "move", x = 20, y = 2}, {platform = 1, scene_generation = 1}, {}
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,sustain,follow,move,publish")

target_platform, calls = 2, {}
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,sustain,follow,plan,set_path,move,publish")
assert(bot_memory.path_target.platform == 2 and bot_memory.path_target.scene_generation == 1)
calls = {}
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,sustain,follow,move,publish")

bot_memory.bot.mode, bot_memory.bot.target = "follow", "2"
bot_memory.path_target, bot_memory.last_poll = {platform = 2, scene_generation = 1}, 9
pending_commands, calls, mover_stopped = {{id = "switch-hunt", kind = "hunt", _ok = true, source = "host"}}, {}, false
selected_mob, selected_drop, movement_result = nil, nil, "running"
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,poll,stop,event,event,sustain,select,move,loot_select,publish")
assert(bot_memory.bot.mode == "hunt" and bot_memory.bot.target == nil)
assert(bot_memory.path_target == nil and mover_stopped)

bot_memory.bot.mode, bot_memory.bot.target = "hunt", "2"
bot_memory.path_target, bot_memory.last_poll = {platform = 2, scene_generation = 1}, 9
pending_commands, calls, mover_stopped = {{id = "switch-follow", kind = "follow", target = "Other", _ok = true, source = "host"}}, {}, false
follow_action, target_platform, movement_result = {kind = "move", x = 20, y = 2}, 2, "done"
environment.__test_main(pipeline_context)
assert(table.concat(calls, ",") == "observe,poll,stop,event,event,sustain,follow,plan,set_path,move,publish")
assert(bot_memory.bot.mode == "follow" and bot_memory.bot.target == "Other")
assert(bot_memory.path_target.platform == 2 and not mover_stopped)

io.open = saved_open
os.execute, os.rename, os.remove = saved_execute, saved_rename, saved_remove
print("bot io/state/world tests ok")
