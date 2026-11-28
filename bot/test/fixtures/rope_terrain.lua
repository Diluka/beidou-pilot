-- 合成绳通道地形：斜面平台 -> 悬空绳 -> 上层/下层平台。
-- 平台 1 是从 (0,120) 斜到 (260,0) 的斜坡，绳 1 在 x=330，
-- 因此从平台右端 x=260 抓绳时水平距离正好是 70px 的判定边界。
return {
    map_id = 900000001,
    scene_generation = 1,
    navigation = {
        model = {
            stand_height = 70,
            wall_margin = 12,
            min_platform_width = 16,
            jump_rise = 75,
            drop_min = 4,
            drop_max = 65,
            rope_grab = 76,
        },
        terrain_left = 0,
        terrain_right = 1600,
        platforms = {
            {index = 1, left = 0, right = 260, open_left = true, open_right = true, segments = {0, 260, 120, 0}},
            {index = 2, left = 300, right = 520, open_left = true, open_right = true, segments = {300, 520, -270, -270}},
            {index = 3, left = 300, right = 520, open_left = true, open_right = true, segments = {300, 520, 200, 200}},
        },
        walls = {},
        ropes = {
            {index = 1, x = 330, y1 = -260, y2 = 40, platforms = {}},
        },
        candidates = {walk = {}, step = {}, jumpup = {}, drop = {}, rope = {}},
    },
}
