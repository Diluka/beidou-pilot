-- @tick.gear 4
-- @option[type=string,default=walk,choices=walk|brake|reverse|jump_stationary|jump_directional|air_release|air_reverse] scenario 校准场景
-- @option[type=string,default=right,choices=left|right] direction 移动方向
-- @option[type=int,default=800,min=100,max=5000] runup_ms 助跑时长（按30ms物理步取整为步数）
-- @option[type=int,default=800,min=100,max=5000] hold_ms 保持采样时长（按30ms物理步取整为步数）
-- @option[type=int,default=150,min=0,max=2000] air_release_ms 起跳后松向或反向的延迟（按30ms物理步取整）
-- @option[type=int,default=6000,min=500,max=20000] timeout_ms 脚本自限时长，超过后放键结束

-- 本地角色普通运动校准采样脚本。只做一次有界移动或跳跃输入，不攻击、不用药、
-- 不换图，也不调整运动规则或导航阈值；比较由 tools/motion_compare.py 离线完成。
--
-- 每个 tick 向脚本事件日志输出一行稳定前缀的 JSON：tick 时间/档位、场景身份、
-- 物理末态（character.physics）、旧显示位置、旧 character.velocity、movement
-- 有效属性、当前输入意图及边沿、以及本宿主帧样本相对上一份物理更新的状态
-- （first/new/repeat/gap/missing/regressed）。脚本不插值、不补造掉样，也不按
-- update_id 判断对错；比较器按真实更新号去重并对齐。
--
-- 使用条件：已登录、真实站着（on_ground=true）、本图可读怪物列表且为空、
-- 有足够空间的普通平地，并且只有本脚本控制角色。整个会话用 --seconds 另外限时；
-- 本脚本另按 timeout_ms 主动放键结束。固定 `@tick.gear 4` 逐宿主帧采样；它不保证
-- 看见每个物理步，掉样由比较器按 update_id 判证据不足，不插值补造。
local PREFIX = "BEIDOU_MOTION_CAL v1 "

local function json_number(value)
    if type(value) ~= "number" or value ~= value or value == math.huge or value == -math.huge then return "null" end
    return string.format("%.17g", value)
end

local function json_bool(value)
    if value == true then return "true" end
    if value == false then return "false" end
    return "null"
end

local function json_token(value)
    -- 只用于脚本自己声明的固定词表，不是任意文本。
    if type(value) ~= "string" then return "null" end
    return '"' .. value .. '"'
end

local function json_physics_velocity(velocity)
    if velocity == nil or velocity.x == nil or velocity.y == nil then return "null" end
    return "{" .. '"x":' .. json_number(velocity.x) .. ',"y":' .. json_number(velocity.y) .. "}"
end

local function json_native_velocity(velocity)
    if velocity == nil then return "null" end
    local fields = {
        '"x":' .. json_number(velocity.x),
        '"y":' .. json_number(velocity.y),
        '"source":' .. json_token(velocity.source),
    }
    if velocity.interval_ms ~= nil then fields[#fields + 1] = '"interval_ms":' .. json_number(velocity.interval_ms) end
    return "{" .. table.concat(fields, ",") .. "}"
end

local function json_movement(movement)
    if movement == nil then return "null" end
    return "{"
        .. '"model":'
        .. json_token(movement.model)
        .. ',"effective_speed":'
        .. json_number(movement.effective_speed)
        .. ',"effective_jump":'
        .. json_number(movement.effective_jump)
        .. ',"max_speed":'
        .. json_number(movement.max_speed)
        .. ',"max_jump_height":'
        .. json_number(movement.max_jump_height)
        .. "}"
end

local function json_physics(physics)
    if physics == nil then return "null" end
    return "{"
        .. '"update_id":'
        .. json_number(physics.update_id)
        .. ',"step_ms":'
        .. json_number(physics.step_ms)
        .. ',"x":'
        .. json_number(physics.x)
        .. ',"y":'
        .. json_number(physics.y)
        .. ',"velocity":'
        .. json_physics_velocity(physics.velocity)
        .. ',"on_ground":'
        .. json_bool(physics.on_ground)
        .. "}"
end

local function json_scene(context)
    local scene = context.scene
    local map_id = scene ~= nil and scene.map_id or nil
    return '{"map_id":'
        .. json_number(map_id)
        .. ',"scene_generation":'
        .. json_number(context.tick.scene_generation)
        .. "}"
end

local function current_input(state)
    if state.jump and state.move ~= nil then return state.move .. "_jump" end
    if state.jump then return "jump" end
    if state.move ~= nil then return state.move end
    return "none"
end

local function emit(context, event)
    local state = context.state
    local character = context.game.character or {}
    local physics = character.physics
    local update_id = physics ~= nil and physics.update_id or nil
    local update_delta = nil
    local sample = "unknown"
    if update_id ~= nil then
        if state.last_update_id == nil then
            sample = "first"
        else
            update_delta = update_id - state.last_update_id
            if update_delta == 0 then
                sample = "repeat"
            elseif update_delta == 1 then
                sample = "new"
            elseif update_delta > 1 then
                sample = "gap"
            else
                sample = "regressed"
            end
        end
        state.last_update_id = update_id
    elseif state.physics_seen then
        sample = "missing"
    end
    if physics ~= nil then state.physics_seen = true end
    local input = current_input(state)
    local intent_edge = state.last_input ~= nil and state.last_input ~= input
    state.last_input = input
    local parts = {
        '"event":' .. json_token(event),
        '"scenario":' .. json_token(state.scenario),
        '"direction":' .. json_token(state.direction),
        '"phase":' .. json_token(state.phase),
        '"input":' .. json_token(input),
        '"intent_edge":' .. json_bool(intent_edge),
        '"sample":' .. json_token(sample),
        '"finish_reason":' .. json_token(state.finish_reason),
        '"scene":' .. json_scene(context),
        '"tick":{"index":'
            .. json_number(context.tick.index)
            .. ',"gear":'
            .. json_number(context.tick.gear)
            .. ',"time":'
            .. json_number(context.tick.time)
            .. ',"delta":'
            .. json_number(context.tick.delta)
            .. "}",
        '"character_id":' .. json_number(character.id),
        '"native_updates":' .. json_number(character.native_updates),
        '"display":{"x":'
            .. json_number(character.x)
            .. ',"y":'
            .. json_number(character.y)
            .. ',"on_ground":'
            .. json_bool(character.on_ground)
            .. "}",
        '"velocity":' .. json_native_velocity(character.velocity),
        '"movement":' .. json_movement(character.movement),
        '"physics":' .. json_physics(physics),
        '"update_delta":' .. json_number(update_delta),
    }
    context.game.log(PREFIX .. "{" .. table.concat(parts, ",") .. "}")
end

local function set_move(state, player, token)
    if state.move == token then return end
    if token == nil then
        player.move(nil)
    else
        player.move(token)
    end
    state.move = token
end

local function set_jump(state, player, pressed)
    if state.jump == pressed then return end
    if pressed then
        player.jump()
    else
        player.skill(nil)
    end
    state.jump = pressed
end

local function finish(context, reason)
    local state = context.state
    -- 显式撤下方向和动作；Runtime 仍负责确认停止所属持续输入后才发布终态。
    context.game.player.stop()
    state.move = nil
    state.jump = false
    state.finished = true
    state.finish_reason = reason
    emit(context, "end")
end

local function start_scenario(context)
    local state = context.state
    state.phase = "arm"
end

-- 阶段推进按“已消费的物理更新数”而不是墙钟秒数：GUI 约 60Hz、headless 约
-- 125Hz 的宿主回调下，同一毫秒阈值可能落在相差一个 30ms 物理步的位置，导致
-- 两端输入边沿虽经对齐，跳跃/空中阶段仍相差一步。按 update_id 步数触发后，
-- 两端执行完全相同的物理步序列，轨迹和接触事件可以逐物理步比较。
local PHYSICS_STEP_MS = 30

local function steps_for(milliseconds)
    local steps = math.floor(milliseconds / PHYSICS_STEP_MS + 0.5)
    if steps < 1 then steps = 1 end
    return steps
end

local function new_updates(state, physics)
    if physics == nil or physics.update_id == nil or state.phase_update == nil then return 0 end
    return physics.update_id - state.phase_update
end

local function mark_phase(state, physics) state.phase_update = physics ~= nil and physics.update_id or nil end

local function advance(context)
    local state = context.state
    local player = context.game.player
    local character = context.game.character
    local physics = character.physics
    local scenario = state.scenario
    local direction = state.direction
    local opposite = direction == "right" and "left" or "right"
    local runup_steps = steps_for(context.options.runup_ms)
    local hold_steps = steps_for(context.options.hold_ms)
    local air_release_steps = steps_for(context.options.air_release_ms)
    -- 不能用 `x and y or nil` 惯用法：on_ground=false 会被吞成 nil，
    -- 导致跳跃场景永远停在 jump_input 直到超时。
    local on_ground = nil
    if physics ~= nil then on_ground = physics.on_ground end

    if scenario == "walk" then
        if state.phase == "arm" then
            state.phase = "walk"
            set_move(state, player, direction)
            mark_phase(state, physics)
        elseif state.phase == "walk" and new_updates(state, physics) >= hold_steps then
            return finish(context, "scenario_completed")
        end
    elseif scenario == "brake" then
        if state.phase == "arm" then
            state.phase = "runup"
            set_move(state, player, direction)
            mark_phase(state, physics)
        elseif state.phase == "runup" and new_updates(state, physics) >= runup_steps then
            state.phase = "brake"
            set_move(state, player, nil)
            mark_phase(state, physics)
        elseif state.phase == "brake" and new_updates(state, physics) >= hold_steps then
            return finish(context, "scenario_completed")
        end
    elseif scenario == "reverse" then
        if state.phase == "arm" then
            state.phase = "runup"
            set_move(state, player, direction)
            mark_phase(state, physics)
        elseif state.phase == "runup" and new_updates(state, physics) >= runup_steps then
            state.phase = "reverse"
            set_move(state, player, opposite)
            mark_phase(state, physics)
        elseif state.phase == "reverse" and new_updates(state, physics) >= hold_steps then
            return finish(context, "scenario_completed")
        end
    elseif scenario == "jump_stationary" then
        if state.phase == "arm" then
            state.phase = "jump_input"
            set_jump(state, player, true)
            mark_phase(state, physics)
        elseif state.phase == "jump_input" and on_ground == false then
            state.phase = "air"
            state.takeoff_update = physics ~= nil and physics.update_id or nil
        elseif state.phase == "air" and on_ground == true then
            return finish(context, "scenario_completed")
        end
    else
        -- jump_directional / air_release / air_reverse 共用助跑、起跳和落地阶段。
        if state.phase == "arm" then
            state.phase = "runup"
            set_move(state, player, direction)
            mark_phase(state, physics)
        elseif state.phase == "runup" and new_updates(state, physics) >= runup_steps then
            state.phase = "jump_input"
            set_jump(state, player, true)
            mark_phase(state, physics)
        elseif state.phase == "jump_input" and on_ground == false then
            state.phase = "air"
            state.takeoff_update = physics ~= nil and physics.update_id or nil
        elseif state.phase == "air" or state.phase == "air_reverse" then
            if on_ground == true then return finish(context, "scenario_completed") end
            local airborne_steps = 0
            if physics ~= nil and physics.update_id ~= nil and state.takeoff_update ~= nil then
                airborne_steps = physics.update_id - state.takeoff_update
            end
            if airborne_steps >= air_release_steps then
                if scenario == "air_release" and state.move ~= nil then
                    set_move(state, player, nil)
                elseif scenario == "air_reverse" and state.move ~= opposite then
                    state.phase = "air_reverse"
                    set_move(state, player, opposite)
                end
            end
        end
    end
    return nil
end

local function main(context)
    local state = context.state
    local character = context.game.character
    local physics = character.physics
    if state.finished then return "done" end
    if not state.started then
        local scene = context.game.scene
        assert(context.game.world.ready, "calibration_requires_ready_world")
        assert(scene ~= nil and scene.monsters ~= nil, "calibration_requires_readable_monster_list")
        assert(#scene.monsters == 0, "calibration_requires_monster_free_area")
        assert(physics ~= nil and physics.x ~= nil and physics.y ~= nil, "calibration_requires_physics_position")
        assert(character.x ~= nil and character.y ~= nil, "calibration_requires_display_position")
        assert(character.on_ground == true, "calibration_requires_grounded_start")
        assert(character.movement ~= nil, "calibration_requires_movement_reference")
        state.started = true
        state.scenario = context.options.scenario
        state.direction = context.options.direction
        state.start_time = context.tick.time
        state.phase = "preflight"
        state.move = nil
        state.jump = false
        emit(context, "begin")
        start_scenario(context)
        return
    end
    local elapsed = context.tick.time - state.start_time
    if elapsed > context.options.timeout_ms / 1000 then
        finish(context, "timeout")
        return "done"
    end
    advance(context)
    if state.finished then return "done" end
    emit(context, "tick")
    return
end
