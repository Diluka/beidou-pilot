-- 按任务条件打怪：读 /work/bot/quest.conf（{quest_id, mob_ids, count, heal_item}），
-- 平台感知地接近目标怪并普攻；进度从 game.quests 读取，达到 count 后停止。
package.path = "/work/scripts/bot/?.lua;/work/scripts/bot/?/init.lua;" .. package.path
local terrain = require("lib.terrain")
local move = require("lib.move")
local world_mod = require("lib.world")

local function load_quest()
    local file = io.open("/work/bot/quest.conf", "r")
    if not file then return nil end
    local text = file:read("*a")
    file:close()
    local chunk = load(text)
    if not chunk then return nil end
    return chunk()
end

local function quest_progress(context, quest_id)
    local domain = context.game and context.game.quests
    if not domain or type(domain.quests) ~= "table" then return nil end
    for _, record in ipairs(domain.quests) do
        if record.quest_id == quest_id then
            local value = tonumber(record.progress)
            return value, record.state
        end
    end
    return nil
end

local function is_target(quest, mob)
    if type(quest.mob_ids) ~= "table" then return false end
    for _, mob_id in ipairs(quest.mob_ids) do
        if mob.template_id == mob_id then return true end
    end
    return false
end

local function nearest_target(quest, world, c)
    local best, target = 1e9, nil
    for _, mob in ipairs(world.mobs or {}) do
        if mob.x and mob.y and mob.active ~= false and is_target(quest, mob)
            and not (mob.hp_percent ~= nil and mob.hp_percent <= 0) then
            local d = math.abs(mob.x - c.x) + math.abs(mob.y - c.y) * 2
            if d < best then best, target = d, mob end
        end
    end
    return target
end

local function main(context)
    local s, p = context.state, context.game.player
    s.quest = s.quest or load_quest()
    if not s.quest then return "failed", "quest_conf_missing" end
    local quest = s.quest
    local world = world_mod.observe(context)
    if not world then return "failed", "world_unavailable" end
    s.t = s.t or context.tick.time
    local c = world.character
    local progress, state = quest_progress(context, quest.quest_id)
    if state == "completed" then p.stop(); context.game.log("quest completed " .. tostring(quest.quest_id)); return "done" end
    if progress and progress >= (quest.count or 0) then
        p.stop()
        context.game.log(string.format("objective reached %s/%s for quest %s", tostring(progress), tostring(quest.count),
            tostring(quest.quest_id)))
        return "done"
    end
    if not s.graph then
        s.graph = assert(terrain.build(context.scene.terrain.navigation))
        s.mover = move.new(s.graph)
    end
    c.platform = terrain.platform_at(s.graph, c.x, c.y, s.graph.model.stand_height)
    local ratio = (c.hp and c.max_hp and c.max_hp > 0) and (c.hp / c.max_hp) or 1
    if s.healing then
        if context.tick.time - s.heal_time >= 0.5 then p.skill(nil); s.healing = nil end
        return
    end
    if ratio < 0.7 and quest.heal_item and (not s.heal_cd or context.tick.time - s.heal_cd > 2) then
        p.use_item(quest.heal_item)
        s.healing, s.heal_time, s.heal_cd = true, context.tick.time, context.tick.time
        context.game.log(string.format("heal hp=%d/%d", c.hp, c.max_hp))
        return
    end
    local mob = nearest_target(quest, world, c)
    if not mob then
        p.stop()
        s.idle = s.idle or context.tick.time
        if context.tick.time - s.idle > 3 then
            context.game.log("no target in view, waiting")
            s.idle = context.tick.time
        end
        if context.tick.time - s.t > (quest.seconds or 240) then return "failed", "target_not_found" end
        return
    end
    s.idle = nil
    local mob_platform = terrain.platform_at(s.graph, mob.x, mob.y, s.graph.model.stand_height)
    local dx = mob.x - c.x
    if c.platform == mob_platform and math.abs(dx) <= 30 then
        p.move(nil)
        p.attack()
        s.path = false
        if not s.last_attack or context.tick.time - s.last_attack > 1 then
            s.last_attack = context.tick.time
            context.game.log(string.format("attack mob tmpl=%s x=%.0f y=%.0f hp=%s", tostring(mob.template_id),
                mob.x, mob.y, tostring(c.hp)))
        end
        return
    end
    if not s.path_goal or s.path_goal.x ~= mob.x or s.path_goal.y ~= mob.y or not s.path then
        s.path_goal = { x = mob.x, y = mob.y }
        if c.platform == nil or mob_platform == nil then
            s.path = false
            p.move(dx > 0 and "right" or "left")
            return
        end
        local movement = context.game.character.movement or { max_speed = 125, max_jump_height = 77 }
        local edges, reason = terrain.plan(s.graph, c.platform, mob_platform,
            { speed = movement.max_speed, max_jump_height = movement.max_jump_height, blocked = {} })
        if not edges or #edges == 0 then
            s.path = false
            p.move(dx > 0 and "right" or "left")
            context.game.log("plan fallback " .. tostring(reason))
            return
        end
        assert(move.set_path(s.mover, edges))
        s.path = true
        context.game.log(string.format("plan %d edge(s) -> mob platform %s", #edges, tostring(mob_platform)))
    end
    local status, reason = move.step(s.mover, context, world)
    if status == "failed" then
        s.path = false
        p.stop()
        context.game.log("move failed " .. tostring(reason))
        return "failed", reason
    end
    if status == "done" then s.path = false end
    if context.tick.index % 90 == 0 then
        context.game.log(string.format("t=%.0f progress=%s hp=%s x=%.0f y=%.0f", context.tick.time - s.t,
            tostring(progress), tostring(c.hp), c.x, c.y))
    end
    if context.tick.time - s.t > (quest.seconds or 240) then p.stop(); return "failed", "timeout" end
end
