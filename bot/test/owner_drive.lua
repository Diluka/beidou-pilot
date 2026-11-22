-- @tick.gear 4
-- @tick.budget_ms 100
-- The CLI owns --seconds; its current default is 30s, so acceptance passes it explicitly.

local right_seconds = 2
local left_seconds = 2
local jump_window_seconds = 0.1
local cycle_seconds = right_seconds + left_seconds + jump_window_seconds

local function main(context)
    if context.state.started_at == nil then
        context.state.started_at = context.tick.time
    end

    local elapsed = context.tick.time - context.state.started_at
    local cycle = math.floor(elapsed / cycle_seconds)
    local phase = elapsed - cycle * cycle_seconds
    local player = context.game.player

    if phase < right_seconds then
        context.state.jump_cycle = nil
        assert(player.skill(nil))
        assert(player.move("right"))
    elseif phase < right_seconds + left_seconds then
        context.state.jump_cycle = nil
        assert(player.skill(nil))
        assert(player.move("left"))
    elseif phase < right_seconds + left_seconds + jump_window_seconds then
        assert(player.move(nil))
        if context.state.jump_cycle ~= cycle then
            assert(player.jump())
            context.state.jump_cycle = cycle
        else
            assert(player.skill(nil))
        end
    else
        assert(player.skill(nil))
        assert(player.move(nil))
    end
end
