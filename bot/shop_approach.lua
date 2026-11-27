-- 仅覆盖已核验的射手村药水店：从入口长平台横向走至卢娜下方。
local terrain = require("lib.terrain")

local function main(context)
    local p = context.game.player
    local function fail(reason)
        p.stop()
        return "failed", reason
    end
    local world, character, scene = context.game.world, context.game.character, context.scene
    if not world or not world.ready or world.map_id ~= 100000102 then return fail("wrong_shop_map") end
    if not scene or not scene.terrain or scene.terrain.status ~= "available" then return fail("terrain_unavailable") end
    if not character or type(character.x) ~= "number" or type(character.y) ~= "number"
        or character.on_ground ~= true or math.abs(character.y - 182) > 15 then
        return fail("character_platform_unknown")
    end
    local npc
    for _, candidate in ipairs(context.game.scene and context.game.scene.npcs or {}) do
        if candidate.name == "卢娜" and type(candidate.x) == "number" and type(candidate.y) == "number" then
            if npc then return fail("npc_ambiguous") end
            npc = candidate
        end
    end
    if not npc then return fail("npc_unavailable") end
    if math.abs(npc.x + 258) > 40 or math.abs(npc.y - character.y) > 100 then
        return fail("npc_distance_unsafe")
    end
    local graph, reason = terrain.build(scene.terrain.navigation)
    if not graph then return fail(reason or "terrain_unavailable") end
    local from = terrain.platform_at(graph, character.x, character.y, graph.model.stand_height)
    local target = terrain.platform_at(graph, npc.x, character.y, graph.model.stand_height)
    if not from or not target or from ~= target then return fail("same_platform_unavailable") end
    local platform = graph.platforms[from]
    if math.min(character.x, npc.x) < platform.left or math.max(character.x, npc.x) > platform.right then
        return fail("walk_outside_platform")
    end
    local state = context.state
    if state.generation and state.generation ~= world.scene_generation then return fail("scene_changed") end
    state.generation = world.scene_generation
    state.started = state.started or context.tick.time
    if context.tick.time - state.started > 30 then return fail("walk_timeout") end
    local dx = npc.x - character.x
    if math.abs(dx) <= 6 then
        if dx * dx + (npc.y - character.y) ^ 2 > 10000 then return fail("npc_distance_unsafe") end
        p.stop()
        return "done"
    end
    p.skill(nil)
    if not p.move(dx > 0 and "right" or "left") then return fail("walk_failed") end
end
