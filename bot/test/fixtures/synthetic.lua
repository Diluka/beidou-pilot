return {
    map_id = 102000000,
    model = {
        stand_height = 70,
        wall_margin = 12,
        min_platform_width = 16,
        jump_rise = 75,
        drop_min = 4,
        drop_max = 65,
        rope_grab = 95,
    },
    terrain_left = 0,
    terrain_right = 300,
    platforms = {
        {index = 1, left = 0, right = 100, open_left = true, open_right = false, segments = {0, 100, 100, 100}},
        {index = 2, left = 100, right = 180, open_left = false, open_right = false, segments = {100, 180, 80, 80}},
        {index = 3, left = 180, right = 260, open_left = false, open_right = false, segments = {180, 260, 120, 120}},
        {index = 4, left = 260, right = 300, open_left = false, open_right = true, segments = {260, 300, 160, 160}},
    },
    walls = {100, 80, 100},
    ropes = {
        {index = 1, x = 260, y1 = 120, y2 = 160, platforms = {3, 120, 4, 160}},
    },
    candidates = {
        walk = {1, 2, 100, 120, 20},
        step = {2, 3, 180, 200, -40},
        jumpup = {1, 2, 90, 150, 20},
        drop = {2, 3, 170, 200, 40},
        rope = {3, 4, 260, 260, 40, 1},
    },
}
