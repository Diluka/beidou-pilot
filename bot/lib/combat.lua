local move = require("lib.move")
local io_module = require("lib.io")
local M = {}
local abandoned, selection_scope = {}, nil
local active_target, active_player, active_mover, active_state

local function release_active()
    if active_mover and active_mover.status == "running" then
        move.stop(active_mover)
    elseif active_player then
        active_player.move(nil)
        active_player.skill(nil)
    end
    if active_state then active_state.combat = nil end
    active_target, active_player, active_mover, active_state = nil, nil, nil, nil
end

local function distance(left, right)
    local dx, dy = left.x - right.x, left.y - right.y
    return math.sqrt(dx * dx + dy * dy)
end

local function target_key(mob)
    return mob.object_id ~= nil and mob.object_id or mob
end

local function is_excluded(exclude, object_id)
    if type(exclude) ~= "table" then return false end
    if exclude[object_id] == true then return true end
    for _, excluded_id in ipairs(exclude) do
        if excluded_id == object_id then return true end
    end
    return false
end

function M.select(world, options)
    options = options or {}
    local character = world and world.character
    if not character or type(character.x) ~= "number" or type(character.y) ~= "number"
        or character.platform == nil then
        release_active()
        return nil
    end

    local scope = tostring(world.map_id) .. ":" .. tostring(world.scene_generation)
    if selection_scope ~= scope then
        release_active()
        abandoned, selection_scope = {}, scope
    end

    local owner = world.owner
    local origin, limit
    if owner and owner.present ~= false then
        if type(owner.x) ~= "number" or type(owner.y) ~= "number" then
            release_active()
            return nil
        end
        origin, limit = owner, 300
    else
        origin, limit = character, 200
    end

    local candidates = {}
    for _, mob in ipairs(world.mobs or {}) do
        local key = target_key(mob)
        if mob.active == true and mob.template_id ~= nil and mob.template_id ~= ""
            and mob.platform == character.platform and not is_excluded(options.exclude, mob.object_id)
            and not abandoned[key] and type(mob.x) == "number" and type(mob.y) == "number" then
            local range = distance(origin, mob)
            if range <= limit then
                candidates[#candidates + 1] = {mob = mob, distance = range}
            end
        end
    end
    table.sort(candidates, function(left, right)
        if left.distance ~= right.distance then return left.distance < right.distance end
        local left_id, right_id = left.mob.object_id, right.mob.object_id
        if type(left_id) == "number" and type(right_id) == "number" then return left_id < right_id end
        return tostring(left_id) < tostring(right_id)
    end)
    local selected = candidates[1] and candidates[1].mob or nil
    if active_target ~= nil and (not selected or target_key(selected) ~= active_target) then release_active() end
    return selected
end

function M.step(ctx, world, mob, mover)
    local player = ctx and ctx.game and ctx.game.player
    local character = world and world.character
    local now = ctx and ctx.tick and ctx.tick.time or world and world.now
    if not player or type(now) ~= "number" or not character
        or type(character.x) ~= "number" or type(character.y) ~= "number" then
        if player then player.move(nil); player.skill(nil) end
        release_active()
        if ctx and ctx.state then ctx.state.combat = nil end
        return "failed", "character_unavailable"
    end
    if not mob then
        release_active()
        player.move(nil); player.skill(nil)
        if ctx.state then ctx.state.combat = nil end
        return "failed", "target_unavailable"
    end

    local key = target_key(mob)
    local current
    if type(world.mobs) == "table" then
        for _, observed in ipairs(world.mobs) do
            if target_key(observed) == key then current = observed; break end
        end
        if not current then
            if active_target == key then release_active() else player.move(nil); player.skill(nil) end
            if ctx.state then ctx.state.combat = nil end
            return "done", "killed"
        end
    else
        current = mob
    end
    if current.active == false or current.hp_percent ~= nil and current.hp_percent <= 0
        or current.hp ~= nil and current.hp <= 0 then
        if active_target == key then release_active() else player.move(nil); player.skill(nil) end
        if ctx.state then ctx.state.combat = nil end
        return "done", "killed"
    end
    mob = current
    local state = ctx.state or {}
    if not ctx.state then ctx.state = state end
    if active_target ~= nil and active_target ~= key then release_active() end
    local combat = state.combat
    if not combat or combat.target_key ~= key then
        if combat then player.move(nil); player.skill(nil) end
        combat = {
            target_key = key, started_at = now, progress_at = now,
            progress_hp = mob.hp_percent, repositioned = false,
        }
        state.combat = combat
    end
    active_target, active_player, active_mover, active_state = key, player, mover, state

    local function finish(status, reason, remember_abandoned)
        if active_target == key then release_active() else player.move(nil); player.skill(nil) end
        if remember_abandoned then abandoned[key] = true end
        state.combat = nil
        return status, reason
    end

    if character.platform == nil or mob.platform == nil or mob.platform ~= character.platform then
        return finish("failed", "target_platform_unreachable", true)
    end
    if world.owner and world.owner.present ~= false and type(world.owner.x) == "number"
        and type(world.owner.y) == "number" and distance(world.owner, mob) > 400 then
        return finish("failed", "leash_exceeded", true)
    end
    if now - combat.started_at >= 15 then return finish("failed", "timeout", true) end

    local target_distance = distance(character, mob)
    if mob.hp_percent ~= nil and combat.progress_hp ~= nil and mob.hp_percent < combat.progress_hp then
        combat.progress_hp, combat.progress_at, combat.repositioned = mob.hp_percent, now, false
    end
    if now - combat.progress_at >= 3 then
        if not combat.repositioned then
            if not mover or type(mover) ~= "table" then
                return finish("failed", "mover_unavailable", true)
            end
            local destination = mob.x + (character.x <= mob.x and 30 or -30)
            local set, set_error = move.set_path(mover, {{
                kind = "walk", from = character.platform, to = character.platform,
                x = character.x, destination = destination, rise = 0,
            }})
            if not set then return finish("failed", set_error or "no_path", true) end
            combat.repositioned, combat.progress_at = true, now
            combat.moving = "reposition"
            local status, reason = move.step(mover, ctx, world)
            if status == "failed" then return finish("failed", reason or "move_failed", true) end
            if status == "done" then combat.moving = nil end
            return "running", "reposition"
        end
        io_module.event(ctx, "combat_no_progress", {object_id = mob.object_id, template_id = mob.template_id})
        return finish("failed", "no_progress", true)
    end

    if target_distance > 60 then
        if not mover or type(mover) ~= "table" then return finish("failed", "mover_unavailable", true) end
        local move_target = mob.object_id
        if combat.moving ~= "approach" or combat.move_target ~= move_target or mover.status ~= "running" then
            local set, set_error = move.set_path(mover, {{
                kind = "walk", from = character.platform, to = character.platform,
                x = character.x, destination = mob.x, rise = 0,
            }})
            if not set then return finish("failed", set_error or "no_path", true) end
            combat.moving, combat.move_target = "approach", move_target
        end
        local status, reason = move.step(mover, ctx, world)
        if status == "failed" then return finish("failed", reason or "move_failed", true) end
        if status == "done" then combat.moving = nil end
        return "running", reason or "approaching"
    end

    if combat.moving == "approach" or combat.moving == "reposition" then
        if mover and mover.status == "running" then move.stop(mover) end
        combat.moving, combat.move_target, combat.facing_direction = nil, nil, nil
        player.skill(nil)
    end

    local direction = mob.x >= character.x and "right" or "left"
    if combat.facing_direction ~= direction then
        player.move(direction)
        combat.facing_direction = direction
        return "running", "facing"
    end
    player.move(nil)

    local skill_id = tonumber((world.config or state.bot and state.bot.config or {}).attack_skill_id) or 0
    local action = skill_id > 0 and character.mp ~= nil and character.mp >= 10 and "skill" or "attack"
    if combat.action ~= action or combat.skill_id ~= (action == "skill" and skill_id or nil) then
        if action == "skill" then player.skill(skill_id) else player.attack() end
        combat.action, combat.skill_id = action, action == "skill" and skill_id or nil
    end
    return "running", "attacking"
end

return M
