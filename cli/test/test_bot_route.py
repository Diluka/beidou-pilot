"""bot_route 生成跨图航点表的离线合同。"""

import ctypes
import ctypes.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools import bot_route


class BotRouteContract(unittest.TestCase):
    def test_route_legs_become_waypoints(self) -> None:
        response = {
            "ok": True,
            "data": {
                "status": "ok",
                "legs": [
                    {"from": 10000, "portal": "out00", "portal_at": [[1077, 480]], "to": 20000},
                    {"from": 20000, "portal": "out00", "portal_at": [[630, 210]], "to": 30000},
                ],
            },
        }
        with patch.object(
            bot_route.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")
        ):
            waypoints = bot_route.build_route(Path("/repo"), "dev/hero", 10000, 30000)
        self.assertEqual(
            [
                {"map": 10000, "portal": "out00", "x": 1077, "y": 480},
                {"map": 20000, "portal": "out00", "x": 630, "y": 210},
            ],
            waypoints,
        )

    def test_no_route_fails(self) -> None:
        response = {"ok": True, "data": {"status": "no_route", "error": "no_route", "legs": []}}
        with patch.object(
            bot_route.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")
        ):
            with self.assertRaises(bot_route.RouteError):
                bot_route.build_route(Path("/repo"), "dev/hero", 50000, 104040000)

    def test_invalid_json_fails(self) -> None:
        with patch.object(bot_route.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "not json", "")):
            with self.assertRaises(bot_route.RouteError):
                bot_route.build_route(Path("/repo"), "dev/hero", 1, 2)

    def test_workbench_must_have_partition(self) -> None:
        with self.assertRaises(SystemExit):
            bot_route.main(["hero", "1", "2"])


class TravelLuaContract(unittest.TestCase):
    def run_lua(self, scenario: str) -> None:
        library = ctypes.util.find_library("lua5.4")
        if not library:
            self.skipTest("Lua 5.4 shared library unavailable")
        lua = ctypes.CDLL(library)
        lua.luaL_newstate.restype = ctypes.c_void_p
        lua.luaL_openlibs.argtypes = [ctypes.c_void_p]
        lua.luaL_loadstring.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        lua.luaL_loadstring.restype = ctypes.c_int
        lua.lua_pcallk.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_longlong,
            ctypes.c_void_p,
        ]
        lua.lua_pcallk.restype = ctypes.c_int
        lua.lua_tolstring.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        lua.lua_tolstring.restype = ctypes.c_char_p
        lua.lua_close.argtypes = [ctypes.c_void_p]
        travel = (Path(__file__).resolve().parents[2] / "bot/travel.lua").read_text(encoding="utf-8")
        source = (
            r"""
local builds, moves, stops = 0, {}, 0
local no_path, fail_move = false, false
local plans, steps = {}, 0
local missing_character_platform, missing_target_platform = false, false
package.loaded["lib.terrain"] = {
    build = function(nav) builds = builds + 1; return {model = {stand_height = 1}, nav = nav} end,
    platform_at = function(graph, x)
        if x < 50 then if missing_character_platform then return nil end; return 1 end
        if missing_target_platform then return nil end; return 2
    end,
    plan = function(graph, from, to, options)
        plans[#plans + 1] = options.blocked
        if no_path then return nil, "no_path" end
        return {{from=1, to=2, kind="rope"}}
    end,
}
package.loaded["lib.move"] = {
    new = function(graph) return {graph = graph} end,
    set_path = function(mover, edges) mover.edges, mover.index = edges, 1; return true end,
    step = function() steps = steps + 1; if fail_move then return "failed", "no_progress" end; return "running" end,
}
package.loaded["lib.world"] = {observe = function(c) return c.world end}
package.loaded["lib.sustain"] = {step = function() return false end}
local c = {
    state = {goal = 3, legs = {{map=1, x=0, y=0, portal="a"}, {map=2, x=0, y=0, portal="b"}}},
    world = {ready=true, map_id=1, character={x=0, y=0}},
    scene = {scene_generation=1, terrain={status="available", navigation={}}}, tick={time=0, index=1},
    game = {player={move=function(key) moves[#moves+1]=key or "release" end,
        stop=function() stops=stops+1 end}, character={}, log=function() end},
}
package.path = "bot/?.lua;" .. package.path
c.state.travel = c.state
local main = assert(load([==[
"""
            + travel
            + r"""
return main
]==]))()
"""
            + scenario
        )
        state = lua.luaL_newstate()
        try:
            lua.luaL_openlibs(state)
            rc = lua.luaL_loadstring(state, source.encode())
            if rc == 0:
                rc = lua.lua_pcallk(state, 0, 0, 0, 0, None)
            self.assertEqual(0, rc, lua.lua_tolstring(state, -1, None) if rc else None)
        finally:
            lua.lua_close(state)

    def test_portal_retry_waits_for_map_change_and_rebuilds_graph(self) -> None:
        self.run_lua(r"""
main(c)
c.tick.time = 0.3; main(c)
assert(c.state.index == 1, "must not advance without a map transition")
c.tick.time = 3.1; main(c)
assert(c.state.index == 1 and c.state.retries == 1, "portal timeout must retry the same leg")
main(c)
assert(moves[#moves] == "up", "retry must attempt the portal again")
c.world.map_id = 2; c.scene.terrain.navigation = {}; main(c)
main(c)
assert(c.state.index == 2, "map transition must advance exactly one leg")
assert(builds == 3, "retry and new map require fresh navigation graphs")
c.tick.time = 3.4; main(c)
assert(c.state.index == 2, "last leg must also wait for a transition")
c.world.map_id = 3; main(c)
local status = main(c)
assert(status == "done", "route completes only after the last map transition")
assert(stops > 0, "completion must release input")
""")

    def test_real_mover_long_edges_remain_bounded(self) -> None:
        self.run_lua(r"""
local move = assert(loadfile("bot/lib/move.lua"))()
game = {player={move=function() return true end, skill=function() return true end,
    jump=function() return true end}, character={movement={max_speed=100}}}
local ctx = {game=game, tick={time=0, index=0}}
local world = {character={x=0, y=0, on_ground=true}}
local function tick(mover, t, x)
    ctx.tick.time, ctx.tick.index, world.character.x = t, ctx.tick.index + 1, x
    return move.step(mover, ctx, world)
end
local function begin(edge)
    ctx.tick.time, world.character.x = 0, 0
    local mover = move.new({})
    assert(move.set_path(mover, {edge}))
    return mover
end
local mover = begin({kind="drop", from=1, to=2, destination=1000})
for t=0, 11 do assert(tick(mover, t, t * 6) == "running", "long drop must continue past 10 seconds") end
local status, reason
for t=12, 30 do status, reason = tick(mover, t, t * 6) end
assert(status == "failed" and reason == "timeout", "long drop must time out at its bound")
mover = begin({kind="drop", from=1, to=2, destination=1000})
tick(mover, 0, 0); tick(mover, 2, 0); tick(mover, 2.1, 0)
status, reason = tick(mover, 4.2, 0)
assert(status == "failed" and reason == "no_progress", "stalled drop must still fail")
for _, kind in ipairs({"jumpup", "downjump", "rope"}) do
    mover = begin({kind=kind, from=1, to=2, x=1000, destination=1000, rise=-20})
    assert(tick(mover, 0, 0) == "running")
    assert(mover.edge_timeout == 30, kind .. " must use alignment distance")
    assert(tick(mover, 11, 100) == "running", kind .. " must not expire at 10 seconds")
    status, reason = tick(mover, 30, 200)
    assert(status == "failed" and reason == "timeout", kind .. " must remain bounded")
end
""")

    def test_active_path_continues_when_character_has_no_platform(self) -> None:
        self.run_lua(r"""
c.state.legs[1].x = 100
main(c); main(c)
assert(steps == 1, "initial plan must start movement")
missing_character_platform = true
main(c)
assert(steps == 2 and c.state.path, "active movement must continue while off platform")
assert(not c.state.retries, "airborne movement must not trigger retry")
""")

    def test_missing_character_platform_waits_then_retries(self) -> None:
        self.run_lua(r"""
c.state.legs[1].x = 100
missing_character_platform = true
main(c)
assert(stops > 0 and #plans == 0 and not c.state.retries, "wait safely before planning")
c.tick.time = 2.9; main(c)
assert(not c.state.retries, "temporary missing platform must not retry")
c.tick.time = 3.1; main(c)
assert(c.state.retries == 1 and #plans == 0, "persistent missing platform must retry")
""")

    def test_missing_target_platform_retries_immediately(self) -> None:
        self.run_lua(r"""
c.state.legs[1].x = 100
missing_target_platform = true
main(c)
assert(c.state.retries == 1 and stops > 0 and #plans == 0, "missing target requires immediate retry")
""")

    def test_failed_edge_stops_without_replanning(self) -> None:
        self.run_lua(r"""
c.state.legs[1].x = 100
fail_move = true
main(c)
local status, reason = main(c)
assert(status == "failed" and reason == "no_progress", "movement failure must stop the route")
assert(stops > 0 and #plans == 1, "failed movement must release input without replanning")
""")

    def test_no_path_fails_instead_of_blind_walking(self) -> None:
        self.run_lua(r"""
c.state.legs[1].x = 100
no_path = true
local status, reason = main(c)
assert(stops > 0, "failed plan must release input")
assert(status == "failed" and reason == "no_path", "no_path must fail explicitly without retry")
assert(moves[#moves] ~= "right", "no_path must not walk blindly")
""")


if __name__ == "__main__":
    unittest.main()
