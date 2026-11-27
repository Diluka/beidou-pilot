local io_module = require("lib.io")
local state_module = require("lib.state")
local world_module = require("lib.world")
local terrain = require("lib.terrain")
local move = require("lib.move")
local follow = require("lib.follow")
local navigate = require("lib.target")
local combat = require("lib.combat")
local sustain = require("lib.sustain")
local supply = require("lib.supply")
local loot = require("lib.loot")
local hunt = require("lib.hunt")
local travel = require("lib.travel")
local defaults = require("defaults")
local memory_module = require("lib.memory")
local metrics_module = require("lib.metrics")

local function main(context)
    local memory = context.state
    if not memory.bot then
        memory.bot_root = memory.bot_root or "/work/bot"
        state_module.bot_root = memory.bot_root
        memory.bot = state_module.new()
        memory.bot.player = context.game.player
        memory.started_at = context.tick.time
        memory.last_poll = nil
        memory.force_publish = true
        io_module.event(context, "mode", {mode = "recover", reason = memory.bot.last_error})
    end

    local bot = memory.bot
    local now = context.tick.time
    local function metrics_error(reason)
        if not memory.metrics_error_at or now < memory.metrics_error_at or now - memory.metrics_error_at >= 20 then
            memory.metrics_error_at = now
            pcall(io_module.event, context, "metrics/error", {reason = tostring(reason)})
        end
    end
    if memory.metrics_initialized == nil then
        memory.metrics_initialized = true
        local enabled = (bot.config or defaults).metrics_enabled
        if enabled == nil then enabled = defaults.metrics_enabled end
        if enabled ~= 0 then
            local ok, result, reason = pcall(metrics_module.new, (memory.bot_root or "/work/bot") .. "/metrics.json")
            if ok and result then memory.metrics = result else metrics_error(ok and reason or result) end
        end
    end
    local function metric_call(method, ...)
        if not memory.metrics then return end
        local ok, result, reason = pcall(metrics_module[method], memory.metrics, ...)
        if not ok then
            metrics_error(result)
            memory.metrics = nil -- a partially mutated accumulator is not safe to reuse
        elseif result == false and (method ~= "observe" or reason == "invalid_time") then metrics_error(reason) end
    end
    if (bot.config or defaults).memory_enabled and not memory.store then
        memory.store = memory_module.load(memory.bot_root .. "/memory.lua", now)
        memory.store_path = memory.bot_root .. "/memory.lua"
    end
    local world, observe_error = world_module.observe(context)
    if (bot.config or defaults).memory_enabled and world and world.ready and world.character then
        -- 客户端观察为唯一权威：启动/运行中以 live 覆盖 memory 冲突字段并发布修复事件
        local live = {
            mode = bot.mode, map_id = world.map_id, level = world.character.level,
            x = world.character.x, y = world.character.y, hp = world.character.hp,
            on_ground = world.character.on_ground,
        }
        local repairs = memory_module.reconcile(memory.store, "bot", live)
        if #repairs > 0 and memory.store.__synced then
            io_module.event(context, "memory/repair", {repairs = repairs, map_id = world.map_id})
        end
        memory.store.__synced = true
    end
    if not world then
        metric_call("observe", context, {ready = false})
        memory.metrics_visit = nil
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
                    if command.kind == "stop" or command.kind == "stay" then
                        memory.travel_suspended = true
                    elseif command.kind == "hunt" then
                        memory.travel_suspended = nil
                    end
                end
                if command._ok and (command.kind == "stop" or command.kind == "stay"
                    or bot.mode ~= previous_mode or bot.target ~= previous_target) then
                    if memory.mover then move.stop(memory.mover) end
                    if memory.travel then travel.stop(memory.travel, context); memory.travel = nil end
                    memory.travel_failed = nil
                    memory.path_target, memory.navigation, memory.hunt_retry_at, memory.hunt_empty_since = nil, nil, nil, nil
                    memory.hunt_action, memory.hunt_drop, memory.hunt_patrol = nil, nil, nil
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
        if memory.travel then travel.stop(memory.travel, context); memory.travel = nil end
        memory.path_target = nil
        state_module.transition(bot, "dead", "hp_zero")
        io_module.event(context, "mode", {from = previous, mode = "dead", reason = "hp_zero"})
    elseif bot.mode == "dead" and character.hp ~= nil and character.hp > 0 then
        state_module.transition(bot, "recover", "revived")
        io_module.event(context, "mode", {from = "dead", mode = "recover", reason = "revived"})
    end

    if bot.mode == "hunt" and world.ready then
        local inventory = context.game.inventory
        local items = inventory and inventory.status == "ok" and type(inventory.items) == "table"
            and world.inventory or nil
        local low = supply.check(memory.bot_root or "/work/bot", items)
        if low then
            metric_call("observe", context, {ready = false})
            metric_call("target", nil)
            if memory.mover then move.stop(memory.mover) end
            if memory.travel then travel.stop(memory.travel, context); memory.travel = nil end
            context.game.player.stop()
            bot.last_error = "supply_" .. low.reason
            low.session_id = context.tick.script_id
            low.map_id = world.map_id
            io_module.event(context, "supply/low", low)
            memory.force_publish = true
            io_module.publish(context, world, now)
            return "done"
        end
    end

    local scene = context.scene
    local terrain_scene = scene and scene.terrain
    local generation = world.scene_generation
    if memory.graph_generation ~= generation then
        if memory.mover then move.stop(memory.mover) end
        memory.hunt_action, memory.hunt_drop, memory.hunt_patrol = nil, nil, nil
        memory.loot_abandoned, memory.loot_abandoned_scope = nil, nil
        memory.blocked, memory.hunt_failures = nil, nil
        memory.graph, memory.mover, memory.path_target, memory.follow_unreachable = nil, nil, nil, nil
        memory.graph_generation, memory.graph_attempt_generation, memory.mover_attempt_generation = nil, nil, nil
        memory.hunt_retry_at = nil
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

    metric_call("observe", context, world)
    if memory.metrics then
        local platform = world.character and world.character.platform
        local visit = memory.metrics_visit
        if world.ready and world.map_id and generation and platform then
            if not visit or visit.map_id ~= world.map_id or visit.generation ~= generation or visit.platform ~= platform then
                metric_call("visit", {arrival_reason = visit and "platform_or_scene_changed" or nil,
                    exit_reason = visit and "platform_or_scene_changed" or nil})
                memory.metrics_visit = {map_id = world.map_id, generation = generation, platform = platform}
            end
        else
            memory.metrics_visit = nil
        end
        if bot.mode ~= "hunt" or not world.ready or not memory.graph or memory.graph_generation ~= generation
            or memory.travel then metric_call("target", nil) end
    end

    if memory.travel and (not world.ready or not world.map_id) then
        context.game.player.stop()
        memory.travel.graph, memory.travel.mover, memory.travel.path = nil, nil, nil
        io_module.publish(context, world, now)
        return
    end
    local kind, name
    if bot.mode == "follow" then kind, name = navigate.selector(bot.target) end
    local handled, sustain_error = sustain.step(context, world)
    if handled and not kind then
        metric_call("target", nil)
        if memory.travel then
            context.game.player.move(nil)
            memory.travel.graph, memory.travel.mover, memory.travel.path = nil, nil, nil
        end
        if bot.mode == "hunt" and memory.hunt_action then
            context.game.player.move(nil)
            memory.mover, memory.mover_attempt_generation = nil, nil
            memory.hunt_action, memory.hunt_drop = nil, nil
        end
        if (bot.config or defaults).memory_enabled and memory.store then
        memory_module.flush(memory.store, memory.store_path or memory.bot_root .. "/memory.lua", now)
    end
    io_module.publish(context, world, now)
        return
    elseif not handled and sustain_error and sustain_error ~= "not_implemented" then
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

    if kind then
        memory.navigation = memory.navigation or {generation = generation, map_id = world.map_id,
            instance_id = scene and scene.instance_id, started = now}
        local nav = memory.navigation
        local status, reason = "wait", "terrain_unavailable"
        if handled then
            reason = sustain_error
        elseif terrain_ready then
            status, reason = navigate.step(context, world, nav, kind, name, ensure_mover)
        end
        if status ~= "moving" then
            if memory.mover then
                if handled and (reason == "hp_potion" or reason == "mp_potion") then
                    context.game.player.move(nil) -- sustain now owns the action slot
                    memory.mover, memory.mover_attempt_generation = nil, nil
                else
                    move.stop(memory.mover)
                end
            end
            state_module.transition(bot, "idle", reason)
            io_module.event(context, "target/" .. status, {target = bot.target, reason = reason,
                map_id = world.map_id, scene_generation = generation, elapsed = now - nav.started,
                x = character.x, y = character.y, from = character.platform, to = nav.goal_platform,
                target_x = nav.goal_x, target_y = nav.goal_y, object_id = nav.object_id,
                vx = context.game.character and context.game.character.velocity and context.game.character.velocity.x})
            io_module.event(context, "mode", {from = "follow", mode = "idle", reason = reason})
            memory.navigation, memory.force_publish = nil, true
        end
        io_module.publish(context, world, now)
        return
    end

    -- idle 和 hunt 均遵循地图绑定；显式 stop/stay 保持暂停。
    local plan_file = io.open((memory.bot_root or "/work/bot") .. "/plan.conf", "r")
    local plan_text = plan_file and plan_file:read("*a") or ""
    if plan_file then plan_file:close() end
    local hunt_map, route_path
    for line in plan_text:gmatch("[^\r\n]+") do
        local key, value = line:match("^%s*([%w_]+)%s*=%s*(.-)%s*$")
        if key == "hunt_map" and value:match("^%d+$") then hunt_map = tonumber(value) end
        if key == "route" and value ~= "" then route_path = value end
    end
    route_path = route_path or (memory.bot_root or "/work/bot") .. "/route.json"
    if memory.travel_plan ~= plan_text then
        if memory.travel then travel.stop(memory.travel, context) end
        memory.travel, memory.travel_failed, memory.travel_plan = nil, nil, plan_text
    end
    if (bot.mode ~= "hunt" and bot.mode ~= "idle") or not hunt_map or memory.travel_suspended then
        if memory.travel then travel.stop(memory.travel, context); memory.travel = nil end
        memory.travel_failed = nil
    elseif world.ready and world.map_id and (world.map_id ~= hunt_map or memory.travel) then
        if not memory.travel and not memory.travel_failed and not terrain_ready then
            context.game.player.stop()
            io_module.publish(context, world, now)
            return
        end
        if not memory.travel and not memory.travel_failed then
            local legs, goal = travel.load_route(route_path)
            if legs and goal == hunt_map and legs[1] and legs[1].map == world.map_id then
                if memory.mover then move.stop(memory.mover); memory.mover = nil end
                context.game.player.stop()
                memory.hunt_action, memory.hunt_drop, memory.hunt_patrol = nil, nil, nil
                memory.travel = travel.new(legs, goal)
                io_module.event(context, "travel/start", {map_id = world.map_id, goal = goal})
            else
                if memory.mover then move.stop(memory.mover); memory.mover = nil end
                memory.hunt_action, memory.hunt_drop, memory.hunt_patrol = nil, nil, nil
                context.game.player.stop()
                if not memory.travel_wait_at or now - memory.travel_wait_at >= 10 then
                    io_module.event(context, "travel/wait", {reason = "route_unavailable", map_id = world.map_id, goal = hunt_map})
                    memory.travel_wait_at = now
                end
            end
        end
        if memory.travel then
            local status, reason, event = travel.step(memory.travel, context, world)
            if event then
                local kind = event.kind
                event.kind = nil
                io_module.event(context, "travel/" .. kind, event)
            end
            if status == "failed" then
                bot.last_error, memory.travel_failed = reason, true
                travel.stop(memory.travel, context)
                memory.travel = nil
            elseif status == "done" then
                travel.stop(memory.travel, context)
                memory.travel, memory.travel_wait_at = nil, nil
            end
        else
            context.game.player.stop()
        end
        io_module.publish(context, world, now)
        return
    end

    local function loot_step(drop, mover)
        local edge = mover.edges and mover.edges[mover.index or 1]
        local key = edge and edge.from and edge.to and tostring(edge.from) .. ":" .. tostring(edge.to)
        local was_blocked = key and memory.blocked and memory.blocked[key]
        local status, reason = loot.step(context, world, drop, mover)
        if not key then
            edge = mover.edges and mover.edges[mover.index or 1]
            key = edge and edge.from and edge.to and tostring(edge.from) .. ":" .. tostring(edge.to)
        end
        if status == "failed" and key and not was_blocked and memory.blocked
            and (reason == "landing_mismatch" or reason == "timeout" or reason == "no_progress"
                or reason == "rope_mismatch") then
            memory.blocked[key] = nil
        end
        return status, reason
    end

    if bot.mode == "hunt" and terrain_ready then
        -- Do not interrupt an in-flight navigation edge when platform_at is unknown.
        if character.on_ground == false and memory.mover and memory.hunt_action then
            if memory.mover.status == "running" then move.step(memory.mover, context, world) end
            io_module.publish(context, world, now)
            return
        end
        if character.on_ground and memory.mover and memory.mover.status == "failed" then
            if memory.hunt_action == "patrol" then
                hunt.step(context, world, memory.graph, memory.mover)
                io_module.publish(context, world, now)
                return
            elseif memory.hunt_action == "loot" and memory.hunt_drop then
                loot_step(memory.hunt_drop, memory.mover)
                memory.hunt_drop = nil
                io_module.publish(context, world, now)
                return
            end
        end
        local scope = tostring(world.map_id) .. ":" .. tostring(generation)
        if memory.hunt_blocked_scope ~= scope then
            memory.blocked, memory.hunt_failures, memory.hunt_blocked_scope = nil, nil, scope
            memory.hunt_last_platform, memory.hunt_idle = nil, nil
        end
        if character.on_ground and character.platform then
            local edge = memory.mover and memory.mover.status == "running" and memory.mover.edges
                and memory.mover.edges[memory.mover.index or 1]
            if memory.hunt_last_platform and memory.hunt_last_platform ~= character.platform
                and not (memory.hunt_action == "patrol" and edge and edge.to == character.platform) then
                if memory.mover and memory.mover.status == "running" then move.stop(memory.mover) end
                io_module.event(context, "hunt/recover", {reason = "platform_changed",
                    from = memory.hunt_last_platform, to = character.platform})
                memory.hunt_patrol, memory.hunt_failures, memory.hunt_action, memory.hunt_drop = nil, 0, nil, nil
                memory.hunt_idle = nil
            end
            memory.hunt_last_platform = character.platform
        end
        local local_only = (memory.hunt_failures or 0) >= 3
            or memory.hunt_patrol and memory.hunt_patrol.fallback_until and now < memory.hunt_patrol.fallback_until
        if memory.loot_abandoned_scope ~= scope then
            memory.loot_abandoned, memory.loot_abandoned_scope = {}, scope
        end
        -- 经过掉落物时优先顺手捡：同平台、贴身范围内的掉落优先于选怪。
        local priority_drop
        if character.on_ground == true and type(world.drops) == "table" and #world.drops > 0 then
            priority_drop = loot.select(world, {local_only = true, radius = 60,
                abandoned = memory.loot_abandoned})
        end
        local mob = not priority_drop and combat.select(world, {hunt = true, platform_only = local_only,
            config = bot.config or defaults, graph = memory.graph, context = context}) or nil
        metric_call("target", mob)
        local drop
        if priority_drop then drop = priority_drop end
        if not mob and not drop then
            local route = {}
            if memory.hunt_action == "patrol" and memory.mover and memory.mover.edges then
                for _, edge in ipairs(memory.mover.edges) do route[edge.to] = true end
            end
            local options = {graph = memory.graph, route_platforms = route, abandoned = memory.loot_abandoned,
                local_only = local_only}
            if memory.hunt_drop then
                for _, observed in ipairs(world.drops or {}) do
                    if observed.object_id == memory.hunt_drop.object_id then
                        local filtered = {character = world.character, owner = world.owner, mobs = world.mobs,
                            drops = {observed}}
                        drop = loot.select(filtered, options)
                        break
                    end
                end
                if not drop and memory.mover and memory.mover.loot and memory.mover.loot.pickup_requested then
                    drop = memory.hunt_drop
                end
            end
            drop = drop or loot.select(world, options)
        end
        if not mob and not drop and character.on_ground and character.platform
            and type(character.x) == "number" and type(character.y) == "number"
            and not (context.game.character or {}).attacking then
            local idle = memory.hunt_idle
            if not idle or idle.platform ~= character.platform
                or math.abs(character.x - idle.x) >= 5 or math.abs(character.y - idle.y) >= 5 then
                memory.hunt_idle = {x = character.x, y = character.y, platform = character.platform, since = now}
            elseif now - idle.since >= 10 then
                if memory.mover and memory.mover.status == "running" then move.stop(memory.mover) end
                io_module.event(context, "hunt/stalled", {platform = character.platform, seconds = now - idle.since})
                metric_call("event", "stuck", {map_id = world.map_id, platform = character.platform, unattributed = true})
                memory.hunt_patrol, memory.hunt_failures, memory.hunt_action = nil, 0, nil
                memory.hunt_idle = {x = character.x, y = character.y, platform = character.platform, since = now}
            end
        else
            memory.hunt_idle = nil
        end
        local action = mob and "combat" or drop and "loot" or "patrol"
        if memory.hunt_action and memory.hunt_action ~= action then
            if memory.mover then
                move.stop(memory.mover)
                memory.mover.loot = nil
            end
            context.game.player.skill(nil)
            memory.hunt_action, memory.hunt_drop = action, nil
            io_module.publish(context, world, now)
            return
        end
        memory.hunt_action = action
        local mover = ensure_mover()
        if mover then
            local status, reason
            if action == "combat" then
                status, reason = combat.step(context, world, mob, mover)
            elseif action == "loot" then
                memory.hunt_drop = drop
                status, reason = loot_step(drop, mover)
                if status ~= "running" then memory.hunt_drop = nil end
            else
                status, reason = hunt.step(context, world, memory.graph, mover)
            end
            if status == "failed" then
                if action == "combat" then metric_call("target", nil) end
                if reason == "no_progress" then
                    metric_call("event", "stuck", {map_id = world.map_id, platform = character.platform, unattributed = true})
                end
                bot.last_error = reason
                if action == "combat" then
                    local edge = mover.status == "failed" and mover.edges and mover.edges[mover.index or 1]
                    if edge then
                        memory.hunt_failures = (memory.hunt_failures or 0) + 1
                        local structural = reason == "no_path" or reason == "unsupported_edge"
                            or reason == "invalid_edge" or reason == "character_unavailable"
                        if structural and edge.from and edge.to and edge.from ~= edge.to then
                            memory.blocked = memory.blocked or {}
                            memory.blocked[tostring(edge.from) .. ":" .. tostring(edge.to)] = true
                        end
                    end
                    if reason == "retreat_blocked" or reason == "timeout" or reason == "no_progress"
                        or reason == "landing_mismatch" then
                        memory.hunt_action, memory.hunt_patrol, memory.hunt_idle = nil, nil, nil
                        memory.hunt_failures = 0
                    end
                    if not memory.hunt_error_at or now - memory.hunt_error_at >= 10 then
                        io_module.event(context, "error", {reason = reason, edge_kind = edge and edge.kind,
                            edge_from = edge and edge.from, edge_to = edge and edge.to, edge_x = edge and edge.x})
                        memory.hunt_error_at = now
                    end
                end
            end
        end
        io_module.publish(context, world, now)
        return
    end
    if terrain_ready then
        local skip_movement = false
        if bot.mode == "follow" then
            local action, follow_error = follow.update(context, world)
            if action and action.kind == "move" then
                local from = world.character and world.character.platform
                local to = terrain.platform_at(memory.graph, action.x, action.y, tolerance)
                if from and to then
                    local path_target = memory.path_target
                    local target_moved = true
                    if memory.mover and memory.mover.status == "running" and path_target and path_target.platform == to
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
                            if edges and #edges == 0 and from == to and type(action.x) == "number" then
                                local character = world.character or {}
                                if type(character.x) == "number" then
                                    edges = {{
                                        kind = "walk", from = from, to = to,
                                        x = character.x, destination = action.x, rise = 0,
                                    }}
                                end
                            end
                            if from ~= to and (plan_error == "no_path" or (edges and #edges == 0)) then
                                memory.follow_unreachable = {from = from, to = to}
                                action = follow.update(context, world)
                            elseif edges then
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
                elseif not (memory.mover and memory.mover.status == "running" and memory.path_target) then
                    if memory.mover then move.stop(memory.mover) end
                    memory.path_target = nil
                    skip_movement = true
                end
            elseif follow_error and follow_error ~= "not_implemented" then
                bot.last_error = follow_error
            end
            if action and action.kind == "wait" then
                if memory.mover then move.stop(memory.mover) end
                memory.path_target = nil
                skip_movement = true
            end
        end

        local movement_status
        if not skip_movement and memory.mover and bot.mode == "follow" then
            local movement_error
            movement_status, movement_error = move.step(memory.mover, context, world)
            if movement_status == "failed" and movement_error and movement_error ~= "not_implemented" then
                bot.last_error = movement_error
                io_module.event(context, "error", {reason = movement_error})
            end
        end

    end

    io_module.publish(context, world, now)
end
