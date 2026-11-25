local terrain = require("lib.terrain")
local synthetic = dofile("bot/test/fixtures/synthetic.lua")
local real = dofile("bot/test/fixtures/map_102000000.lua")

local graph, reason = terrain.build(synthetic.navigation)
assert(graph and reason == nil, "synthetic navigation must build: " .. tostring(reason))
assert(graph.navigation == synthetic.navigation, "graph must retain the original navigation reference")
assert(graph.platforms == synthetic.navigation.platforms, "platforms must retain the native 1-based array")
assert(graph.walls == synthetic.navigation.walls and graph.ropes == synthetic.navigation.ropes
    and graph.candidates == synthetic.navigation.candidates and graph.model == synthetic.navigation.model,
    "graph must retain native navigation fields")
assert(terrain.platform_at(graph, 50, 100, 0) == 1, "flat platform position must match")
assert(terrain.platform_at(graph, 100, 100, 0) == 1, "platform edge must be inclusive")
assert(terrain.platform_at(graph, -1, 100, 25) == nil, "position outside all platforms must not match")
assert(terrain.platform_at(graph, 260, 90, 5) == nil, "position above the rope must not be mistaken for a platform")
assert(terrain.platform_at(graph, 50, 100, -1) == nil, "negative tolerance must not match")

local function navigation_with_platforms(platforms)
    return {
        model = synthetic.navigation.model,
        terrain_left = synthetic.navigation.terrain_left,
        terrain_right = synthetic.navigation.terrain_right,
        platforms = platforms,
        walls = synthetic.navigation.walls,
        ropes = {},
        candidates = {walk = {}, step = {}, jumpup = {}, drop = {}, rope = {}},
    }
end

local function graph_for_candidate(kind, values)
    local navigation = navigation_with_platforms(synthetic.navigation.platforms)
    navigation.ropes = synthetic.navigation.ropes
    navigation.candidates[kind] = values
    return assert(terrain.build(navigation))
end

local candidate_examples = {
    walk = {1, 2, 100, 120, 20},
    step = {1, 2, 100, 120, 20},
    jumpup = {1, 2, 90, 150, 20},
    drop = {1, 2, 90, 150, 40},
    rope = {3, 4, 260, 260, 40, 1},
}
for kind, values in pairs(candidate_examples) do
    local from, to = values[1], values[2]
    local planned = assert(terrain.plan(graph_for_candidate(kind, values), from, to))
    assert(#planned == 1 and planned[1].kind == kind, kind .. " candidate must be plannable")
    assert(planned[1].from == from and planned[1].to == to
        and planned[1].x == values[3] and planned[1].destination == values[4]
        and planned[1].rise == values[5], kind .. " edge metadata must be retained")
    if kind == "rope" then assert(planned[1].rope_index == values[6], "rope index must be retained") end
end

local horizontal_navigation = navigation_with_platforms({
    {index=1,left=0,right=40,open_left=true,open_right=true,segments={0,40,100,100}},
    {index=2,left=64,right=104,open_left=true,open_right=true,segments={64,104,100,100}},
})
horizontal_navigation.walls = {}
local horizontal_graph = assert(terrain.build(horizontal_navigation))
local horizontal_path = assert(terrain.plan(horizontal_graph, 1, 2))
assert(#horizontal_path == 1 and horizontal_path[1].kind == "horizontal_jump"
    and horizontal_path[1].from == 1 and horizontal_path[1].to == 2
    and horizontal_path[1].destination > horizontal_graph.platforms[2].left,
    "a clear 24px horizontal gap must create a supported jump edge")
local ceiling_navigation = navigation_with_platforms({
    {index=1,left=0,right=40,open_left=true,open_right=true,segments={0,40,100,100}},
    {index=2,left=64,right=104,open_left=true,open_right=true,segments={64,104,100,100}},
    {index=3,left=40,right=64,open_left=true,open_right=true,segments={40,64,50,50}},
})
ceiling_navigation.walls = {}
local ceiling_path, ceiling_reason = terrain.plan(assert(terrain.build(ceiling_navigation)), 1, 2)
assert(ceiling_path == nil and ceiling_reason == "no_path",
    "a platform intruding into the jump clearance envelope must prevent the edge")

local plan_graph = assert(terrain.build(synthetic.navigation))
local planned = assert(terrain.plan(plan_graph, 1, 4, {speed = 125, blocked = {}}))
assert(#planned == 3, "synthetic path must use three edges")
assert(planned[1].kind == "walk" and planned[2].kind == "step" and planned[3].kind == "rope",
    "A* must choose the lowest-cost valid route")
assert(planned[1].from == 1 and planned[3].to == 4, "path endpoints must match the request")
for index = 1, #planned - 1 do
    assert(planned[index].to == planned[index + 1].from, "path edges must be continuous")
end
local repeated = assert(terrain.plan(plan_graph, 1, 4, {speed = 125, blocked = {}}))
assert(#repeated == #planned, "repeated planning must return the same edge count")
for index, edge in ipairs(planned) do
    assert(repeated[index].kind == edge.kind and repeated[index].from == edge.from
        and repeated[index].to == edge.to, "repeated planning must return the same edge sequence")
end
local same_platform = assert(terrain.plan(plan_graph, 2, 2))
assert(#same_platform == 0, "planning from a platform to itself must return an empty path")
local no_path, no_path_reason = terrain.plan(plan_graph, 1, 4, {blocked = {["1:2"] = true}})
assert(no_path == nil and no_path_reason == "no_path", "blocking all first-hop edges must report no_path")
local unreachable_path, unreachable_reason = terrain.plan(graph_for_candidate("walk", {}), 1, 2)
assert(unreachable_path == nil and unreachable_reason == "no_path", "a disconnected graph must report no_path")
local out_of_range_candidates = {walk = {999, 2, 0, 0, 0}, step = {}, jumpup = {}, drop = {}, rope = {}}
local out_of_range_path, out_of_range_reason = terrain.plan({
    model = synthetic.navigation.model,
    platforms = synthetic.navigation.platforms,
    candidates = out_of_range_candidates,
}, 1, 2)
assert(out_of_range_path == nil and out_of_range_reason == "no_path",
    "candidate edges with out-of-range platform indexes must be skipped")
local invalid_path, invalid_reason = terrain.plan(plan_graph, 0, 2)
assert(invalid_path == nil and invalid_reason == "invalid_platform", "invalid platform indices must be rejected")
invalid_path, invalid_reason = terrain.plan(plan_graph, 1, #plan_graph.platforms + 1)
assert(invalid_path == nil and invalid_reason == "invalid_platform", "out-of-range goal must be rejected")
local model_path, model_reason = terrain.plan({model = nil}, 1, 1)
assert(model_path == nil and model_reason == "model_unavailable", "missing model must report model_unavailable")

local filtered_path, filtered_reason = terrain.plan(
    graph_for_candidate("jumpup", {1, 2, 90, 150, 76}), 1, 2)
assert(filtered_path == nil and filtered_reason == "no_path", "jumpup above the model limit must be filtered")
filtered_path, filtered_reason = terrain.plan(
    graph_for_candidate("jumpup", candidate_examples.jumpup), 1, 2, {max_jump_height = 10})
assert(filtered_path == nil and filtered_reason == "no_path", "max_jump_height must filter jumpup edges")
filtered_path, filtered_reason = terrain.plan(
    graph_for_candidate("drop", {1, 2, 90, 150, 66}), 1, 2)
assert(filtered_path == nil and filtered_reason == "no_path", "drop above the model limit must be filtered")
filtered_path, filtered_reason = terrain.plan(
    graph_for_candidate("drop", {1, 2, 90, 150, 3}), 1, 2)
assert(filtered_path == nil and filtered_reason == "no_path", "drop below the model limit must be filtered")
filtered_path, filtered_reason = terrain.plan(
    graph_for_candidate("rope", {3, 4, 260, 260, 96, 1}), 3, 4)
assert(filtered_path == nil and filtered_reason == "no_path", "rope above the model limit must be filtered")
filtered_path, filtered_reason = terrain.plan(
    graph_for_candidate("rope", {3, 4, 260, 260, -96, 1}), 3, 4)
assert(filtered_path == nil and filtered_reason == "no_path", "rope below the model limit must be filtered")

local overlap_navigation = navigation_with_platforms({
    {index = 1, left = 0, right = 100, open_left = true, open_right = true, segments = {0, 100, 100, 100}},
    {index = 2, left = 0, right = 100, open_left = true, open_right = true, segments = {0, 100, 90, 90}},
})
local overlap_graph = assert(terrain.build(overlap_navigation))
assert(terrain.platform_at(overlap_graph, 50, 91, 10) == 2,
    "overlapping platforms must choose the nearest height")
assert(terrain.platform_at(overlap_graph, 50, 95, 10) == 1,
    "equidistant overlapping platforms must choose the lower index")

-- A stationary vertical jump first touches the highest reachable surface on descent,
-- not necessarily the pair used to generate the native candidate.
local stacked = navigation_with_platforms({
    {index=1, left=0, right=100, open_left=true, open_right=true, segments={0,100,100,100}},
    {index=2, left=0, right=100, open_left=true, open_right=true, segments={0,100,60,60}},
    {index=3, left=0, right=100, open_left=true, open_right=true, segments={0,100,35,35}},
})
stacked.candidates.jumpup = {1,2,50,50,40}
local stacked_graph = assert(terrain.build(stacked))
local shadowed, why = terrain.plan(stacked_graph,1,2)
assert(not shadowed and why == "no_path", "a higher landing surface intercepts this candidate across its entire width")
assert(terrain.plan(stacked_graph,1,2,{max_jump_height=55}), "a platform above the apex does not intercept")
stacked.platforms[3].left = 47
stacked.platforms[3].segments = {47,100,35,35}
local clear = assert(terrain.plan(stacked_graph,1,2))[1]
assert(clear.kind=="jumpup" and clear.x==clear.destination and clear.x+8<47 and clear.to==2,
    "use an unobstructed column of the same pair, including approach tolerance")
assert(stacked.candidates.jumpup[3]==50, "alternate launch columns must not modify the native snapshot")
stacked.platforms[2].segments = {0,5,60,60, 45,48,60,60, 52,55,60,60, 95,100,60,60}
shadowed, why = terrain.plan(stacked_graph,1,2,{max_jump_height=55})
assert(not shadowed and why=="no_path", "a platform's bounding box alone cannot support a landing strip")

local down_navigation = navigation_with_platforms({
    {index=1, left=0, right=100, open_left=true, open_right=true, segments={0,100,100,100}},
    {index=2, left=0, right=100, open_left=true, open_right=true, segments={0,100,160,160}},
})
local down_graph = assert(terrain.build(down_navigation))
local down = assert(terrain.plan(down_graph, 1, 2))[1]
assert(down.kind == "downjump" and down.x == down.destination, "overlapping lower floor supports downjump")
down_navigation.walls = {50, 0, 200}
assert(not terrain.plan(assert(terrain.build(down_navigation)), 1, 2), "wall blocks downjump")
down_navigation.walls = {}
down_navigation.platforms[3] = {index=3, left=0, right=100, open_left=true, open_right=true, segments={0,100,70,70}}
assert(not terrain.plan(assert(terrain.build(down_navigation)), 1, 2, {blocked={["1:3"]=true}}), "ceiling blocks downjump")
down_navigation.platforms[3] = nil
down_navigation.platforms[2].segments = {0,40,160,160, 60,100,160,160}
assert(not terrain.plan(assert(terrain.build(down_navigation)), 1, 2), "unsupported landing strip blocks downjump")
down_navigation.platforms[2].left, down_navigation.platforms[2].right = 300, 400
down_navigation.platforms[2].segments = {300,400,160,160}
assert(not terrain.plan(assert(terrain.build(down_navigation)), 1, 2), "no overlapping landing rejects downjump")

local sloped_navigation = navigation_with_platforms({
    {index = 1, left = 0, right = 100, open_left = true, open_right = true, segments = {0, 100, 100, 50}},
})
local sloped_graph = assert(terrain.build(sloped_navigation))
assert(terrain.platform_at(sloped_graph, 50, 75, 0) == 1, "sloped segment height must be interpolated")

local bad_graph, bad_reason = terrain.build(nil)
assert(bad_graph == nil and bad_reason == "navigation_unavailable", "nil navigation reason must be stable")
bad_graph, bad_reason = terrain.build({model = synthetic.navigation.model, candidates = synthetic.navigation.candidates})
assert(bad_graph == nil and bad_reason == "navigation_invalid:platforms", "missing platforms reason must be stable")
local missing_candidates = navigation_with_platforms(synthetic.navigation.platforms)
missing_candidates.candidates = nil
bad_graph, bad_reason = terrain.build(missing_candidates)
assert(bad_graph == nil and bad_reason == "navigation_invalid:candidates", "missing candidates reason must be stable")
local missing_model = navigation_with_platforms(synthetic.navigation.platforms)
missing_model.model = nil
bad_graph, bad_reason = terrain.build(missing_model)
assert(bad_graph == nil and bad_reason == "navigation_invalid:model", "missing model reason must be stable")
local sparse_platforms = navigation_with_platforms({
    [1] = synthetic.navigation.platforms[1],
    [3] = synthetic.navigation.platforms[3],
})
bad_graph, bad_reason = terrain.build(sparse_platforms)
assert(bad_graph == nil and bad_reason == "navigation_invalid:platforms", "sparse platforms must be rejected")
local sparse_segments = navigation_with_platforms({
    {index = 1, left = 0, right = 100, open_left = true, open_right = true,
        segments = {[1] = 0, [2] = 100, [4] = 100, [5] = 100}},
})
bad_graph, bad_reason = terrain.build(sparse_segments)
assert(bad_graph == nil and bad_reason == "navigation_invalid:platforms", "sparse segments must be rejected")
local sparse_walls = navigation_with_platforms(synthetic.navigation.platforms)
sparse_walls.walls = {[1] = 100, [3] = 80}
bad_graph, bad_reason = terrain.build(sparse_walls)
assert(bad_graph == nil and bad_reason == "navigation_invalid:walls", "sparse walls must be rejected")
local invalid_candidate = navigation_with_platforms(synthetic.navigation.platforms)
invalid_candidate.candidates.walk = {999, 1, 0, 0, 0}
bad_graph, bad_reason = terrain.build(invalid_candidate)
assert(bad_graph == nil and bad_reason == "navigation_invalid:candidates",
    "candidate platform references must be validated")
local invalid_rope_candidate = navigation_with_platforms(synthetic.navigation.platforms)
invalid_rope_candidate.candidates.rope = {1, 2, 0, 0, 0, 999}
bad_graph, bad_reason = terrain.build(invalid_rope_candidate)
assert(bad_graph == nil and bad_reason == "navigation_invalid:candidates",
    "rope candidate references must be validated")
local sparse_candidates = navigation_with_platforms(synthetic.navigation.platforms)
sparse_candidates.candidates.walk = {[1] = 1, [3] = 1}
bad_graph, bad_reason = terrain.build(sparse_candidates)
assert(bad_graph == nil and bad_reason == "navigation_invalid:candidates", "sparse candidates must be rejected")
local sparse_rope_platforms = navigation_with_platforms(synthetic.navigation.platforms)
sparse_rope_platforms.ropes = {{index = 1, x = 100, y1 = 0, y2 = 10, platforms = {[1] = 1, [3] = 100}}}
bad_graph, bad_reason = terrain.build(sparse_rope_platforms)
assert(bad_graph == nil and bad_reason == "navigation_invalid:ropes", "sparse rope platform pairs must be rejected")

assert(real.map_id == 102000000 and real.scene_generation == 3, "character sample must match the captured map fixture")
local real_graph = assert(terrain.build(real.navigation))
-- The captured p87 starts at x=1200 and intercepts the old p125->86 column.
-- There is a clear overlap to its left; p85->87 still has a direct jump too.
local movement = {speed=125, max_jump_height=77.01}
local first = assert(terrain.plan(real_graph,125,86,movement))[1]
assert(first.kind=="jumpup" and first.to==86 and first.x==first.destination
    and first.x-8>=real_graph.platforms[86].left and first.x+8<real_graph.platforms[87].left)
first = assert(terrain.plan(real_graph,85,87,movement))[1]
assert(first.kind=="jumpup" and first.to==87)
-- Observed in the existing dev/observer record for map 102000000, scene generation 3.
local character_x, character_y = 2452, 1935
local character_platform = terrain.platform_at(real_graph, character_x, character_y, 25)
assert(character_platform == 125, "observed development character position must map to platform 125")
local candidate_count = 0
for kind, values in pairs(real.navigation.candidates) do
    candidate_count = candidate_count + #values / (kind == "rope" and 6 or 5)
end
assert(#real_graph.platforms > 0 and candidate_count > 0, "real fixture must contain platforms and candidates")
local real_candidates = real.navigation.candidates
local api_edges, api_error = terrain.plan(real_graph, 3, 9, {blocked = {}})
assert(api_edges, api_error)
local real_path = assert(terrain.plan(real_graph, character_platform, 1))
assert(#real_path >= 3, "real fixture must produce a path with at least three edges")
for index = 1, #real_path - 1 do
    assert(real_path[index].to == real_path[index + 1].from, "real fixture path must be continuous")
end
assert(real_path[1].from == character_platform and real_path[#real_path].to == 1,
    "real fixture path endpoints must match the request")
assert(real_graph.navigation == real.navigation and real.navigation.candidates == real_candidates,
    "planning must not modify the navigation snapshot")
local real_path_kinds = {}
for _, edge in ipairs(real_path) do real_path_kinds[#real_path_kinds + 1] = edge.kind end

local map10000 = dofile("bot/test/fixtures/map_10000.lua")
assert(map10000.map_id == 10000, "tutorial fixture must retain the captured map identity")
local tutorial_graph = assert(terrain.build(map10000.navigation))
local tutorial_jump = assert(terrain.plan(tutorial_graph, 4, 10, {speed = 125}))
assert(#tutorial_jump == 1 and tutorial_jump[1].kind == "horizontal_jump"
    and tutorial_jump[1].from == 4 and tutorial_jump[1].to == 10
    and tutorial_jump[1].destination > tutorial_graph.platforms[10].left
    and tutorial_jump[1].destination < tutorial_graph.platforms[10].right,
    "the supported p4-to-p10 gap must plan a horizontal jump onto the target platform")
for _, pair in ipairs({{3, 4}, {9, 10}, {7, 8}, {7, 9}}) do
    local no_route, no_route_reason = terrain.plan(tutorial_graph, pair[1], pair[2], {speed = 125})
    assert(no_route == nil and no_route_reason == "no_path",
        ("blocked or unreachable tutorial route %d->%d must remain no_path"):format(pair[1], pair[2]))
end

print(("terrain ok: synthetic locations=8; map=%d platforms=%d candidates=%d character=(%d,%d) platform=%d path=%d->1 edges=%d kinds=%s")
    :format(real.map_id, #real_graph.platforms, candidate_count, character_x, character_y,
        character_platform, character_platform, #real_path, table.concat(real_path_kinds, ",")))
