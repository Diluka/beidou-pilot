local io_module = require("lib.io")
local M = {}

function M.step(ctx, world)
    local character = world.character
    if not character or character.hp == nil then
        return true, "observation_unavailable"
    end
    local state = ctx.state
    state.sustain = state.sustain or {}
    local memory = state.sustain
    local player = ctx.game.player
    if character.hp == 0 then
        if not memory.revive_at then
            memory.revive_at = world.now
            player.revive()
            return true, "reviving"
        end
        if world.now - memory.revive_at >= 10 then
            if not memory.revive_reported then
                io_module.event(ctx, "revive", {reason = "revive_unknown"})
                memory.revive_reported = true
            end
            return true, "revive_unknown"
        end
        return true, "reviving"
    end
    if memory.revive_at and not memory.revive_succeeded then
        io_module.event(ctx, "revive", {reason = "revived"})
        memory.revive_succeeded = true
    end

    if character.max_hp == nil or character.max_hp <= 0 or character.mp == nil
        or character.max_mp == nil or character.max_mp <= 0 or not world.inventory then
        player.skill(nil)
        return true, "observation_unavailable"
    end

    if not memory.config then
        memory.config = {hp_item = 0, mp_item = 0}
        local file = io.open((state.bot_root or "/work/bot") .. "/config.conf", "r")
        if file then
            for line in file:lines() do
                local key, value = line:match("^([%w_]+)=(.*)$")
                if key == "hp_item" or key == "mp_item" then
                    memory.config[key] = tonumber(value) or 0
                end
            end
            file:close()
        end
    end
    local hp, mp = character.hp / character.max_hp, character.mp / character.max_mp
    if hp < 0.60 then memory.need_hp = true elseif hp > 0.65 then memory.need_hp = false end
    if mp < 0.30 then memory.need_mp = true elseif mp > 0.35 then memory.need_mp = false end
    local kind = memory.need_hp and "hp" or memory.need_mp and "mp"
    if memory.potion and memory.potion ~= kind then
        player.skill(nil)
        memory.potion = nil
    end
    if kind then
        local id = memory.config[kind .. "_item"]
        for _, item in ipairs(world.inventory) do
            if id > 0 and id <= 2147483647 and id % 1 == 0 and item.item_id == id
                and type(item.quantity) == "number" and item.quantity > 0 then
                memory.potion = kind
                player.use_item(id)
                return true, kind .. "_potion"
            end
        end
        player.skill(nil)
        memory.potion = nil
        -- 无药不是“被接管”：返回 false 让 idle/hunt/travel/loot 继续；
        -- 事件按 30 秒限频，避免每 tick 刷屏。
        local now = world.now or 0
        if not memory.no_potion_at or now - memory.no_potion_at >= 30 then
            memory.no_potion_at = now
            io_module.event(ctx, "sustain/no_potion", {kind = kind, item_id = id})
        end
        return false, nil
    end
    return false, nil
end

return M
