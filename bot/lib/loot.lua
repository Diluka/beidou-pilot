local move = require("lib.move")
local terrain = require("lib.terrain")
local M = {}

local function distance(left, right)
    if not left or type(left.x) ~= "number" or type(left.y) ~= "number"
        or type(right.x) ~= "number" or type(right.y) ~= "number" then
        return nil
    end
    local dx, dy = left.x - right.x, left.y - right.y
    return math.sqrt(dx * dx + dy * dy)
end

local function owner_is_near(world, owner)
    if not owner or owner.present == false then return false end
    local owner_distance = owner.distance or distance(world.character, owner)
    -- When an owner is present but its distance is unknown, wait rather than risk stealing.
    return owner_distance == nil or owner_distance <= 100
end

local function unsafe(world)
    local character = world and world.character
    if not character or type(character.hp) ~= "number" or type(character.max_hp) ~= "number"
        or character.max_hp <= 0 or character.hp / character.max_hp < 0.4
        or type(world.mobs) ~= "table" then
        return true
    end
    for _, mob in ipairs(world.mobs) do
        local alive = mob.active == true or (mob.active == nil
            and type(mob.hp_percent) == "number" and mob.hp_percent > 0)
        if alive then
            local mob_distance = distance(character, mob)
            if mob_distance == nil or mob_distance <= 80 then return true end
        end
    end
    return false
end

function M.select(world, options)
    options = type(options) == "table" and options or {}
    if unsafe(world) then return nil, "unsafe" end
    if owner_is_near(world, options.owner or world.owner) then return nil, "owner_near" end

    local character = world.character
    local radius = options.radius or options.loot_radius or 150
    if type(radius) ~= "number" or radius < 0 or type(character.platform) ~= "number"
        or type(world.drops) ~= "table" then
        return nil
    end
    local candidates = {}
    for _, drop in ipairs(world.drops) do
        if drop.landed == true and drop.platform ~= nil
            and (drop.platform == character.platform or options.graph)
            and drop.object_id ~= nil and not (options.abandoned and options.abandoned[drop.object_id]) then
            local drop_distance = distance(character, drop)
            if drop_distance and (drop_distance <= radius or options.graph) then
                local priority = drop.platform == character.platform and 1
                    or options.route_platforms and options.route_platforms[drop.platform] and 2 or 3
                candidates[#candidates + 1] = {drop = drop, distance = drop_distance, priority = priority}
            end
        end
    end
    table.sort(candidates, function(left, right)
        if left.priority ~= right.priority then return left.priority < right.priority end
        if left.distance ~= right.distance then return left.distance < right.distance end
        if type(left.drop.object_id) == type(right.drop.object_id) then
            return left.drop.object_id < right.drop.object_id
        end
        return tostring(left.drop.object_id) < tostring(right.drop.object_id)
    end)
    return candidates[1] and candidates[1].drop or nil
end

local function inventory_quantity(world, item_id)
    if item_id == nil or type(world.inventory) ~= "table" then return nil end
    local quantity = 0
    for _, item in ipairs(world.inventory) do
        if item.item_id == item_id and type(item.quantity) == "number" then
            quantity = quantity + item.quantity
        end
    end
    return quantity
end

local function drop_is_present(world, object_id)
    if type(world.drops) ~= "table" then return nil end
    for _, current in ipairs(world.drops) do
        if current.object_id == object_id then return true end
    end
    return false
end

local function clear_input(ctx, mover)
    if mover and mover.status == "running" then move.stop(mover) end
    if ctx and ctx.game and ctx.game.player then
        ctx.game.player.move(nil)
        ctx.game.player.skill(nil)
    end
end

local function fail(ctx, world, drop, mover, state, reason)
    clear_input(ctx, mover)
    mover.loot = nil
    if ctx.state and reason ~= "unsafe" then
        local scope = tostring(world.map_id) .. ":" .. tostring(world.scene_generation)
        if ctx.state.loot_abandoned_scope ~= scope then
            ctx.state.loot_abandoned, ctx.state.loot_abandoned_scope = {}, scope
        end
        ctx.state.loot_abandoned[drop.object_id] = true
    end
    require("lib.io").event(ctx, "loot", {
        object_id = drop.object_id, item_id = drop.item_id, reason = reason,
        attempts = state.attempt + 1,
    })
    return "failed", reason
end

function M.step(ctx, world, drop, mover)
    local player = ctx and ctx.game and ctx.game.player
    local character = world and world.character
    if not player or not character or not mover or type(drop) ~= "table" then
        if player then player.skill(nil) end
        return "failed", "observation_unavailable"
    end
    if unsafe(world) then
        local state = mover.loot or {attempt = 0}
        return fail(ctx, world, drop, mover, state, "unsafe")
    end
    if owner_is_near(world, world.owner) then
        if mover.loot then mover.loot.started_at = ctx.tick.time end
        clear_input(ctx, mover)
        return "running", "owner_near"
    end
    if type(character.platform) ~= "number" or type(drop.platform) ~= "number"
        or (character.platform ~= drop.platform and not (ctx.state and ctx.state.graph)) then
        return fail(ctx, world, drop, mover, mover.loot or {attempt = 0}, "drop_platform_unreachable")
    end

    local now = ctx.tick and ctx.tick.time or world.now
    local state = mover.loot
    if not state or state.object_id ~= drop.object_id then
        state = {
            object_id = drop.object_id, item_id = drop.item_id,
            attempt = 0, started_at = now,
            baseline_quantity = inventory_quantity(world, drop.item_id),
        }
        mover.loot = state
    end

    local quantity = inventory_quantity(world, state.item_id)
    if (quantity ~= nil and state.baseline_quantity ~= nil and quantity > state.baseline_quantity)
        or (state.pickup_requested and drop_is_present(world, state.object_id) == false) then
        clear_input(ctx, mover)
        mover.loot = nil
        return "done", "picked"
    end

    if character.platform ~= drop.platform then
        if state.cross_platform and mover.status == "done" then
            return fail(ctx, world, drop, mover, state, "landing_mismatch")
        end
        if not state.cross_platform then
            local path, reason = terrain.plan(ctx.state.graph, character.platform, drop.platform,
                {blocked = ctx.state.blocked or {}})
            if not path or #path == 0 then
                return fail(ctx, world, drop, mover, state, reason or "no_path")
            end
            local ok, set_reason = move.set_path(mover, path)
            if not ok then return fail(ctx, world, drop, mover, state, set_reason or "move_failed") end
            state.cross_platform = true
            require("lib.io").event(ctx, "loot/navigate", {object_id = drop.object_id,
                from = character.platform, to = drop.platform})
        end
        local status, reason = move.step(mover, ctx, world)
        if status == "failed" then return fail(ctx, world, drop, mover, state, reason or "move_failed") end
        return "running", "cross_platform"
    end
    if state.cross_platform then
        if mover.status == "running" then move.stop(mover) end
        state.cross_platform, state.started_at = nil, now
    end
    local drop_distance = distance(character, drop)

    local function retry(reason)
        clear_input(ctx, mover)
        if state.attempt == 0 then
            state.attempt = 1
            state.started_at = now
            return "running", "retry"
        end
        return fail(ctx, world, drop, mover, state, reason)
    end

    if type(now) ~= "number" or type(state.started_at) ~= "number" or now - state.started_at >= 5 then
        return retry("timeout")
    end
    if drop_distance == nil then return retry("drop_position_unavailable") end

    if drop_distance > 25 then
        if state.moving_to ~= drop.x or state.moving_platform ~= character.platform or mover.status ~= "running" then
            local ok, reason = move.set_path(mover, {{
                kind = "walk", from = character.platform, to = character.platform,
                x = character.x, destination = drop.x, rise = 0,
            }})
            if not ok then return retry(reason or "move_failed") end
            state.moving_to, state.moving_platform = drop.x, character.platform
        end
        local status, reason = move.step(mover, ctx, world)
        if status == "failed" then return retry(reason or "move_failed") end
        if status == "running" then return "running", "moving" end
        if distance(character, drop) > 25 then
            state.moving_to = nil
            return "running", "moving"
        end
    elseif mover.status == "running" then
        move.stop(mover)
    end

    local ok, reason = player.pickup()
    if not ok then return retry(reason or "pickup_rejected") end
    state.pickup_requested = true
    return "running", "picking"
end

return M
