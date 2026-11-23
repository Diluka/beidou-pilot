local io_module = require("lib.io")
local state_module = require("lib.state")
local world_module = require("lib.world")
local terrain = require("lib.terrain")
local move = require("lib.move")
local follow = require("lib.follow")
local combat = require("lib.combat")
local sustain = require("lib.sustain")
local loot = require("lib.loot")
local defaults = require("defaults")

local function main(context)
    local memory = context.state
    if not memory.bot then
        memory.bot = state_module.new()
        memory.bot.player = context.game.player
        memory.bot_root = memory.bot_root or "/work/bot"
        memory.started_at = context.tick.time
        memory.last_poll = nil
        memory.force_publish = true
        io_module.event(context, "mode", {mode = "recover", reason = memory.bot.last_error})
    end

    local bot = memory.bot
    local now = context.tick.time
    local world, observe_error = world_module.observe(context)
    if not world then
        bot.last_error = observe_error or "world_unavailable"
        io_module.event(context, "error", {reason = bot.last_error})
        memory.force_publish = true
        io_module.publish(context, {character = {}}, now)
        return
    end

    if memory.last_poll == nil or now - memory.last_poll >= 0.5 then
        memory.last_poll = now
        local commands, poll_error = io_module.poll(context, now)
        if not commands then
            bot.last_error = poll_error or "poll_failed"
            io_module.event(context, "error", {reason = bot.last_error})
        else
            for _, command in ipairs(commands) do
                local previous_mode, previous_target = bot.mode, bot.target
                if command._ok then
                    local applied, apply_error = state_module.apply(bot, command)
                    command._ok = applied
                    command._reason = apply_error
                    if not applied then
                        bot.last_error = apply_error
                    end
                end
                if command._ok then
                    bot.last_command = command.kind
                    bot.last_error = nil
                end
                if command._ok and (command.kind == "stop" or command.kind == "stay"
                    or bot.mode ~= previous_mode or bot.target ~= previous_target) then
                    if memory.mover then move.stop(memory.mover) end
                    memory.path_target = nil
                end
                local event_ok, event_error = io_module.event(context, "command/" .. tostring(command.kind or "invalid"), {
                    id = command.id, kind = command.kind, target = command.target,
                    source = command.source, ok = command._ok, reason = command._reason,
                })
                if not event_ok then bot.last_error = event_error end
                if bot.mode ~= previous_mode then
                    io_module.event(context, "mode", {from = previous_mode, mode = bot.mode, reason = command.kind})
                end
                if command.kind == "status" then memory.force_publish = true end
                if not command._skip_receipt then
                    memory.pending_receipts = memory.pending_receipts or {}
                    memory.pending_receipts[#memory.pending_receipts + 1] = command
                end
            end
            if #commands > 0 then memory.force_publish = true end
        end
    end

    local character = world.character or {}
    if character.hp ~= nil and character.hp <= 0 and bot.mode ~= "dead" then
        local previous = bot.mode
        bot.player.stop()
        if memory.mover then move.stop(memory.mover) end
        memory.path_target = nil
        state_module.transition(bot, "dead", "hp_zero")
        io_module.event(context, "mode", {from = previous, mode = "dead", reason = "hp_zero"})
    elseif bot.mode == "dead" and character.hp ~= nil and character.hp > 0 then
        state_module.transition(bot, "recover", "revived")
        io_module.event(context, "mode", {from = "dead", mode = "recover", reason = "revived"})
    end

    local scene = context.scene
    local terrain_scene = scene and scene.terrain
    local generation = world.scene_generation
    if memory.graph_generation ~= generation then
        memory.graph, memory.mover, memory.path_target = nil, nil, nil
        memory.graph_generation, memory.graph_attempt_generation, memory.mover_attempt_generation = nil, nil, nil
    end
    if generation ~= nil and memory.graph_generation ~= generation
        and memory.graph_attempt_generation ~= generation
        and terrain_scene and terrain_scene.status == "available" then
        memory.graph_attempt_generation = generation
        local graph, graph_error = terrain.build(terrain_scene.navigation)
        if graph then
            memory.graph = graph
            memory.graph_generation = generation
        elseif graph_error ~= "not_implemented" then
            bot.last_error = graph_error or "terrain_build_failed"
            io_module.event(context, "error", {reason = bot.last_error})
        end
    end
    if bot.mode == "recover" and world.ready and terrain_scene and terrain_scene.status == "available"
        and memory.graph and memory.graph_generation == generation then
        local previous = bot.mode
        state_module.transition(bot, "idle", "recovered")
        io_module.event(context, "mode", {from = previous, mode = "idle", reason = "terrain_ready"})
    end

    local tolerance = terrain_scene and terrain_scene.navigation and terrain_scene.navigation.model
        and terrain_scene.navigation.model.stand_height
    if memory.graph and world.character then
        local function set_platform(entity)
            if entity and entity.x ~= nil and entity.y ~= nil then
                entity.platform = terrain.platform_at(memory.graph, entity.x, entity.y, tolerance)
            end
        end
        set_platform(world.character)
        set_platform(world.owner)
        for _, mob in ipairs(world.mobs or {}) do set_platform(mob) end
        for _, drop in ipairs(world.drops or {}) do set_platform(drop) end
    end

    local handled, sustain_error = sustain.step(context, world)
    if handled then
        io_module.publish(context, world, now)
        return
    elseif sustain_error and sustain_error ~= "not_implemented" then
        bot.last_error = sustain_error
        io_module.event(context, "error", {reason = sustain_error})
    end

    local terrain_ready = world.ready and terrain_scene and terrain_scene.status == "available"
        and memory.graph and memory.graph_generation == generation
    local function ensure_mover()
        if memory.mover then return memory.mover end
        if memory.mover_attempt_generation == generation then return nil end

        memory.mover_attempt_generation = generation
        local mover, mover_error = move.new(memory.graph)
        memory.mover = mover
        if not mover and mover_error and mover_error ~= "not_implemented" then
            bot.last_error = mover_error
            io_module.event(context, "error", {reason = mover_error})
        end
        return memory.mover
    end

    local mob, drop
    if terrain_ready then
        local skip_movement = false
        if bot.mode == "follow" then
            local action, follow_error = follow.update(context, world)
            if action and action.kind == "wait" then
                if memory.mover then move.stop(memory.mover) end
                memory.path_target = nil
                skip_movement = true
            elseif action and action.kind == "move" then
                local from = world.character and world.character.platform
                local to = terrain.platform_at(memory.graph, action.x, action.y, tolerance)
                if from and to then
                    local path_target = memory.path_target
                    local target_moved = true
                    if memory.mover and path_target and path_target.platform == to
                        and path_target.scene_generation == generation
                        and path_target.x ~= nil and path_target.y ~= nil then
                        local dx, dy = action.x - path_target.x, action.y - path_target.y
                        local stop_distance = action.stop_distance or (bot.config or defaults).stop_distance
                            or defaults.stop_distance
                        target_moved = dx * dx + dy * dy >= stop_distance * stop_distance
                    end
                    if target_moved then
                        local character_data = context.game.character
                        local movement = character_data and character_data.movement or {}
                        local model = type(movement.model) == "table" and movement.model
                            or movement.defaults or movement.model_defaults or {}
                        local speed = movement.max_speed or model.max_speed
                        local max_jump_height = movement.max_jump_height or model.max_jump_height
                        if speed == nil or max_jump_height == nil then
                            bot.last_error = "movement_unavailable"
                            if memory.mover then move.stop(memory.mover) end
                            memory.path_target = nil
                            skip_movement = true
                        elseif not ensure_mover() then
                            memory.path_target = nil
                            skip_movement = true
                        else
                            local edges, plan_error = terrain.plan(memory.graph, from, to, {
                                speed = speed, max_jump_height = max_jump_height,
                                blocked = memory.blocked or {},
                            })
                            if edges then
                                local set, set_error = move.set_path(memory.mover, edges)
                                if set then
                                    memory.path_target = {
                                        platform = to, scene_generation = generation, x = action.x, y = action.y,
                                    }
                                else
                                    bot.last_error = set_error or "set_path_failed"
                                    move.stop(memory.mover)
                                    memory.path_target = nil
                                end
                            else
                                bot.last_error = plan_error or "path_plan_failed"
                                move.stop(memory.mover)
                                memory.path_target = nil
                            end
                        end
                    end
                else
                    if memory.mover then move.stop(memory.mover) end
                    memory.path_target = nil
                    skip_movement = true
                end
            elseif follow_error and follow_error ~= "not_implemented" then
                bot.last_error = follow_error
            end
        elseif bot.mode == "hunt" then
            mob = combat.select(world, bot.config or defaults)
            if mob then ensure_mover() end
        end

        local movement_status
        if not skip_movement and memory.mover and (bot.mode == "follow" or bot.mode == "hunt") then
            local movement_error
            movement_status, movement_error = move.step(memory.mover, context, world)
            if movement_status == "failed" and movement_error and movement_error ~= "not_implemented" then
                bot.last_error = movement_error
                io_module.event(context, "error", {reason = movement_error})
            end
        end
        if movement_status ~= "running" and bot.mode == "hunt" then
            local combat_status, combat_error
            if mob and memory.mover then
                combat_status, combat_error = combat.step(context, world, mob, memory.mover)
                if combat_status == "failed" and combat_error and combat_error ~= "not_implemented" then
                    bot.last_error = combat_error
                    io_module.event(context, "error", {reason = combat_error})
                end
            end
            if combat_status ~= "running" then
                drop = loot.select(world, bot.config or defaults)
                if drop then
                    if not memory.mover then ensure_mover() end
                    if memory.mover then
                        local loot_status, loot_error = loot.step(context, world, drop, memory.mover)
                        if loot_status == "failed" and loot_error and loot_error ~= "not_implemented" then
                            bot.last_error = loot_error
                            io_module.event(context, "error", {reason = loot_error})
                        end
                    end
                end
            end
        end
    end

    io_module.publish(context, world, now)
end
