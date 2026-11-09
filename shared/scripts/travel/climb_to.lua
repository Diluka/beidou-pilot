local initial = travel_initial()
local deadline = game.time() + options.seconds
local direction = options.direction or (options.y < initial.position.y and "up" or "down")
assert(not (direction == "up" and options.y > initial.position.y + options.tolerance)
       and not (direction == "down" and options.y < initial.position.y - options.tolerance), "invalid_climb_direction")
local state = align_to_x(initial, options.x, 5, 45, deadline, options.min_hp_ratio)
if math.abs(state.position.y - options.y) <= options.tolerance then return end
local stop_y = options.y
if direction == "up" and options.rope_top then stop_y = math.min(stop_y, options.rope_top - 2) end
for attempt = 1, 2 do
    if deadline - game.time() < 1 then break end
    local hold = math.max(0.05, math.min(9, deadline - game.time() - 0.7, math.abs(stop_y - state.position.y) / 90 + 1.5))
    if direction == "up" then game.jump() end
    local hold_deadline = math.min(deadline, game.time() + hold)
    while game.time() < hold_deadline do
        state = travel_state(initial, options.min_hp_ratio, deadline, false)
        assert(math.abs(state.position.x - options.x) <= 18, "outside_safe_x")
        if (direction == "up" and state.position.y <= stop_y)
           or (direction == "down" and state.position.y >= stop_y) then break end
        game.move(direction, math.max(0.05, math.min(0.15, hold_deadline - game.time())))
    end
    game.stop()
    game.sleep(0.3)
    state = travel_state(initial, options.min_hp_ratio, deadline, false)
    if math.abs(state.position.y - options.y) <= options.tolerance and math.abs(state.position.x - options.x) <= 18 then return end
    if attempt == 1 and math.abs(state.position.y - initial.position.y) <= 35 then
        state = align_to_x(initial, options.x, 5, 45, deadline, options.min_hp_ratio)
    else
        break
    end
end
error("climb_not_confirmed")
