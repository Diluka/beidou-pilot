local defaults = require("defaults")
local M = {}
local config

local function read_config(root)
    if config then return config end
    config = {}
    for key, value in pairs(defaults) do config[key] = value end

    local file = io.open(root .. "/config.conf", "r")
    if not file then return config end
    for line in file:lines() do
        local key, value = line:match("^([%w_]+)=(.*)$")
        if key ~= nil and defaults[key] ~= nil then
            local default = defaults[key]
            if type(default) == "string" then
                config[key] = value
            elseif type(default) == "number" then
                local parsed = tonumber(value)
                if parsed ~= nil then config[key] = parsed end
            end
        end
    end
    file:close()
    return config
end

local function project_entity(entity, fields)
    local projected = {}
    for output, inputs in pairs(fields) do
        for _, input in ipairs(inputs) do
            local value = entity[input]
            if value ~= nil then
                projected[output] = value
                break
            end
        end
    end
    return projected
end

function M.observe(ctx)
    local game = ctx.game
    local observed_world = game and game.world
    local root = ctx.state and ctx.state.bot_root or "/work/bot"
    local settings = read_config(root)
    local world = {
        ready = observed_world and observed_world.ready,
        map_id = observed_world and observed_world.map_id,
        scene_generation = observed_world and observed_world.scene_generation,
        now = ctx.tick and ctx.tick.time,
    }

    local source_character = game and game.character
    if source_character then
        world.character = project_entity(source_character, {
            x = {"x"}, y = {"y"}, hp = {"hp"}, max_hp = {"max_hp"},
            mp = {"mp"}, max_mp = {"max_mp"}, level = {"level"}, job = {"job"},
            action_idle = {"action_idle"}, on_ground = {"on_ground"},
        })
    end

    local scene = game and game.scene
    local players = scene and scene.players
    if type(players) == "table" then
        local character_id = settings.owner_character_id ~= 0 and settings.owner_character_id or nil
        local name = settings.owner_name ~= "" and settings.owner_name or nil
        local target = ctx.state and ctx.state.bot and ctx.state.bot.target
        if target and not require("lib.target").selector(target) then
            local target_id = tonumber(target)
            if target_id then
                character_id, name = target_id, nil
            else
                name, character_id = target, nil
            end
        end

        local owner
        if character_id then
            for _, player in ipairs(players) do
                if (player.character_id or player.id) == character_id then
                    owner = player
                    break
                end
            end
        end
        if not owner and name then
            for _, player in ipairs(players) do
                if player.name == name then
                    owner = player
                    break
                end
            end
        end

        if owner then
            world.owner = project_entity(owner, {
                name = {"name"}, character_id = {"character_id", "id"},
                x = {"x"}, y = {"y"},
            })
            world.owner.present = true
            if source_character and source_character.x ~= nil and source_character.y ~= nil
                and owner.x ~= nil and owner.y ~= nil then
                local dx, dy = source_character.x - owner.x, source_character.y - owner.y
                world.owner.distance = math.sqrt(dx * dx + dy * dy)
            end
        elseif (name or character_id) and scene.players_complete == true then
            world.owner = {present = false}
        end
    end

    local monsters = scene and scene.monsters
    if type(monsters) == "table" then
        world.mobs = {}
        for _, monster in ipairs(monsters) do
            local mob = project_entity(monster, {
                object_id = {"object_id", "id"}, template_id = {"template_id", "monster_id"},
                x = {"x"}, y = {"y"}, active = {"active"},
            })
            if monster.hp ~= nil and monster.max_hp ~= nil and monster.max_hp > 0 then
                mob.hp_percent = monster.hp * 100 / monster.max_hp
            elseif monster.hp_percent ~= nil then
                mob.hp_percent = monster.hp_percent
            end
            if mob.active == nil and monster.hp ~= nil then mob.active = monster.hp > 0 end
            world.mobs[#world.mobs + 1] = mob
        end
    end

    local drops = scene and scene.drops
    if type(drops) == "table" then
        world.drops = {}
        for _, drop in ipairs(drops) do
            world.drops[#world.drops + 1] = project_entity(drop, {
                object_id = {"object_id", "id"}, item_id = {"item_id"},
                x = {"x"}, y = {"y"}, landed = {"landed"},
            })
        end
    end

    local inventory = game and game.inventory
    local items = inventory and (inventory.items or inventory)
    if type(items) == "table" then
        world.inventory = {}
        for _, item in ipairs(items) do
            world.inventory[#world.inventory + 1] = project_entity(item, {
                item_id = {"item_id", "id"}, quantity = {"quantity", "count"},
            })
        end
    end
    return world
end

return M
