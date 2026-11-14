-- 由 CLI 显式装载，与调用者 Lua 组成同一 chunk；不解释动作表或探路。
travel = {}
local methods = {}
local function validate(condition, reason)
    if not condition then error("route_failed arrived=false stage=start reason=" .. reason) end
end
local function number(value) return type(value) == "number" and value == value and math.abs(value) < math.huge end
local function region(value, fail)
    local function check(condition, reason)
        if not condition then
            if fail then
                fail(reason)
            else
                validate(false, reason)
            end
        end
    end
    check(type(value) == "table", "route_region_required")
    local result = {}
    for _, key in ipairs({ "min_x", "max_x", "min_y", "max_y" }) do
        check(number(value[key]), "route_region_unknown")
        result[key] = value[key]
    end
    check(result.min_x <= result.max_x and result.min_y <= result.max_y, "route_region_invalid")
    return result
end
local function inside(s, area)
    return s.position.x >= area.min_x
        and s.position.x <= area.max_x
        and s.position.y >= area.min_y
        and s.position.y <= area.max_y
end
function methods:fail(reason) error("route_failed arrived=false stage=" .. self._stage .. " reason=" .. reason) end
function methods:stage(name)
    self._stage = name
    game.log("route_stage name=" .. self.name .. " stage=" .. name .. " arrived=false")
end
function methods:state(transition)
    if game.time() >= self.deadline then self:fail("budget_exhausted") end
    local control = game.tasks().control
    if
        control.owner and control.owner ~= self.owner
        or control.from
            and control.from ~= self.owner
            and (control.from ~= self.previous_control.from or control.to ~= self.previous_control.to or control.reason ~= self.previous_control.reason)
    then
        self:fail("control_preempted")
    end
    return travel_state(
        self.initial,
        self.min_hp_ratio,
        self.deadline,
        transition,
        function(reason) self:fail(reason) end
    )
end
function methods:action(result)
    if result.reason == "control_not_owned" then self:fail("control_not_owned") end
    return travel_action(result, function(reason) self:fail(reason) end)
end
function methods:stop()
    self:state()
    if game.tasks().control.owner then self:action(game.stop()) end
end
function methods:walk(x, y_tolerance, label)
    self:stage(label or "walk")
    if not number(x) or not number(y_tolerance or 10) or (y_tolerance or 10) < 0 then
        self:fail("unknown_walk_target")
    end
    local initial = self:state()
    align_to_x(
        initial,
        x,
        4,
        y_tolerance or 10,
        self.deadline,
        self.min_hp_ratio,
        nil,
        function(reason) self:fail(reason) end
    )
    self:state()
    return self
end
function methods:drop_to(x, landing, label)
    self:stage(label or "drop")
    local initial = self:state()
    landing = region(landing, function(reason) self:fail(reason) end)
    if not number(x) or x < landing.min_x or x > landing.max_x or landing.min_y <= initial.position.y + 10 then
        self:fail("unknown_drop_target")
    end
    -- 出边点和下层落区是不同事实。只在出边前推进；观察到下降后释放输入，
    -- 允许正常空中余速进入已知落区，到达并复采后才由后续walk/portal对齐。
    local direction = x >= initial.position.x and 1 or -1
    local left, right =
        math.min(initial.position.x - 10, landing.min_x), math.max(initial.position.x + 10, landing.max_x)
    local progress_at, nearest, falling = game.time(), math.huge, false
    self:stop()
    while game.time() < self.deadline do
        local s = self:state()
        if
            s.position.x < left
            or s.position.x > right
            or s.position.y < initial.position.y - 10
            or s.position.y > landing.max_y
        then
            self:fail("drop_left_known_corridor")
        end
        local distance = math.max(0, (x - s.position.x) * direction) + math.max(0, landing.min_y - s.position.y)
        if distance < nearest - 2 then
            progress_at, nearest = game.time(), distance
        end
        if inside(s, landing) then
            self:stop()
            game.sleep(0.2)
            local after = self:state()
            if inside(after, landing) and math.abs(after.position.y - s.position.y) <= 2 then
                game.log(
                    string.format("route_drop phase=region_confirmed x=%.1f y=%.1f", after.position.x, after.position.y)
                )
                return self
            end
        elseif falling or s.position.y > initial.position.y + 5 then
            if not falling then
                self:stop()
                falling = true
                game.log(string.format("route_drop phase=falling x=%.1f y=%.1f", s.position.x, s.position.y))
            end
            game.sleep(0.05)
        else
            local distance_x = (x - s.position.x) * direction
            if distance_x > 3 then
                self:action(game.move(direction > 0 and "right" or "left", math.min(0.08, distance_x / 150)))
            end
            self:stop()
            game.sleep(0.05)
        end
        if game.time() - progress_at >= 3 then self:fail("drop_no_progress") end
    end
    self:fail("budget_exhausted")
end
function methods:portal(x, y, target_map, label)
    self:stage(label or "portal")
    local initial = self:state()
    if
        not number(x)
        or not number(y)
        or not number(target_map)
        or target_map % 1 ~= 0
        or target_map < 0
        or target_map == 999999999
        or target_map == initial.map_id
    then
        self:fail("unknown_portal_target")
    end
    if math.abs(initial.position.y - y) > 10 then self:fail("portal_other_layer") end
    align_to_x(initial, x, 4, 10, self.deadline, self.min_hp_ratio, nil, function(reason) self:fail(reason) end)
    self:action(game.move("up", 0.18))
    while game.time() < self.deadline do
        local s = self:state(true)
        if s.map_id == target_map then
            self.initial = s
            self:stop()
            return self
        end
        if s.map_id ~= initial.map_id or s.scene_generation ~= initial.scene_generation then
            self:fail("unexpected_transition")
        end
        game.sleep(0.05)
    end
    self:fail("portal_unconfirmed")
end
function methods:finish()
    self:stage("destination")
    self:stop()
    local before = self:state()
    local until_at = math.min(self.deadline, game.time() + 3)
    while game.time() < until_at do
        game.sleep(0.2)
        local after = self:state()
        if
            after.map_id == self.destination_map
            and inside(before, self.destination)
            and inside(after, self.destination)
            and math.abs(after.position.y - before.position.y) <= 2
        then
            self:stage("arrived")
            game.log("route_result name=" .. self.name .. " arrived=true map_id=" .. after.map_id)
            return { arrived = true, stage = "arrived", map_id = after.map_id, position = after.position }
        end
        before = after
    end
    self:fail("destination_unconfirmed")
end
function travel.begin(spec)
    validate(type(spec) == "table" and type(spec.name) == "string", "route_spec_required")
    validate(number(spec.seconds) and spec.seconds >= 1 and spec.seconds <= 600, "route_budget_invalid")
    validate(
        number(spec.start_map)
            and spec.start_map % 1 == 0
            and number(spec.destination_map)
            and spec.destination_map % 1 == 0
            and spec.start_map >= 0
            and spec.destination_map >= 0
            and spec.start_map ~= 999999999
            and spec.destination_map ~= 999999999,
        "route_map_unknown"
    )
    local hp = spec.min_hp_ratio or 0.25
    validate(number(hp) and hp >= 0 and hp <= 1, "route_hp_limit_invalid")
    local self = {
        name = spec.name,
        deadline = game.time() + spec.seconds,
        min_hp_ratio = hp,
        destination_map = spec.destination_map,
        destination = region(spec.destination),
    }
    local start = region(spec.start)
    for name, fn in pairs(methods) do
        self[name] = fn
    end
    self:stage("start")
    local tasks = game.tasks()
    self.previous_control = tasks.control
    self.owner = tasks.control.owner or (#tasks.tasks == 1 and tasks.tasks[1].name)
    if not self.owner then self:fail("control_not_owned") end
    local s = game.state()
    if not s.ready or not s.character or not s.position then self:fail("observation_unavailable") end
    self.initial = s
    self:state()
    if s.map_id ~= spec.start_map or not inside(s, start) then self:fail("inapplicable_start") end
    return self
end
