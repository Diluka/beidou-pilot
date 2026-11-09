local deadline = game.time() + options.seconds
local initial = travel_initial()
align_to_x(initial, options.x, options.tolerance, options.y_tolerance,
           deadline, options.min_hp_ratio)
game.stop()
