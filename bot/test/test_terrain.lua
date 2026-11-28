local terrain = require("lib.terrain")
local synthetic = dofile("bot/test/fixtures/synthetic.lua")
local real = dofile("bot/test/fixtures/map_102000000.lua")
local route_map = assert(terrain.build(dofile("bot/test/fixtures/map_100030000.lua").navigation))
assert(terrain.platform_at(route_map, -947, -865, 70) == 33, "east00 must resolve to platform 33")
for _, from in ipairs({5, 69, 71}) do
    local route = assert(terrain.plan(route_map, from, 33, {speed=125, max_jump_height=77.00625}))
    assert(#route > 0 and route[1].from == from and route[#route].to == 33)
end
local route69 = assert(terrain.plan(route_map, 69, 33, {speed=125, max_jump_height=77.00625}))
assert(route69[1].kind == "jumpup" and route69[1].from == 69 and route69[1].to == 67
    and route69[1].x == -3285 and route69[1].destination == -3269)
local shop = dofile("bot/test/fixtures/map_100000102.lua")
local shop_graph = assert(terrain.build(shop.navigation))
local shop_path = assert(terrain.plan(shop_graph, 6, 13, {speed = 125, max_jump_height = 77.00625}))
assert(#shop_path > 1, "shop route must avoid the intercepted direct drop")
for _, edge in ipairs(shop_path) do
    assert(not (edge.kind == "drop" and edge.from == 6 and edge.to == 13 and edge.x == 99),
        "shop platform 14 intercepts the observed 6->13 drop")
end

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
    local platforms = synthetic.navigation.platforms
    if kind == "drop" then
        platforms = {
            {index=1,left=0,right=100,open_left=true,open_right=true,segments={0,100,100,100}},
            {index=2,left=100,right=180,open_left=true,open_right=true,segments={100,180,140,140}},
        }
    end
    local navigation = navigation_with_platforms(platforms)
    navigation.ropes = kind == "drop" and {} or synthetic.navigation.ropes
    navigation.candidates[kind] = values
    return assert(terrain.build(navigation))
end

-- A lower platform reachable by drop must not use a cheaper rope shortcut.
local descent_nav = navigation_with_platforms({
    {index=1,left=0,right=100,open_left=true,open_right=true,segments={0,100,100,100}},
    {index=2,left=100,right=180,open_left=true,open_right=true,segments={100,180,140,140}},
})
descent_nav.walls = {}
descent_nav.ropes = {{index=1,x=100,y1=100,y2=140,platforms={1,100,2,140}}}
descent_nav.candidates.drop = {1,2,100,120,40}
descent_nav.candidates.rope = {1,2,100,100,40,1}
local descent_graph = assert(terrain.build(descent_nav))
local descent = assert(terrain.plan(descent_graph,1,2))
assert(#descent==1 and descent[1].kind=="drop", "prefer a direct drop to rope descent")
local rope_fallback = assert(terrain.plan(descent_graph,1,2,{blocked={["1:2:drop"]=true}}))
assert(#rope_fallback>0 and rope_fallback[1].kind:match("rope"), "retain rope fallback")

local candidate_examples = {
    walk = {1, 2, 100, 120, 20},
    step = {1, 2, 100, 120, 20},
    jumpup = {1, 2, 90, 150, 20},
    drop = {1, 2, 90, 150, 40},
    rope = {3, 4, 260, 260, 40, 1},
}
for kind, values in pairs(candidate_examples) do
    local from, to = values[1], values[2]
    local candidate_graph = graph_for_candidate(kind, values)
    if kind == "rope" then
        -- 绳节点通道会生成更便宜的上下绳路径；这里只校验原生 rope 候选本身。
        candidate_graph.rope_nodes = nil
    end
    local planned = assert(terrain.plan(candidate_graph, from, to))
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

-- Shop capture: the higher floor intercepts the planned descent to the lower floor.
local drop_occlusion = navigation_with_platforms({
    {index=1,left=91,right=174,open_left=true,open_right=true,segments={91,174,57,57}},
    {index=2,left=61,right=108,open_left=true,open_right=true,segments={61,108,120,120}},
    {index=3,left=59,right=109,open_left=true,open_right=true,segments={59,109,72,73}},
})
drop_occlusion.walls = {}
drop_occlusion.candidates.drop = {1,2,99,74,63}
local drop_graph = assert(terrain.build(drop_occlusion))
local shadowed_drop = terrain.plan(drop_graph, 1, 2, {blocked={["1:3"]=true}})
assert(not shadowed_drop, "intermediate floor must reject a drop even when its bounding corridor overlaps")
drop_occlusion.platforms[3] = {index=3,left=0,right=50,open_left=true,open_right=true,segments={0,50,72,73}}
local open_drop = assert(terrain.plan(drop_graph, 1, 2))[1]
assert(open_drop.kind == "drop" and open_drop.from == 1 and open_drop.to == 2,
    "a floor outside the drop corridor must not reject the candidate")

local plan_graph = assert(terrain.build(synthetic.navigation))
local planned = assert(terrain.plan(plan_graph, 1, 4, {speed = 125, blocked = {}}))
assert(#planned >= 3, "synthetic path must use at least three edges")
assert(planned[1].kind == "walk" and planned[2].kind == "step"
    and planned[3].kind == "rope_grab" and planned[#planned].kind == "rope_leave",
    "A* must route through the rope channel instead of the native rope candidate")
assert(planned[1].from == 1 and planned[#planned].to == 4, "path endpoints must match the request")
for index = 1, #planned - 1 do
    assert(planned[index].to == planned[index + 1].from, "path edges must be continuous")
end
local repeated = assert(terrain.plan(plan_graph, 1, 4, {speed = 125, blocked = {}}))
assert(#repeated == #planned, "repeated planning must return the same edge count")
for index, edge in ipairs(planned) do
    assert(repeated[index].kind == edge.kind and repeated[index].from == edge.from
        and repeated[index].to == edge.to, "repeated planning must return the same edge sequence")
end
local same_platform, same_reason = terrain.plan(plan_graph, 2, 2)
assert(same_platform and #same_platform == 0 and same_reason == "same_platform",
    "planning on one platform returns a successful zero-edge path")
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
local native_rope_graph = graph_for_candidate("rope", {3, 4, 260, 260, 96, 1})
native_rope_graph.rope_nodes = nil
filtered_path, filtered_reason = terrain.plan(native_rope_graph, 3, 4)
assert(filtered_path and filtered_path[1].kind == "rope" and filtered_path[1].rise == 96,
    "long rope climbs must not be filtered by grab tolerance")
native_rope_graph = graph_for_candidate("rope", {3, 4, 260, 260, -96, 1})
native_rope_graph.rope_nodes = nil
filtered_path, filtered_reason = terrain.plan(native_rope_graph, 3, 4)
assert(filtered_path and filtered_path[1].kind == "rope" and filtered_path[1].rise == -96,
    "long descending rope climbs must not be filtered by grab tolerance")

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
local rope_path = assert(terrain.plan(tutorial_graph, 4, 1))
assert(rope_path[1].kind == "rope_grab" and rope_path[1].from == 4
    and rope_path[1].rope_index == 1 and rope_path[1].x == 975
    and rope_path[#rope_path].kind == "rope_leave" and rope_path[#rope_path].to == 1
    and rope_path[#rope_path].rise == -2,
    "map 10000 p4-to-p1 must climb the long rope channel")
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

-- 绳通道：斜面平台抓绳、攀爬、绳间跳跃与跳离。
local rope_fixture = dofile("bot/test/fixtures/rope_terrain.lua")
local rope_graph = assert(terrain.build(rope_fixture.navigation))
assert(#rope_graph.rope_nodes > 0 and rope_graph.rope_nodes[1].node == #rope_graph.platforms + 1,
    "rope nodes must be appended after the platform nodes")
assert(rope_graph.rope_nodes[1].rope == 1 and rope_graph.rope_nodes[1].y < rope_graph.rope_nodes[2].y,
    "rope nodes must carry the rope index and rise along the rope")
assert(terrain.platform_at(rope_graph, 130, 60, 0) == 1,
    "sloped platform height must be interpolated for the rope launch point")
local climb_path = assert(terrain.plan(rope_graph, 1, 2))
assert(#climb_path == 7, "sloped platform -> rope -> upper platform must plan grab, five climbs and leave")
local rope_grab = climb_path[1]
assert(rope_grab.kind == "rope_grab" and rope_grab.from == 1
    and rope_grab.to == rope_graph.rope_nodes[6].node
    and rope_grab.x == 260 and rope_grab.destination == 330
    and rope_grab.grab_y == -60 and rope_grab.rise == -60 and rope_grab.rope_index == 1,
    "rope_grab must launch from the interpolated sloped edge at the 70px horizontal boundary")
for index = 2, #climb_path - 1 do
    local edge = climb_path[index]
    assert(edge.kind == "rope_climb" and edge.x == 330 and edge.destination == 330
        and edge.rise == -40 and edge.target_y == rope_grab.grab_y - 40 * (index - 1),
        "rope_climb must step between adjacent 40px rope nodes")
end
local rope_leave = climb_path[#climb_path]
assert(rope_leave.kind == "rope_leave" and rope_leave.to == 2 and rope_leave.x == 330
    and rope_leave.destination == 330 and rope_leave.rise == -10,
    "rope_leave must jump onto a platform above the rope node")
local rope_only_blocked = {}
for from = 1, #rope_graph.platforms do
    for to = 1, #rope_graph.platforms do
        for _, kind in ipairs({"drop", "downjump", "jumpup", "horizontal_jump", "walk", "step"}) do
            rope_only_blocked[("%d:%d:%s"):format(from, to, kind)] = true
        end
    end
end
local descend_path = assert(terrain.plan(rope_graph, 1, 3, {blocked=rope_only_blocked}))
assert(#descend_path == 2 and descend_path[1].kind == "rope_grab" and descend_path[1].rise == 20
    and descend_path[2].kind == "rope_leave" and descend_path[2].to == 3 and descend_path[2].rise == 180,
    "rope_leave must also support landing below the rope node")

-- 抓绳判定边界：水平 71px 与整体高于起跳窗口的绳都不可抓。
local farther_rope = dofile("bot/test/fixtures/rope_terrain.lua").navigation
farther_rope.ropes[1].x = 331
local farther_path, farther_reason = terrain.plan(assert(terrain.build(farther_rope)), 1, 2)
assert(farther_path == nil and farther_reason == "no_path", "a rope 71px away must not be grabbable")
local high_rope = dofile("bot/test/fixtures/rope_terrain.lua").navigation
high_rope.ropes[1].y1, high_rope.ropes[1].y2 = -500, -400
local high_path, high_reason = terrain.plan(assert(terrain.build(high_rope)), 1, 3)
assert(high_path == nil and high_reason == "no_path", "a rope entirely above the grab window must not be grabbable")
local boundary_rope = dofile("bot/test/fixtures/rope_terrain.lua").navigation
boundary_rope.ropes[1].y1, boundary_rope.ropes[1].y2 = -75, 100
assert(terrain.plan(assert(terrain.build(boundary_rope)), 1, 3),
    "a rope node exactly on the grab window edge must be grabbable")

local function rope_navigation(platforms, ropes, walls)
    return {
        model = synthetic.navigation.model,
        terrain_left = 0,
        terrain_right = 1200,
        platforms = platforms,
        walls = walls or {},
        ropes = ropes,
        candidates = {walk = {}, step = {}, jumpup = {}, drop = {}, rope = {}},
    }
end

-- 从平台上沿下落 220px 内抓绳；墙挡住直接 downjump，确保路径只能走绳。
local fall_platforms = {
    {index=1, left=0, right=100, open_left=true, open_right=true, segments={0,100,-500,-500}},
    {index=2, left=0, right=100, open_left=true, open_right=true, segments={0,100,200,200}},
}
local block_wall = {50, -1000, 1000}
local fall_rope = {index=1, x=150, y1=-280, y2=0, platforms={}}
local fall_graph = assert(terrain.build(rope_navigation(fall_platforms, {fall_rope}, block_wall)))
local fall_path = assert(terrain.plan(fall_graph, 1, 2))
assert(#fall_path == 2 and fall_path[1].kind == "rope_grab" and fall_path[1].grab_y == -280
    and fall_path[1].rise == 220 and fall_path[2].kind == "rope_leave" and fall_path[2].to == 2,
    "a falling grab up to 220px below the launch must be reachable")
local too_low_rope = {index=1, x=150, y1=-270, y2=0, platforms={}}
local too_low_graph = assert(terrain.build(rope_navigation(fall_platforms, {too_low_rope}, block_wall)))
local too_low_path, too_low_reason = terrain.plan(too_low_graph, 1, 2)
assert(too_low_path == nil and too_low_reason == "no_path",
    "a rope top more than 220px below the launch must not be grabbable")

-- rope_leave 跳离上升上限 19px 与水平超距。
local leave_platforms = {
    {index=1, left=0, right=100, open_left=true, open_right=true, segments={0,100,0,0}},
    {index=2, left=100, right=200, open_left=true, open_right=true, segments={100,200,-139,-139}},
}
local leave_rope = {index=1, x=150, y1=-120, y2=100, platforms={}}
local leave_graph = assert(terrain.build(rope_navigation(leave_platforms, {leave_rope})))
local rise19_path = assert(terrain.plan(leave_graph, 1, 2))
local rise19 = rise19_path[#rise19_path]
assert(rise19.kind == "rope_leave" and rise19.to == 2 and rise19.rise == -19
    and rise19.destination == 150, "rope_leave must allow landing 19px above the rope node")
leave_platforms[2].segments = {100, 200, -140, -140}
local rise20_path, rise20_reason = terrain.plan(assert(terrain.build(
    rope_navigation(leave_platforms, {leave_rope}))), 1, 2)
assert(rise20_path == nil and rise20_reason == "no_path",
    "rope_leave must reject landings more than 19px above the rope node")
local overshoot_platforms = {
    {index=1, left=0, right=100, open_left=true, open_right=true, segments={0,100,0,0}},
    {index=2, left=400, right=600, open_left=true, open_right=true, segments={400,600,200,200}},
}
local overshoot_path, overshoot_reason = terrain.plan(assert(terrain.build(
    rope_navigation(overshoot_platforms, {leave_rope}))), 1, 2)
assert(overshoot_path == nil and overshoot_reason == "no_path",
    "rope_leave must reject a platform beyond the horizontal airtime reach")
overshoot_platforms[2].left, overshoot_platforms[2].right = 200, 420
overshoot_platforms[2].segments = {200, 420, 200, 200}
local reach_path = assert(terrain.plan(assert(terrain.build(
    rope_navigation(overshoot_platforms, {leave_rope}))), 1, 2))
assert(#reach_path == 2 and reach_path[2].kind == "rope_leave" and reach_path[2].to == 2
    and reach_path[2].destination == 208 and reach_path[2].rise >= 100,
    "rope_leave must reach a platform inside the horizontal airtime envelope")

-- 端到端：真实地图 103030100 中间绳链（R3->R4->R5->R6）。
local chain_fixture = dofile("bot/test/fixtures/map_103030100.lua")
local chain_graph = assert(terrain.build(chain_fixture.navigation))
local left_detour = assert(terrain.plan(chain_graph, 1, 3))
assert(left_detour[#left_detour].kind == "horizontal_jump" and left_detour[#left_detour].from == 2
    and left_detour[#left_detour].to == 3,
    "unblocked plan(1,3) must keep using the left detour onto P3")
local chain_path = assert(terrain.plan(chain_graph, 1, 3, {blocked = {["1:15"]=true, ["15:2"]=true, ["2:3"]=true}}))
local chain_hops, chain_ropes = 0, {}
for _, edge in ipairs(chain_path) do
    if edge.kind == "rope_hop" then
        chain_hops = chain_hops + 1
        chain_ropes[#chain_ropes + 1] = edge.rope_index
    end
end
assert(chain_path[1].kind == "rope_grab" and chain_path[1].rope_index == 3
    and chain_path[1].x == 1267 and chain_path[1].grab_y == 128,
    "blocked left detour must grab R3 from the ground platform")
assert(chain_hops >= 2 and chain_ropes[1] == 4 and chain_ropes[#chain_ropes] == 6,
    "middle chain must hop R3->R4->R5->R6 in order")
assert(chain_path[#chain_path].kind == "rope_leave" and chain_path[#chain_path].to == 3
    and chain_path[#chain_path].destination == 1547,
    "middle chain must leave R6 onto P3 at the rope axis")
local function node_x(graph, index)
    if index <= #graph.platforms then
        local platform = graph.platforms[index]
        return (platform.left + platform.right) / 2
    end
    for _, node in ipairs(graph.rope_nodes) do
        if node.node == index then
            for _, rope in ipairs(graph.ropes) do
                if rope.index == node.rope then return rope.x end
            end
        end
    end
end
local function path_cost(graph, path, speed)
    local total = 0
    for _, edge in ipairs(path) do
        local dx = math.abs(node_x(graph, edge.to) - node_x(graph, edge.from))
        if edge.kind == "walk" then total = total + dx / speed
        elseif edge.kind == "step" then total = total + 0.05 + dx / speed
        elseif edge.kind == "jumpup" then total = total + 0.6 + dx / speed
        elseif edge.kind == "drop" then total = total + 0.4 + dx / speed
        elseif edge.kind == "rope" then total = total + 0.8 + math.abs(edge.rise) / 100
        elseif edge.kind == "horizontal_jump" then total = total + 0.8 + math.abs(edge.destination - edge.x) / speed
        elseif edge.kind == "downjump" then total = total + 0.6 + dx / speed
        elseif edge.kind == "rope_grab" then
            total = total + 0.3 + math.abs(edge.destination - edge.x) / 125 + math.abs(edge.rise) / 200
        elseif edge.kind == "rope_climb" then total = total + math.abs(edge.rise) / 100 + 0.02
        elseif edge.kind == "rope_hop" then
            total = total + 0.6 + math.abs(edge.destination - edge.x) / 162.5
                + math.abs(edge.grab_y - edge.leave_y) / 200
        elseif edge.kind == "rope_leave" then
            total = total + 0.3 + math.abs(edge.destination - edge.x) / 162.5 + math.abs(edge.rise) / 200
        end
    end
    return total
end
local middle_cost = path_cost(chain_graph, chain_path, 100)
local detour_cost = path_cost(chain_graph, left_detour, 100)
print(("rope chain: middle edges=%d cost=%.3f; left detour edges=%d cost=%.3f; ratio=%.2f")
    :format(#chain_path, middle_cost, #left_detour, detour_cost, middle_cost / detour_cost))
for index, edge in ipairs(chain_path) do
    print(("  %d %s %s->%s x=%s destination=%s rise=%s grab_y=%s leave_y=%s")
        :format(index, edge.kind, tostring(edge.from), tostring(edge.to), tostring(edge.x),
            tostring(edge.destination), tostring(edge.rise), tostring(edge.grab_y), tostring(edge.leave_y)))
end

-- 反向兜底：屏蔽旧绕行以及 P3 的直接 downjump/垂降后，plan(3,1) 经 R6->R5->R4->R3 回到 P1。
local reverse_blocked = {["1:15"]=true, ["15:2"]=true, ["2:3"]=true,
    ["3:2"]=true, ["2:15"]=true, ["15:1"]=true}
for to = 1, #chain_graph.platforms do
    if to ~= 3 then reverse_blocked["3:" .. to] = true end
end
for from = 1, #chain_graph.platforms do
    if from ~= 1 then reverse_blocked[from .. ":1"] = true end
end
for _, node in ipairs(chain_graph.rope_nodes) do
    if node.rope ~= 3 then reverse_blocked[node.node .. ":1"] = true end
    if node.rope ~= 6 then reverse_blocked["3:" .. node.node] = true end
end
local reverse_path = assert(terrain.plan(chain_graph, 3, 1, {blocked = reverse_blocked}))
local reverse_hops = {}
for _, edge in ipairs(reverse_path) do
    if edge.kind == "rope_hop" then reverse_hops[#reverse_hops + 1] = edge.rope_index end
end
assert(reverse_path[1].kind == "rope_grab" and reverse_path[1].rope_index == 6,
    "reverse chain must grab R6 from P3")
assert(#reverse_hops >= 2 and reverse_hops[1] == 5 and reverse_hops[#reverse_hops] == 3,
    "reverse chain must hop R6->R5->R4->R3")
assert(reverse_path[#reverse_path].kind == "rope_leave" and reverse_path[#reverse_path].to == 1
    and reverse_path[#reverse_path].x == 1267,
    "reverse chain must leave R3 onto the ground platform")
local reverse_kinds = {}
for _, edge in ipairs(reverse_path) do reverse_kinds[#reverse_kinds + 1] = edge.kind end
print(("rope chain reverse ok: edges=%d kinds=%s")
    :format(#reverse_path, table.concat(reverse_kinds, ",")))

print(("terrain ok: synthetic locations=8; map=%d platforms=%d candidates=%d character=(%d,%d) platform=%d path=%d->1 edges=%d kinds=%s")
    :format(real.map_id, #real_graph.platforms, candidate_count, character_x, character_y,
        character_platform, character_platform, #real_path, table.concat(real_path_kinds, ",")))

-- 禁边键兼容：navigation 数值经后端序列化为浮点（15.0）时，整数语义键 "15:2" 与主流程
-- 按原始数值 tostring 的 "15.0:2.0" 都必须能禁用对应边。
local function float_numbers(value)
    if type(value) == "number" then return value + 0.0 end
    if type(value) ~= "table" then return value end
    local copy = {}
    for key, item in pairs(value) do copy[key] = float_numbers(item) end
    return copy
end
local float_graph = assert(terrain.build(float_numbers(chain_fixture.navigation)))
local function path_has_edge(path, from, to)
    for _, edge in ipairs(path or {}) do
        if edge.from == from and edge.to == to then return true end
    end
    return false
end
local mini_navigation = {
    model = {stand_height = 70, wall_margin = 12, min_platform_width = 16, jump_rise = 75,
        drop_min = 4, drop_max = 65, rope_grab = 76},
    terrain_left = 0, terrain_right = 200,
    platforms = {
        {index = 1, left = 0, right = 100, open_left = false, open_right = true,
            segments = {0, 100, 100, 100}},
        {index = 2, left = 120, right = 200, open_left = true, open_right = false,
            segments = {120, 200, 120, 120}},
    },
    walls = {}, ropes = {},
    candidates = {walk = {}, step = {1.0, 2.0, 92.0, 128.0, 20.0}, jumpup = {}, drop = {}, rope = {}},
}
local mini_graph = assert(terrain.build(mini_navigation))
local mini_plain = assert(terrain.plan(mini_graph, 1, 2, {}))
assert(mini_plain[1].kind == "step" and mini_plain[1].from == 1 and mini_plain[1].to == 2,
    "float navigation keeps the native 1->2 step edge")
assert(not path_has_edge(terrain.plan(mini_graph, 1, 2, {blocked = {["1:2"] = true}}), 1, 2),
    "integer blocked key suppresses a float-id native edge")
-- Lua 5.1 的 tostring(1.0) 输出 "1"，与客户端运行时（tostring(1.0) 输出 "1.0"）不同；
-- 原始 tostring 键的兼容分支由 edge_blocked 的第二种格式覆盖，这里无法在 5.1 下构造该键。
print("terrain blocked key compatibility ok")
