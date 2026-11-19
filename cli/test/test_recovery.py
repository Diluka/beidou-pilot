"""一次普通复活请求及其同角色效果核验合同。"""

import ctypes
import ctypes.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from beidou_pilot.errors import ClientError
from beidou_pilot.recovery import revive


class RecoveryContract(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = SimpleNamespace(name="beidou", root=Path("/unused"), instance="default", read=lambda _name: None)
        self.before = {
            "character": {"id": 7, "hp": 0},
            "native_values_valid": True,
            "map_id": 100000000,
            "position": None,
        }
        self.after = {
            "character": {"id": 7, "hp": 50},
            "native_values_valid": True,
            "map_id": 100000000,
            "position": {"x": 2581, "y": 567},
        }
        self.window = {"address": "0x1234", "vtables": ["0xb3b1a8"], "buttons": [{"control_id": 1, "enabled": True}]}
        self.snapshot = patch("beidou_pilot.recovery.BridgeClient.snapshot", return_value={"scripts": []})
        self.scene = patch(
            "beidou_pilot.strategy_scene.scene_context",
            return_value={"character_id": 7, "map_id": 100000000, "instance_id": "gui-1", "scene_generation": 1},
        )
        self.ui_patch = patch("beidou_pilot.recovery.read_ui", return_value=self.ui([self.window]))
        self.ui_read = self.ui_patch.start()
        self.addCleanup(self.ui_patch.stop)
        self.run = patch("beidou_pilot.recovery.BridgeClient.run_script", return_value={"status": "completed"})
        self.snapshot.start()
        self.scene.start()
        self.run_script = self.run.start()
        self.addCleanup(self.snapshot.stop)
        self.addCleanup(self.scene.stop)
        self.addCleanup(self.run.stop)

    @staticmethod
    def ui(windows: list[dict]) -> dict:
        return {"unavailable": [], "windows": windows}

    def test_gui_requests_once_and_requires_same_character_recovery_and_closed_dialog(self) -> None:
        with (
            patch.object(self.backend, "read", side_effect=[self.before, self.after]),
            patch("beidou_pilot.recovery.read_ui", side_effect=[self.ui([self.window]), self.ui([])]),
        ):
            result = revive(self.backend)
        self.run_script.assert_called_once()
        code = self.run_script.call_args.kwargs["code"]
        self.assertIn("context.game.player.revive()", code)
        self.assertIn('if status.dispatched or status.reason == "native_input_cleared" then return "done" end', code)
        self.assertIn(
            'if status.input_action ~= "revive" then error(status.reason or "revive_not_dispatched") end', code
        )
        self.assertIn("requested = true", code)
        self.assertEqual(1, code.count("context.game.player.revive()"))
        self.assertEqual("revived", result["status"])
        self.assertEqual(7, result["state"]["character"]["id"])

    def test_gui_native_clear_waits_for_real_recovery_and_rejections_are_not_replayed(self) -> None:
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

        for reason, recovered in (
            ("native_input_cleared", True),
            ("native_input_cleared", False),
            ("revive_dialog_unavailable", False),
            ("native_input_cleared_extra", False),
        ):
            with self.subTest(reason=reason, recovered=recovered):
                self.run_script.reset_mock()

                def execute(*, code, **_kwargs):
                    state = lua.luaL_newstate()
                    self.assertTrue(state)
                    try:
                        lua.luaL_openlibs(state)
                        source = (
                            code
                            + f'''
local calls = 0
local context = {{game={{player={{
  revive=function() calls=calls+1; return true end,
  status=function() return {{dispatched=false, input_action=nil, reason="{reason}"}} end
}}}}}}
assert(main(context) == nil)
local ok, result = pcall(main, context)
assert(calls == 1)
'''
                        )
                        if reason == "native_input_cleared":
                            source += 'assert(ok and result == "done")\n'
                        else:
                            source += f'assert(not ok and string.find(result, "{reason}", 1, true))\n'
                        rc = lua.luaL_loadstring(state, source.encode())
                        if rc == 0:
                            rc = lua.lua_pcallk(state, 0, 0, 0, 0, None)
                        self.assertEqual(0, rc, lua.lua_tolstring(state, -1, None) if rc else None)
                    finally:
                        lua.lua_close(state)
                    if reason != "native_input_cleared":
                        raise ClientError("bridge_script_error", reason)
                    return {"status": "completed"}

                self.run_script.side_effect = execute
                after = self.after if recovered else self.before
                with (
                    patch("beidou_pilot.strategies.compile_strategy", side_effect=lambda source, *_: source),
                    patch.object(self.backend, "read", side_effect=[self.before, after]),
                    patch("beidou_pilot.recovery.read_ui", side_effect=[self.ui([self.window]), self.ui([])]),
                    patch("beidou_pilot.recovery.time.monotonic", side_effect=[0, 0, 0, 0, 7]),
                    patch("beidou_pilot.recovery.time.sleep"),
                ):
                    if recovered:
                        self.assertEqual("revived", revive(self.backend)["status"])
                    else:
                        with self.assertRaises(ClientError) as raised:
                            revive(self.backend)
                        expected = "revive_not_confirmed" if reason == "native_input_cleared" else "bridge_script_error"
                        self.assertEqual(expected, raised.exception.code)
                self.run_script.assert_called_once()

    def test_gui_open_or_unavailable_window_does_not_confirm(self) -> None:
        for ui in (self.ui([self.window]), {"unavailable": ["camera unavailable"], "windows": []}):
            with (
                self.subTest(ui=ui),
                patch.object(self.backend, "read", side_effect=[self.before, self.after]),
                patch("beidou_pilot.recovery.read_ui", side_effect=[self.ui([self.window]), ui]),
                patch("beidou_pilot.recovery.time.monotonic", side_effect=[0, 0, 0, 0, 7]),
                patch("beidou_pilot.recovery.time.sleep"),
            ):
                self.run_script.reset_mock()
                with self.assertRaises(ClientError) as raised:
                    revive(self.backend)
                self.assertEqual("revive_not_confirmed", raised.exception.code)
                self.run_script.assert_called_once()

    def test_gui_waits_for_delayed_window_before_requesting(self) -> None:
        with (
            patch.object(self.backend, "read", side_effect=[self.before, self.after]),
            patch(
                "beidou_pilot.recovery.read_ui", side_effect=[self.ui([]), self.ui([self.window]), self.ui([])]
            ) as ui,
            patch("beidou_pilot.recovery.time.monotonic", side_effect=[0, 0, 1, 1, 1]),
            patch("beidou_pilot.recovery.time.sleep") as sleep,
        ):
            result = revive(self.backend)
        self.assertEqual("revived", result["status"])
        self.assertEqual(3, ui.call_count)
        sleep.assert_called_once_with(0.15)
        self.run_script.assert_called_once()

    def test_gui_window_timeout_never_requests(self) -> None:
        with (
            patch.object(self.backend, "read", return_value=self.before),
            patch("beidou_pilot.recovery.read_ui", return_value=self.ui([])),
            patch("beidou_pilot.recovery.time.monotonic", side_effect=[0, 0, 3]),
            patch("beidou_pilot.recovery.time.sleep"),
        ):
            with self.assertRaises(ClientError) as raised:
                revive(self.backend)
        self.assertEqual("revive_dialog_unavailable", raised.exception.code)
        self.run_script.assert_not_called()

    def test_alive_never_requests(self) -> None:
        alive = {**self.before, "character": {"id": 7, "hp": 1}}
        with patch.object(self.backend, "read", return_value=alive):
            result = revive(self.backend)
        self.assertEqual("already_alive", result["status"])
        self.run_script.assert_not_called()

    def test_script_error_or_timeout_is_not_replayed(self) -> None:
        for code in ("bridge_script_error", "bridge_timeout"):
            with self.subTest(code=code), patch.object(self.backend, "read", return_value=self.before):
                self.run_script.reset_mock()
                self.ui_read.reset_mock()
                error = ClientError(code, "test", {"script_id": "failed-script"})
                self.run_script.side_effect = error
                with self.assertRaises(ClientError) as raised:
                    revive(self.backend)
                self.assertIs(error, raised.exception)
                self.assertEqual(code, raised.exception.code)
                self.run_script.assert_called_once()
                self.ui_read.assert_called_once()

    def test_character_change_stops_confirmation(self) -> None:
        changed = {**self.after, "character": {"id": 8, "hp": 50}}
        with patch.object(self.backend, "read", side_effect=[self.before, changed]):
            with self.assertRaises(ClientError) as raised:
                revive(self.backend)
        self.assertEqual("character_changed", raised.exception.code)
        self.run_script.assert_called_once()
