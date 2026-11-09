local initial = travel_initial()
local deadline = game.time() + options.seconds
local function transitioned(s)
    if s.map_id ~= initial.map_id then
        assert(options.target_map == 999999999 or s.map_id == options.target_map, "portal_unexpected_map")
        return true
    end
    return options.destination_x and options.destination_y
        and math.abs(s.position.x - options.destination_x) <= 80
        and math.abs(s.position.y - options.destination_y) <= 80
        and math.abs(s.position.x - options.x) + math.abs(s.position.y - options.y) > 60
end
local state, _, arrived = align_to_x(initial, options.x, options.tolerance, options.y_tolerance,
                                     deadline, options.min_hp_ratio, transitioned)
if arrived then game.stop(); return end
assert(math.abs(state.position.y - options.y) <= options.y_tolerance, "portal_other_layer")
assert(deadline - game.time() >= 0.4, "travel_budget_exhausted")
-- 只派发一次进入动作；转场期间只等待原生状态，不重发Up。
game.move("up", 0.18)
game.sleep(0.15)
local confirmation_deadline = math.max(deadline, game.time() + 2.5)
while game.time() < confirmation_deadline do
    state = travel_state(initial, options.min_hp_ratio, confirmation_deadline, true)
    if transitioned(state) then game.stop(); return end
    game.sleep(0.05)
end
error("portal_transition_unconfirmed")
