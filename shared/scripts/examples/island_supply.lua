-- 已知路线示例：50000东上层落向城镇入口，返回50000东下层。
-- 静态坐标来自同源Map资料；实际通行和终点由本次客户端重新确认。
local island_supply = {}
function island_supply.to_town(options)
    options = options or {}
    local route = travel.begin({
        name = "island-supply-to-town",
        seconds = options.seconds or 30,
        min_hp_ratio = options.min_hp_ratio or 0.5,
        start_map = 50000,
        start = { min_x = 1100, max_x = 1350, min_y = -95, max_y = -75 },
        destination_map = 1000000,
        destination = { min_x = -90, max_x = -40, min_y = 264, max_y = 284 },
    })
    route:walk(1340, 10, "east-upper-platform")
    -- 上层到x1389结束；下层地面连续至x1530，保留边缘空间后声明落区。
    route:drop_to(1398, { min_x = 1390, max_x = 1500, min_y = 270, max_y = 280 }, "east-portal-platform")
    route:portal(1420, 275, 1000000, "enter-town")
    return route:finish()
end
function island_supply.to_field(options)
    options = options or {}
    local route = travel.begin({
        name = "island-supply-to-field",
        seconds = options.seconds or 20,
        min_hp_ratio = options.min_hp_ratio or 0.5,
        start_map = 1000000,
        start = { min_x = -100, max_x = 20, min_y = 264, max_y = 284 },
        destination_map = 50000,
        destination = { min_x = 1400, max_x = 1440, min_y = 265, max_y = 285 },
    })
    route:portal(-66, 274, 50000, "return-field")
    return route:finish()
end
