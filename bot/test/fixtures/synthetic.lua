local platforms = {
    {index = 1, x1 = 0, x2 = 100, y1 = 100, y2 = 100},
    {index = 2, x1 = 100, x2 = 180, y1 = 80, y2 = 80},
    {index = 3, x1 = 180, x2 = 260, y1 = 120, y2 = 120},
    {index = 4, x1 = 260, x2 = 300, y1 = 120, y2 = 160},
}

return {
    map_id = 102000000,
    model = {
        name = "synthetic",
        platforms = platforms,
    },
    platforms = platforms,
    walls = {
        {x = 100, y1 = 80, y2 = 100},
    },
    ropes = {
        {index = 1, x = 280, y1 = 100, y2 = 160},
    },
    candidates = {
        {kind = "walk", from = 1, to = 1, x = 50, destination = {x = 60, y = 100}},
        {kind = "step", from = 1, to = 2, x = 100, destination = {x = 120, y = 80}, rise = 20},
        {kind = "jumpup", from = 1, to = 2, x = 150, destination = {x = 150, y = 80}, rise = 20},
        {kind = "drop", from = 2, to = 3, x = 190, destination = {x = 200, y = 120}, rise = -40},
        {kind = "rope", from = 3, to = 4, x = 280, destination = {x = 280, y = 160}, rope_index = 1},
    },
}
