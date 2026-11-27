-- Passive estimates only: the caller supplies the selected combat target and action results.
local storage = require('lib.metrics_storage')
local io_module = require('lib.io')
local defaults = require('defaults')
local M = {}
local NULL = {}

local function encode(v)
    if v == NULL or v == nil then return 'null' end
    local t = type(v)
    if t == 'number' then return (v == v and v ~= math.huge and v ~= -math.huge) and string.format('%.14g', v) or 'null' end
    if t == 'boolean' then return v and 'true' or 'false' end
    if t == 'string' then
        return '"' .. v:gsub('[%z\1-\31\\"]', function(c)
            local e = {['\\']='\\\\', ['"']='\\"', ['\n']='\\n', ['\r']='\\r', ['\t']='\\t'}
            return e[c] or string.format('\\u%04x', c:byte())
        end) .. '"'
    end
    local keys, parts = {}, {}
    for k in pairs(v) do keys[#keys + 1] = k end
    table.sort(keys)
    for _, k in ipairs(keys) do parts[#parts + 1] = encode(tostring(k)) .. ':' .. encode(v[k]) end
    return '{' .. table.concat(parts, ',') .. '}'
end

local function record(s, map, platform, mob, platform_observation)
    local key = encode(map) .. ':' .. encode(platform) .. ':' .. encode(mob)
    local r = s.current[key]
    if not r then
        r = {map_id=map or NULL, platform=platform or NULL, mob_template=mob or NULL,
            kills=NULL, kill_time_sum=NULL, kill_time_samples=NULL, exp=NULL, exp_unknown_kills=0,
            hp_potions=NULL, mp_potions=NULL, arrows=NULL, drops_seen=NULL, drops_picked=NULL,
            damage_taken=NULL, deaths=NULL, stuck_events=NULL, dwell_s=0, sample_windows=1,
            estimated=false, kill_source='target_disappearance_or_inactive', complete=false, completeness_reason='open',
            entries=NULL, arrival_reason=s.visit and s.visit.reason or NULL,
            collection_policy=s.visit and s.visit.policy or NULL, policy_seed=s.visit and s.visit.seed or NULL,
            visit_start=s.visit and s.visit.started or NULL, visit_end=NULL, exit_reason=NULL,
            scene_generation=s.scene or NULL, window_start=s.window_start or NULL, window_end=NULL}
        s.current[key] = r
    end
    if platform_observation and r.attribution == nil then
        r.attribution, r.estimated = 'platform_window', true
        r.exp_delta_observed, r.arrow_delta_observed = NULL, NULL
        r.hp_potion_delta_observed, r.mp_potion_delta_observed = NULL, NULL
        r.platform_complete = false
    end
    if s.visit and r.entries == NULL then
        if not s.visit.counted[key] then
            r.entries = 1
            s.visit.counted[key] = true
        else
            r.entries = 0
        end
    end
    return r
end

local function close_window(s, now, reason)
    for _, r in pairs(s.current) do
        r.window_end = now
        r.complete = reason == nil and s.complete == true
        if r.attribution == 'platform_window' then
            r.platform_complete = reason == nil or reason == 'platform_changed'
        end
        r.completeness_reason = reason or (r.complete and 'complete' or 'observation_unverified')
        r.insufficient = r.kills == NULL or r.kills < 5 or r.dwell_s < 60
        if r.exp_unknown_kills > 0 then r.exp = NULL end
        s.rows[#s.rows + 1] = encode(r)
    end
    s.current = {}
end

function M.new(path)
    local disk, err = storage.new(path)
    if not disk then return nil, err end
    return {disk=disk, rows={}, current={}, seen={}, last_write=nil}
end

-- Explicit visit metadata; absent policy/reasons remain unknown, never inferred.
function M.visit(s, data)
    if data.preserve_observation then
        s.visit = {reason=data.arrival_reason, policy=data.collection_policy, seed=data.policy_seed,
            started=s.now, counted={}}
        for key, r in pairs(s.current) do
            r.arrival_reason, r.visit_start = data.arrival_reason or NULL, s.now or NULL
            r.collection_policy, r.policy_seed = data.collection_policy or NULL, data.policy_seed or NULL
            r.entries, s.visit.counted[key] = 1, true
        end
        return
    end
    if s.window_start then
        for _, r in pairs(s.current) do
            r.exit_reason, r.visit_end = data.exit_reason or NULL, s.now or NULL
        end
        local reason
        if not data.exit_reason then reason = 'exit_reason_unknown' end
        close_window(s, s.now, reason)
    end
    s.previous, s.target, s.complete = nil, nil, false
    s.window_start = nil
    s.visit = {reason=data.arrival_reason, policy=data.collection_policy, seed=data.policy_seed,
        started=s.now, counted={}}
end

-- Selecting a target is not evidence of a kill. Call after combat.select.
function M.target(s, mob)
    if not mob or not mob.object_id then s.target = nil; return end
    if not s.target or s.target.object_id ~= mob.object_id or s.target.platform ~= mob.platform
        or s.target.template_id ~= mob.template_id then
        s.target = {object_id=mob.object_id, template_id=mob.template_id, platform=mob.platform,
            started=s.now, map=s.map, scene=s.scene}
        record(s, s.map, mob.platform, mob.template_id)
    end
end

function M.event(s, kind, data)
    data = data or {}
    local t = not data.unattributed and s.target or nil
    local r = record(s, data.map_id or s.map, data.platform or (t and t.platform) or s.platform,
        data.mob_template or (t and t.template_id))
    local fields = {hp_potion='hp_potions', mp_potion='mp_potions', damage='damage_taken',
        death='deaths', stuck='stuck_events', arrow='arrows'}
    if fields[kind] then
        local n = data.value or 1
        if type(n) ~= 'number' or n < 0 then return false, 'invalid_value' end
        local field = fields[kind]
        r[field] = (r[field] == NULL and 0 or r[field]) + n
    elseif kind == 'drop_seen' or kind == 'drop_picked' then
        if data.item_id == nil then return false, 'missing_item_id' end
        local field = kind == 'drop_seen' and 'drops_seen' or 'drops_picked'
        local item = tostring(data.item_id)
        if r[field] == NULL then r[field] = {} end
        r[field][item] = (r[field][item] or 0) + 1
    else return false, 'invalid_event' end
    return true
end

function M.observe(s, ctx, world)
    local now = ctx.tick and ctx.tick.time
    if type(now) ~= 'number' or now ~= now then return false, 'invalid_time' end
    local c = world.character or {}
    local native = ctx.game and ctx.game.character or {}
    local exp = native.experience or native.exp or c.exp
    local valid = world.ready == true and world.map_id ~= nil and world.scene_generation ~= nil
        and c.platform ~= nil
    local prev = s.previous
    local boundary = prev and (not valid or prev.map ~= world.map_id or prev.scene ~= world.scene_generation
        or prev.platform ~= c.platform or now < prev.time or now - prev.time > 2)
    if not s.started then
        io_module.event(ctx, 'metrics/reset', {reason='session_start'})
        s.started = true
    end
    local elapsed = s.window_start and now - s.window_start >= 20
    if s.window_start and boundary then
        for _, r in pairs(s.current) do
            r.visit_end, r.exit_reason = prev.time, 'scene_or_observation_changed'
        end
        local platform_changed = valid and prev.map == world.map_id and prev.scene == world.scene_generation
            and prev.platform ~= c.platform and now >= prev.time and now - prev.time <= 2
        close_window(s, prev.time, platform_changed and 'platform_changed' or 'scene_or_observation_changed')
        s.window_start = nil
    end
    if not valid then
        s.previous, s.target, s.visit, s.seen = nil, nil, nil, {}
        s.window_start = nil
        return M.flush(s, now, ctx)
    end
    if not s.window_start then
        s.window_start, s.scene = now, world.scene_generation
        s.complete = valid and type(world.mobs) == 'table' and world.metrics_complete == true
    else
        s.complete = s.complete and valid and type(world.mobs) == 'table' and world.metrics_complete == true
    end
    s.now, s.map, s.platform = now, world.map_id, c.platform
    local platform = record(s, world.map_id, c.platform, nil, true)
    local config = ctx.state and ctx.state.bot and ctx.state.bot.config or {}
    local item_ids = {arrow_delta_observed=config.ammo_item_id or defaults.ammo_item_id,
        hp_potion_delta_observed=config.hp_item or defaults.hp_item,
        mp_potion_delta_observed=config.mp_item or defaults.mp_item}
    local items, invalid_items = {}, {}
    local inventory = ctx.game and ctx.game.inventory
    if inventory and inventory.status == 'ok' and type(world.inventory) == 'table' then
        for _, item in ipairs(world.inventory) do
            if type(item.item_id) == 'number' then
                if type(item.quantity) == 'number' and item.quantity >= 0 and item.quantity == item.quantity then
                    items[item.item_id] = (items[item.item_id] or 0) + item.quantity
                else
                    invalid_items[item.item_id] = true
                end
            end
        end
    end
    for id in pairs(invalid_items) do items[id] = nil end
    local levels_ok = type(c.level) == 'number' and type(exp) == 'number' and exp >= 0
    local fields = {'exp_delta_observed', 'arrow_delta_observed', 'hp_potion_delta_observed', 'mp_potion_delta_observed'}
    for _, field in ipairs(fields) do
        local previous_value, current_value, available
        if field == 'exp_delta_observed' then
            current_value = exp
            previous_value = prev and prev.exp
            available = levels_ok and (not prev or boundary or (type(prev.exp) == 'number' and prev.level == c.level and exp >= prev.exp))
        else
            local id = item_ids[field]
            current_value = items[id]
            previous_value = prev and prev.items[id]
            local distinct = true
            for other, other_id in pairs(item_ids) do
                if other ~= field and other_id == id then distinct = false end
            end
            available = type(id) == 'number' and id > 0 and distinct and current_value ~= nil
                and (not prev or boundary or (prev.item_ids[field] == id and previous_value ~= nil))
        end
        local complete_field = field .. '_complete'
        if not available then
            platform[field], platform[complete_field] = NULL, false
        elseif platform[complete_field] ~= false then
            if platform[field] == NULL then platform[field] = 0 end
            platform[complete_field] = true
            if prev and not boundary then
                local delta = field == 'exp_delta_observed' and current_value - previous_value
                    or previous_value - current_value
                if delta > 0 then platform[field] = platform[field] + delta end
            end
        end
    end
    local exposures = {}
    if valid then
        for _, mob in ipairs(world.mobs or {}) do
            if mob.active == true and mob.platform == c.platform and mob.template_id ~= nil then
                local key = encode(mob.platform) .. ':' .. encode(mob.template_id)
                exposures[key] = {platform=mob.platform, template_id=mob.template_id}
            end
        end
    end
    if valid and prev and not boundary then
        platform.dwell_s = platform.dwell_s + now - prev.time
        for key, item in pairs(exposures) do
            if prev.exposures[key] then
                local exposure = record(s, world.map_id, item.platform, item.template_id)
                exposure.dwell_s = exposure.dwell_s + now - prev.time
                if s.complete and world.metrics_targets_complete == true and exposure.kills == NULL then exposure.kills = 0 end
            end
        end
        local t = s.target
        local r = record(s, prev.map, t and t.platform or prev.platform, t and t.template_id)
        if t and t.map == prev.map and t.scene == prev.scene then
            local found
            for _, mob in ipairs(world.mobs or {}) do if mob.object_id == t.object_id then found = mob; break end end
            if (found and (found.platform ~= t.platform or found.template_id ~= t.template_id))
                or (not found and (type(world.mobs) ~= 'table' or world.metrics_complete ~= true)) then
                s.complete, s.target = false, nil
            end
            if s.target and ((not found and world.metrics_complete == true) or (found and (found.active == false or (found.hp_percent and found.hp_percent <= 0)))) then
                r.kills, r.estimated = (r.kills == NULL and 0 or r.kills) + 1, true
                if t.started then
                    r.kill_time_sum = (r.kill_time_sum == NULL and 0 or r.kill_time_sum) + math.max(0, now - t.started)
                    r.kill_time_samples = (r.kill_time_samples == NULL and 0 or r.kill_time_samples) + 1
                end
                if not found then s.complete = false end -- disappearance can be lost visibility
                if world.metrics_exp_attributable == true and type(exp) == 'number'
                    and type(prev.exp) == 'number' and exp > prev.exp and c.level ~= nil and c.level == prev.level then
                    r.exp = (r.exp == NULL and 0 or r.exp) + exp - prev.exp
                else r.exp_unknown_kills = r.exp_unknown_kills + 1 end
                s.target = nil
            end
        end
        if type(prev.hp) == 'number' and type(c.hp) == 'number' then
            local risk = record(s, prev.map, prev.platform, nil)
            if c.hp < prev.hp then risk.damage_taken = (risk.damage_taken == NULL and 0 or risk.damage_taken) + prev.hp - c.hp end
            if c.hp <= 0 and prev.hp > 0 then risk.deaths = (risk.deaths == NULL and 0 or risk.deaths) + 1 end
        end
    elseif boundary then s.target = nil; s.seen = {}; s.visit = nil end
    if valid and type(world.drops) == 'table' then
        for _, d in ipairs(world.drops) do
            if d.object_id and not s.seen[d.object_id] then
                s.seen[d.object_id] = true
                if d.item_id then M.event(s, 'drop_seen', {item_id=d.item_id, platform=d.platform, unattributed=true}) end
            end
        end
    end
    s.previous = valid and {time=now,map=world.map_id,scene=world.scene_generation,platform=c.platform,
        hp=c.hp,exp=exp,level=c.level,exposures=exposures,items=items,item_ids=item_ids} or nil
    if elapsed and not boundary then
        close_window(s, now, nil)
        s.window_start, s.scene = now, world.scene_generation
        s.complete = valid and type(world.mobs) == 'table' and world.metrics_complete == true
    end
    return M.flush(s, now, ctx)
end

function M.flush(s, now, ctx)
    if not s.last_write then s.last_write = now; return true end
    if now - s.last_write < 20 then return true end
    local started = os.clock()
    local ok, err = storage.save(s.disk, s.rows)
    local rotation = s.disk.rotation
    if ctx and rotation and rotation.generation ~= s.reported_rotation then
        io_module.event(ctx, 'metrics/rotate', rotation)
        s.reported_rotation = rotation.generation
    end
    if not ok then
        s.last_write = now -- retry at the next interval; do not flood error events
        if ctx then io_module.event(ctx, 'metrics/error', {reason=err}) end
        return false, err
    end
    s.last_write = now
    if ctx then io_module.event(ctx, 'metrics/flush', {records=#s.rows, elapsed_ms=(os.clock()-started)*1000}) end
    return true
end

return M
