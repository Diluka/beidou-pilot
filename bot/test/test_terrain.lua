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

local overlap_navigation = navigation_with_platforms({
    {index = 1, left = 0, right = 100, open_left = true, open_right = true, segments = {0, 100, 100, 100}},
    {index = 2, left = 0, right = 100, open_left = true, open_right = true, segments = {0, 100, 90, 90}},
})
local overlap_graph = assert(terrain.build(overlap_navigation))
assert(terrain.platform_at(overlap_graph, 50, 91, 10) == 2,
    "overlapping platforms must choose the nearest height")
assert(terrain.platform_at(overlap_graph, 50, 95, 10) == 1,
    "equidistant overlapping platforms must choose the lower index")

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
-- Observed in the existing dev/observer record for map 102000000, scene generation 3.
local character_x, character_y = 2452, 1935
local character_platform = terrain.platform_at(real_graph, character_x, character_y, 25)
assert(character_platform == 125, "observed development character position must map to platform 125")
local candidate_count = 0
for kind, values in pairs(real.navigation.candidates) do
    candidate_count = candidate_count + #values / (kind == "rope" and 6 or 5)
end
assert(#real_graph.platforms > 0 and candidate_count > 0, "real fixture must contain platforms and candidates")

print(("terrain ok: synthetic locations=8; map=%d platforms=%d candidates=%d character=(%d,%d) platform=%d")
    :format(real.map_id, #real_graph.platforms, candidate_count, character_x, character_y, character_platform))
