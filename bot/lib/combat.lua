local move = require("lib.move")
local terrain = require("lib.terrain")
local io_module = require("lib.io")
local M = {}
local abandoned, selection_scope = {}, nil
local low_events = {}

local function emit_low(ctx, name, detail)
    local now = (ctx.tick and ctx.tick.time) or 0
    if low_events[name] and now - low_events[name] < 5 then return end
    low_events[name] = now
    io_module.event(ctx, name, detail)
end

local function count_item(ctx, item_id)
    local inventory = ctx.game and ctx.game.inventory
    if type(inventory) ~= "table" then return nil end
    local items = inventory.items
    if type(items) ~= "table" then
        if type(inventory[1]) == "table" or #inventory > 0 then items = inventory else return nil end
    end
    local total = 0
    for _, item in ipairs(items) do
        if type(item) == "table" and tonumber(item.item_id) == item_id then
            total = total + (tonumber(item.quantity) or 0)
        end
    end
    return total
end
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

local function ranged_range(config, observed)
    local skills = observed and observed.skills
    local level
    if type(skills) == "table" and observed.skills_complete ~= false then
        local record = skills[tostring(tonumber(config.ranged_skill_id) or 3000002)]
        level = type(record) == "table" and tonumber(record.level) or 0
    else
        level = tonumber(config.ranged_skill_level) or 0
    end
    return (tonumber(config.attack_range) or 110) + level * (tonumber(config.ranged_skill_bonus_per_level) or 15)
end

local function cross_range(character, mob, graph, config, observed)
    local source = graph and graph.platforms and graph.platforms[character.platform]
    local target = graph and graph.platforms and graph.platforms[mob.platform]
    if not source or not target or not graph.walls or not character.on_ground then return "geometry_unavailable" end
    local margin = math.min(40, (tonumber(config.min_range) or 60) / 2)
    if source.right - source.left < (tonumber(config.min_range) or 60) + 60
        or character.x - source.left < margin or source.right - character.x < margin
        or mob.x < target.left or mob.x > target.right then return "platform_boundary" end
    local dx = math.abs(mob.x - character.x)
    if dx < (tonumber(config.min_range) or 60) then return "too_close" end
    if dx > ranged_range(config, observed) then return "out_of_range" end
    if math.abs(mob.y - character.y) > 40 then return "height_difference" end
    local left, right = math.min(character.x, mob.x), math.max(character.x, mob.x)
    for i = 1, #graph.walls, 3 do
        local x, top, bottom = graph.walls[i], graph.walls[i + 1], graph.walls[i + 2]
        if top <= math.max(character.y, mob.y) and bottom >= math.min(character.y, mob.y) - 40 then
            if math.abs(x - character.x) < margin or x >= left and x <= right then return "wall" end
        end
    end
    return nil
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

    local ranged_context
    if options.hunt and options.config and options.graph and options.context and options.context.game
        and (options.config.attack_mode or "melee") ~= "melee" then
        ranged_context = options.context
        local best, best_dx, blocked_reason
        for _, mob in ipairs(world.mobs or {}) do
            if mob.active == true and mob.template_id ~= nil and mob.template_id ~= ""
                and mob.platform ~= nil and mob.platform ~= character.platform
                and type(mob.x) == "number" and type(mob.y) == "number"
                and not is_excluded(options.exclude, mob.object_id) and not abandoned[target_key(mob)]
                and not (mob.hp_percent ~= nil and mob.hp_percent <= 0)
                and not (mob.hp ~= nil and mob.hp <= 0) then
                local reason = cross_range(character, mob, options.graph, options.config, options.context.game.character)
                if reason then blocked_reason = blocked_reason or reason else
                    local dx = math.abs(character.x - mob.x)
                    if not best or dx < best_dx or dx == best_dx and tostring(mob.object_id) < tostring(best.object_id) then
                        best, best_dx = mob, dx
                    end
                end
            end
        end
        if best then
            if active_target ~= nil and active_target ~= target_key(best) then release_active() end
            emit_low(options.context, "combat/ranged_target", {object_id = best.object_id,
                platform = best.platform, horizontal_distance = best_dx, cross_platform = true})
            return best
        end
        emit_low(options.context, "combat/range_blocked", {reason = blocked_reason or "no_target"})
        -- Other-platform mobs that cannot be hit are not pursuit targets.
        options = {hunt = true, platform_only = true, exclude = options.exclude}
    end

    local owner = world.owner
    local origin, limit
    if not options.hunt and owner and owner.present ~= false then
        if type(owner.x) ~= "number" or type(owner.y) ~= "number" then
            release_active()
            return nil
        end
        origin, limit = owner, 300
    else
        origin, limit = character, options.hunt and math.huge or 200
    end

    if active_target ~= nil then
        local locked
        for _, mob in ipairs(world.mobs or {}) do
            if target_key(mob) == active_target then locked = mob; break end
        end
        local leash_origin = owner and owner.present ~= false and owner or character
        if locked and locked.active == true and locked.template_id ~= nil and locked.template_id ~= ""
            and locked.platform ~= nil and (not options.platform_only or locked.platform == character.platform)
            and not is_excluded(options.exclude, locked.object_id)
            and not abandoned[active_target] and type(locked.x) == "number" and type(locked.y) == "number"
            and not (locked.hp_percent ~= nil and locked.hp_percent <= 0)
            and not (locked.hp ~= nil and locked.hp <= 0)
            and (options.hunt or distance(leash_origin, locked) <= 400) then
            if ranged_context then
                emit_low(ranged_context, "combat/ranged_target", {object_id = locked.object_id, platform = locked.platform,
                    horizontal_distance = math.abs(locked.x - character.x), cross_platform = false})
            end
            return locked
        end
        release_active()
    end

    local candidates = {}
    for _, mob in ipairs(world.mobs or {}) do
        local key = target_key(mob)
        if mob.active == true and mob.template_id ~= nil and mob.template_id ~= ""
            and mob.platform ~= nil and (not options.platform_only or mob.platform == character.platform)
            and not is_excluded(options.exclude, mob.object_id)
            and not abandoned[key] and type(mob.x) == "number" and type(mob.y) == "number"
            and not (mob.hp_percent ~= nil and mob.hp_percent <= 0)
            and not (mob.hp ~= nil and mob.hp <= 0) then
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
    if selected and ranged_context then
        emit_low(ranged_context, "combat/ranged_target", {object_id = selected.object_id, platform = selected.platform,
            horizontal_distance = math.abs(selected.x - character.x), cross_platform = false})
    end
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

    if character.platform == nil or mob.platform == nil then
        return finish("failed", "target_platform_unreachable", true)
    end
    if not (state.bot and state.bot.mode == "hunt") and world.owner and world.owner.present ~= false
        and type(world.owner.x) == "number" and type(world.owner.y) == "number"
        and distance(world.owner, mob) > 400 then
        return finish("failed", "leash_exceeded", true)
    end
    if now - combat.started_at >= 15 then return finish("failed", "timeout", true) end
    local config = world.config or state.bot and state.bot.config or {}
    local attack_mode = config.attack_mode or "melee"
    local min_range = tonumber(config.min_range) or 60
    local graph = state.graph or mover and mover.graph
    local platform = graph and graph.platforms and graph.platforms[mob.platform]
    if attack_mode ~= "melee" and state.bot and state.bot.mode == "hunt" and platform
        and mob.platform == character.platform and platform.right - platform.left < min_range + 60 then
        return finish("failed", "narrow_platform", true)
    end
    if attack_mode ~= "melee" and mob.platform == character.platform
        and not (combat.moving == "cross_platform" and mover and mover.status == "running")
        and distance(character, mob) < min_range then
        player.skill(nil)
        combat.action, combat.skill_id, combat.facing_direction = nil, nil, nil
        local direction = mob.x > character.x and "left" or "right"
        local available = 0
        local source = graph and graph.platforms and graph.platforms[character.platform]
        if source then
            available = direction == "left" and character.x - source.left or source.right - character.x
            for i = 1, #(graph.walls or {}), 3 do
                local x, top, bottom = graph.walls[i], graph.walls[i + 1], graph.walls[i + 2]
                if top <= character.y and bottom >= character.y - (graph.model and graph.model.stand_height or 40)
                    and (direction == "left" and x <= character.x or direction == "right" and x >= character.x) then
                    available = math.min(available, math.abs(character.x - x))
                end
            end
        end
        local threshold = math.min(40, min_range / 2)
        if not source or available < threshold then
            io_module.event(ctx, "combat/retreat_blocked", {reason = source and "insufficient_space" or "platform_unavailable",
                platform = character.platform, retreat_distance = available, target_distance = distance(character, mob)})
            return finish("failed", "retreat_blocked", true)
        end
        if not mover then return finish("failed", "mover_unavailable", true) end
        if combat.moving ~= "retreat" or mover.status ~= "running" or combat.retreat_direction ~= direction then
            local destination = character.x + (direction == "left" and -threshold or threshold)
            local ok, err = move.set_path(mover, {{kind = "walk", from = character.platform, to = character.platform,
                x = character.x, destination = destination, rise = 0}})
            if not ok then return finish("failed", err or "no_path", true) end
            combat.moving, combat.retreat_direction = "retreat", direction
        end
        local status, reason = move.step(mover, ctx, world)
        if status == "failed" then
            io_module.event(ctx, "combat/retreat_blocked", {reason = reason or "move_failed", platform = character.platform,
                retreat_distance = available, target_distance = distance(character, mob)})
            return finish("failed", "retreat_blocked", true)
        end
        return "running", "retreating"
    end
    local observed = ctx.game.character or {}
    local ranged_cross = attack_mode ~= "melee" and state.bot and state.bot.mode == "hunt"
        and mob.platform ~= character.platform
    if ranged_cross then
        local reason = cross_range(character, mob, graph, config, observed)
        if reason then
            emit_low(ctx, "combat/range_blocked", {reason = reason, object_id = mob.object_id, platform = mob.platform})
            return finish("failed", "range_blocked", false)
        end
        if mover and mover.status == "running" then move.stop(mover) end
        combat.moving = nil
    end
    if observed.attacking or not observed.action_idle then
        player.move(nil)
        return "running", "action_busy"
    end
    if combat.moving == "cross_platform" and combat.goal_platform == mob.platform
        and mover and mover.status == "running" then
        local status, reason = move.step(mover, ctx, world)
        if status == "failed" then return finish("failed", reason or "move_failed", true) end
        if status == "running" then return "running", reason or "approaching" end
        combat.moving, combat.progress_at = nil, now
    end
    if mob.platform ~= character.platform and not ranged_cross then
        if not mover or not state.graph then return finish("failed", "no_path", true) end
        if combat.moving ~= "cross_platform" or combat.goal_platform ~= mob.platform or mover.status ~= "running" then
            local movement = observed.movement or {}
            local model = type(movement.model) == "table" and movement.model or movement.defaults or movement.model_defaults or {}
            local edges, err = terrain.plan(state.graph, character.platform, mob.platform, {
                speed = movement.max_speed or model.max_speed,
                max_jump_height = movement.max_jump_height or model.max_jump_height,
                blocked = state.blocked or {},
            })
            if not edges or #edges == 0 then return finish("failed", err or "no_path", true) end
            local set, set_error = move.set_path(mover, edges)
            if not set then return finish("failed", set_error or "no_path", true) end
            combat.moving, combat.goal_platform = "cross_platform", mob.platform
        end
        local status, reason = move.step(mover, ctx, world)
        if status == "failed" then return finish("failed", reason or "move_failed", true) end
        return "running", reason or "approaching"
    end
    if combat.moving == "cross_platform" then
        if mover and mover.status == "running" then move.stop(mover) end
        combat.moving, combat.progress_at = nil, now
    end
    local target_distance = ranged_cross and math.abs(character.x - mob.x) or distance(character, mob)
    -- 射程与武器/技能挂钩：弓弩基础射程 + 已学「远程箭」加成。
    -- 远程箭（弓箭手 1 转）= 3000002：Data/Skill/300.img/skill/3000002 最高 8 级，
    -- range 依次为 15/30/…/120，即每级 +15。弓弩基础射程 110 来自真机距离预判，
    -- 原版客户端公式待核实。技能列表不可读时用 ranged_skill_level 兜底。
    local attack_range = tonumber(config.attack_range) or 110
    if attack_mode ~= "melee" then attack_range = ranged_range(config, observed) end
    if combat.moving == "retreat" then
        if mover and mover.status == "running" then move.stop(mover) end
        combat.moving, combat.progress_at = nil, now
    end
    if mob.hp_percent ~= nil and combat.progress_hp ~= nil and mob.hp_percent < combat.progress_hp then
        combat.progress_hp, combat.progress_at, combat.repositioned = mob.hp_percent, now, false
    end
    if now - combat.progress_at >= 3 then
        if not combat.repositioned and not ranged_cross then
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

    local approach_range = attack_mode == "melee" and 60 or attack_range
    if target_distance > approach_range then
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

    local skill_id = tonumber(config.attack_skill_id) or 0
    local mp_cost = tonumber(config.skill_mp_cost) or 10
    local can_skill = skill_id > 0 and character.mp ~= nil and character.mp >= mp_cost
    if attack_mode ~= "melee" then
        if attack_mode == "skill" and character.max_mp and character.max_mp > 0
            and (character.mp or 0) / character.max_mp < 0.2 then
            emit_low(ctx, "combat/mp_low", {mp = character.mp, max_mp = character.max_mp})
        end
        local ammo_id = tonumber(config.ammo_item_id) or 2060000
        local ammo_low = tonumber(config.ammo_low) or 50
        local ammo_count = count_item(ctx, ammo_id)
        if ammo_count ~= nil and ammo_count < ammo_low then
            emit_low(ctx, "combat/ammo_low", {item_id = ammo_id, count = ammo_count, low = ammo_low})
        end
    end
    local action = "attack"
    if can_skill and (attack_mode == "skill" or attack_mode == "melee") then action = "skill" end
    if combat.action ~= action or combat.skill_id ~= (action == "skill" and skill_id or nil) then
        if action == "skill" then player.skill(skill_id) else player.attack() end
        combat.action, combat.skill_id = action, action == "skill" and skill_id or nil
    end
    return "running", "attacking"
end

return M
