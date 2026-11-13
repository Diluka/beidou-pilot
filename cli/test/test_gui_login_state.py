import unittest
import fcntl
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from beidou_pilot.errors import ClientError
from beidou_pilot.gui_login import _step as execute


class GuiLoginStateTests(unittest.TestCase):
    def setUp(self):
        self.backend = Mock(name="backend")
        self.backend.name = "beidou"
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.backend.runtime = SimpleNamespace(
            running=True, run_id="r", run_dir=Path(directory.name), character_id=None, world=0, channel=0
        )
        self.profile = SimpleNamespace(world=0, channel=0)
        self.stage = {
            "instance_id": "i",
            "client": {"run_id": "r"},
            "unavailable": [],
            "stage": "LOGIN",
            "login": {
                "raw_step": 0,
                "request_pending": False,
                "transition_pending": False,
                "raw_world_selection": {"count": 1, "selected_index": 0, "raw_world_id": 0},
            },
            "windows": [
                {"vtables": v}
                for v in (
                    ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
                    ["0xaf7168", "0xaf711c", "0xaf7118"],
                    ["0xaf7940", "0xaf78f4", "0xaf78f0"],
                )
            ],
        }
        self.backend.read.return_value = self.stage
        bridge = patch("beidou_pilot.gui_login.BridgeClient").start()
        self.addCleanup(patch.stopall)
        self.bridge = bridge.return_value
        self.bridge.snapshot.return_value = {
            "instance_id": "i",
            "run_id": "r",
            "held_keys": [],
            "command": {"status": "idle"},
            "script": None,
            "scripts": [],
        }

    def call(self):
        return execute(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female")

    @patch(
        "beidou_pilot.gui_login.submit_credentials_once",
        return_value={"status": "unknown", "credentials_submitted": True},
    )
    def test_credentials_use_verified_input_handler(self, submit):
        self.assertTrue(self.call()["credentials_submitted"])
        submit.assert_called_once_with(self.backend, self.profile, "i", "r", deadline=float("inf"))
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_unknown_or_pending_never_inputs(self, load):
        load.return_value = self.backend.runtime
        for change in (
            {"windows": []},
            {"windows": [{"login_page_candidate": "gender"}]},
            {"login": {"raw_step": 0, "request_pending": None, "transition_pending": False}},
        ):
            with self.subTest(change=change):
                stage = self.stage.copy()
                stage.update(change)
                self.backend.read.return_value = stage
                with self.assertRaises(ClientError):
                    self.call()
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_terms_scroll_bounded_and_authorized(self, load):
        load.return_value = self.backend.runtime
        window = {
            "address": "0x1",
            "login_page_candidate": "terms",
            "buttons": [
                {"control_id": 1, "enabled": False, "layout_x": 266, "layout_y": 374, "width": 75, "height": 32}
            ],
        }
        window["vtables"] = ["0xaf79c8", "0xaf797c", "0xaf7978"]
        self.stage["windows"] = [
            {"vtables": v}
            for v in (
                ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
                ["0xaf7168", "0xaf711c", "0xaf7118"],
                ["0xaf7940", "0xaf78f4", "0xaf78f0"],
            )
        ] + [window]
        dialog = {
            "instance_id": "i",
            "client": {"run_id": "r"},
            "unavailable": [],
            "focused_window": {
                "address": "0x1",
                "vtables": ["0xaf79c8", "0xaf797c", "0xaf7978"],
                "width": 431,
                "height": 426,
                "root_rect": {"left": 100, "top": 100, "right": 531, "bottom": 526},
            },
        }

        def read(name, *args):
            if name == "stage":
                return self.stage
            if name == "dialog":
                return dialog
            if name == "desktop":
                return {"action": "scroll", "input_dispatched": True}
            self.fail(name)

        self.backend.read.side_effect = read
        self.backend.desktop.side_effect = lambda actions: {
            "input_dispatched": True,
            "cancelled": False,
            "timings": [{"action": actions[0]["action"], "held_seconds": 0.1}],
        }
        with self.assertRaises(ClientError):
            self.call()
        scrolls = [call for call in self.backend.read.call_args_list if call.args[0] == "desktop"]
        self.assertEqual(len(scrolls), 2)
        self.assertEqual(self.backend.desktop.call_count, 1)

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_terms_authorization_and_enabled_confirmation(self, load):
        load.return_value = self.backend.runtime
        button = {"control_id": 1, "enabled": True, "layout_x": 266, "layout_y": 374, "width": 75, "height": 32}
        self.stage["windows"] = [
            {"vtables": v}
            for v in (
                ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
                ["0xaf7168", "0xaf711c", "0xaf7118"],
                ["0xaf7940", "0xaf78f4", "0xaf78f0"],
            )
        ] + [
            {
                "address": "0x1",
                "vtables": ["0xaf79c8", "0xaf797c", "0xaf7978"],
                "login_page_candidate": "terms",
                "buttons": [button],
            }
        ]
        dialog = {
            "instance_id": "i",
            "client": {"run_id": "r"},
            "unavailable": [],
            "focused_window": {
                "address": "0x1",
                "vtables": ["0xaf79c8", "0xaf797c", "0xaf7978"],
                "width": 431,
                "height": 426,
                "root_rect": {"left": 100, "top": 100, "right": 531, "bottom": 526},
            },
        }
        self.backend.read.side_effect = lambda name, *args: dialog if name == "dialog" else self.stage
        self.backend.desktop.side_effect = lambda actions: {
            "input_dispatched": True,
            "cancelled": False,
            "timings": [{"action": actions[0]["action"], "held_seconds": 0.1}],
        }
        with self.assertRaises(ClientError):
            execute(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=False, gender="female")
        self.backend.desktop.assert_not_called()
        self.assertEqual(self.call()["phase"], "unknown")
        self.backend.desktop.assert_called_once_with([{"action": "click", "x": 403, "y": 490}])
        with self.assertRaises(ClientError):
            self.call()
        self.backend.desktop.assert_called_once()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_world_channel_selection_and_unknown_modal(self, load):
        load.return_value = self.backend.runtime
        common = [
            ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
            ["0xaf7168", "0xaf711c", "0xaf7118"],
            ["0xaf7a90", "0xaf7a44", "0xaf7a40"],
            ["0xaf70d0", "0xaf7084", "0xaf7080"],
        ]
        self.stage.update(
            stage="WORLD_SELECT",
            windows=[
                {
                    "vtables": v,
                    **(
                        {
                            "address": "0x1",
                            "window_position_source": "stable Gr2D layer bounds and camera",
                            "game_rect": {"left": 472, "top": 164, "right": 872, "bottom": 264},
                        }
                        if v[0] == "0xaf7a90"
                        else {}
                    ),
                }
                for v in common
            ],
            game_geometry={"x": 10, "y": 20, "width": 1280, "height": 720},
        )
        self.backend.desktop.side_effect = lambda actions: {
            "input_dispatched": True,
            "cancelled": False,
            "timings": [{"action": actions[0]["action"], "held_seconds": 0.1}],
        }
        self.assertEqual(self.call()["action"], "world_input_dispatched")
        self.assertEqual(self.backend.desktop.call_count, 2)
        self.backend.desktop.reset_mock()
        self.stage["windows"].append({"vtables": ["unknown"]})
        with self.assertRaises(ClientError):
            self.call()
        self.backend.desktop.assert_not_called()
        self.stage.update(
            stage="CHANNEL_SELECT",
            windows=[{"vtables": v} for v in common + [["0xaf7b4c", "0xaf7b00", "0xaf7afc"]]],
            channel_panel={
                "channels": [{"channel": 1, "root_rect": {"left": 20, "top": 30, "right": 40, "bottom": 50}}]
            },
        )
        with self.assertRaises(ClientError):
            self.call()
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_world_click_transition_to_channel_never_sends_return(self, load):
        load.return_value = self.backend.runtime
        common = [
            ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
            ["0xaf7168", "0xaf711c", "0xaf7118"],
            ["0xaf7a90", "0xaf7a44", "0xaf7a40"],
            ["0xaf70d0", "0xaf7084", "0xaf7080"],
        ]
        self.stage.update(
            stage="WORLD_SELECT",
            windows=[
                {
                    "vtables": v,
                    **(
                        {
                            "address": "0x1",
                            "window_position_source": "stable Gr2D layer bounds and camera",
                            "game_rect": {"left": 472, "top": 164, "right": 872, "bottom": 264},
                        }
                        if v[0] == "0xaf7a90"
                        else {}
                    ),
                }
                for v in common
            ],
            game_geometry={"x": 10, "y": 20, "width": 1280, "height": 720},
        )
        channel = dict(
            self.stage,
            stage="CHANNEL_SELECT",
            windows=[{"vtables": v} for v in common + [["0xaf7b4c", "0xaf7b00", "0xaf7afc"]]],
        )
        self.backend.read.side_effect = [self.stage, channel]
        self.backend.desktop.return_value = {
            "input_dispatched": True,
            "cancelled": False,
            "timings": [{"action": "click"}],
        }
        self.assertEqual(self.call()["action"], "world_input_dispatched")
        self.backend.desktop.assert_called_once()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_unknown_world_index_never_inputs(self, load):
        load.return_value = self.backend.runtime
        self.stage.update(
            stage="WORLD_SELECT",
            game_geometry={"x": 10, "y": 20, "width": 1280, "height": 720},
            windows=[
                {"vtables": v}
                for v in (
                    ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
                    ["0xaf7168", "0xaf711c", "0xaf7118"],
                    ["0xaf7a90", "0xaf7a44", "0xaf7a40"],
                    ["0xaf70d0", "0xaf7084", "0xaf7080"],
                )
            ],
        )
        self.stage["windows"][2].update(
            address="0x1",
            window_position_source="stable Gr2D layer bounds and camera",
            game_rect={"left": 472, "top": 164, "right": 872, "bottom": 264},
        )
        self.stage["windows"][2]["game_rect"] = None
        with self.assertRaises(ClientError):
            self.call()
        self.stage["windows"][2]["game_rect"] = {"left": 472, "top": 164, "right": 872, "bottom": 264}
        for value in (
            None,
            {"count": 2, "selected_index": 0},
            {"count": 1, "selected_index": -1},
            {"count": True, "selected_index": 0},
            {"count": 1, "selected_index": 0, "raw_world_id": None},
            {"count": 1, "selected_index": 0, "raw_world_id": 1},
        ):
            self.stage["login"]["raw_world_selection"] = value
            with self.subTest(value=value), self.assertRaises(ClientError):
                self.call()
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_script_started_between_world_click_and_return_stops(self, load):
        load.return_value = self.backend.runtime
        common = [
            ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
            ["0xaf7168", "0xaf711c", "0xaf7118"],
            ["0xaf7a90", "0xaf7a44", "0xaf7a40"],
            ["0xaf70d0", "0xaf7084", "0xaf7080"],
        ]
        self.stage.update(
            stage="WORLD_SELECT",
            windows=[
                {
                    "vtables": v,
                    **(
                        {
                            "address": "0x1",
                            "window_position_source": "stable Gr2D layer bounds and camera",
                            "game_rect": {"left": 472, "top": 164, "right": 872, "bottom": 264},
                        }
                        if v[0] == "0xaf7a90"
                        else {}
                    ),
                }
                for v in common
            ],
            game_geometry={"x": 10, "y": 20, "width": 1280, "height": 720},
        )

        def desktop(actions):
            self.bridge.snapshot.return_value["scripts"] = [
                {"status": "running", "control_released": False},
                {"status": "completed", "control_released": True},
            ]
            return {"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]}

        self.backend.desktop.side_effect = desktop
        with self.assertRaises(ClientError):
            self.call()
        self.backend.desktop.assert_called_once()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_world_interruption_never_replays(self, load):
        load.return_value = self.backend.runtime
        common = [
            ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
            ["0xaf7168", "0xaf711c", "0xaf7118"],
            ["0xaf7a90", "0xaf7a44", "0xaf7a40"],
            ["0xaf70d0", "0xaf7084", "0xaf7080"],
        ]
        self.stage.update(
            stage="WORLD_SELECT",
            windows=[
                {
                    "vtables": v,
                    **(
                        {
                            "address": "0x1",
                            "window_position_source": "stable Gr2D layer bounds and camera",
                            "game_rect": {"left": 472, "top": 164, "right": 872, "bottom": 264},
                        }
                        if v[0] == "0xaf7a90"
                        else {}
                    ),
                }
                for v in common
            ],
            game_geometry={"x": 10, "y": 20, "width": 1280, "height": 720},
        )
        self.backend.desktop.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.call()
        with self.assertRaises(ClientError):
            self.call()
        self.backend.desktop.assert_called_once()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_channel_without_world_evidence_is_blocked(self, load):
        load.return_value = self.backend.runtime
        self.stage.update(
            stage="CHANNEL_SELECT",
            game_geometry={"x": 10, "y": 20, "width": 1280, "height": 720},
            windows=[
                {"vtables": v}
                for v in (
                    ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
                    ["0xaf7168", "0xaf711c", "0xaf7118"],
                    ["0xaf7a90", "0xaf7a44", "0xaf7a40"],
                    ["0xaf70d0", "0xaf7084", "0xaf7080"],
                    ["0xaf7b4c", "0xaf7b00", "0xaf7afc"],
                )
            ],
            channel_panel={
                "channels": [{"channel": 1, "root_rect": {"left": 20, "top": 30, "right": 40, "bottom": 50}}]
            },
        )
        with self.assertRaises(ClientError):
            self.call()
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.load_runtime")
    @patch("beidou_pilot.gui_login.time.sleep")
    @patch("beidou_pilot.gui_login.time.monotonic", side_effect=[0, 0, 0, 1])
    @patch("beidou_pilot.gui_login._step", return_value={"credentials_submitted": True})
    def test_loop_does_not_replay_credentials(self, submit, clock, sleep, load):
        load.return_value = self.backend.runtime
        from beidou_pilot.gui_login import execute as run

        with self.assertRaises(ClientError) as error:
            run(
                self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female", timeout=0.1
            )
        self.assertEqual(error.exception.code, "gui_login_timeout")
        submit.assert_called_once()

    @patch("beidou_pilot.gui_login.load_runtime")
    @patch("beidou_pilot.gui_login.time.sleep")
    @patch("beidou_pilot.gui_login._step")
    def test_loop_advances_only_after_observed_page_changes(self, step, sleep, load):
        load.return_value = self.backend.runtime
        from beidou_pilot.gui_login import execute as run

        base = {
            "instance_id": "i",
            "client": {"run_id": "r"},
            "unavailable": [],
            "login": {"request_pending": False, "transition_pending": False},
        }
        states = [
            dict(base, stage="LOGIN", windows=[]),
            dict(base, stage="LOGIN", windows=[{"login_page_candidate": "terms"}]),
            dict(base, stage="CHARACTER_SELECT", windows=[]),
        ]
        self.backend.read.side_effect = states
        step.side_effect = [
            {"credentials_submitted": True},
            {"action": "terms_input_dispatched"},
            {"phase": "character_list", "characters": []},
        ]
        self.assertEqual(
            run(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female")["phase"],
            "character_list",
        )
        self.assertEqual(step.call_count, 3)

    @patch("beidou_pilot.gui_login.load_runtime")
    @patch("beidou_pilot.gui_login.time.sleep")
    @patch("beidou_pilot.gui_login.time.monotonic", side_effect=[0, 1])
    @patch("beidou_pilot.gui_login._step")
    def test_resume_world_marker_observes_without_replay(self, step, clock, sleep, load):
        from beidou_pilot.gui_login import execute as run

        load.return_value = self.backend.runtime
        (self.backend.runtime.run_dir / "gui-world-submitted").write_text("attempted\n")
        self.stage["stage"] = "WORLD_SELECT"
        with self.assertRaises(ClientError) as error:
            run(
                self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female", timeout=0.1
            )
        self.assertEqual(error.exception.code, "gui_login_timeout")
        step.assert_not_called()
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_concurrent_login_does_not_observe_or_input(self, load):
        from beidou_pilot.gui_login import execute as run

        load.return_value = self.backend.runtime
        with (self.backend.runtime.run_dir / "gui-login.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ClientError) as error:
                run(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female")
        self.assertEqual(error.exception.code, "gui_login_busy")
        self.backend.read.assert_not_called()
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_gender_unknown_never_sends_input(self, load):
        from beidou_pilot.gui_login import execute as run

        load.return_value = self.backend.runtime
        self.stage["windows"] = [{"login_page_candidate": "gender"}]
        with self.assertRaises(ClientError) as error:
            run(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female")
        self.assertEqual(error.exception.code, "gui_gender_state_unknown")
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.load_runtime")
    @patch("beidou_pilot.gui_login.time.sleep")
    @patch("beidou_pilot.gui_login.time.monotonic", side_effect=[0, 1])
    @patch("beidou_pilot.gui_login._step")
    def test_resume_channel_marker_observes_without_replay(self, step, clock, sleep, load):
        from beidou_pilot.gui_login import execute as run

        load.return_value = self.backend.runtime
        (self.backend.runtime.run_dir / "gui-channel-submitted").write_text("attempted\n")
        self.stage["stage"] = "CHANNEL_SELECT"
        with self.assertRaises(ClientError) as error:
            run(
                self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female", timeout=0.1
            )
        self.assertEqual(error.exception.code, "gui_login_timeout")
        step.assert_not_called()
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_gender_female_selection_verified_before_confirm(self, load):
        from beidou_pilot.gui_login import _gender

        load.return_value = self.backend.runtime
        window = {
            "address": "0x1",
            "vtables": ["0xaf7298", "0xaf724c", "0xaf7248"],
            "width": 354,
            "height": 259,
            "login_page_candidate": "gender",
            "raw_gender_selection": 0,
            "game_rect": {"left": 595, "top": 160, "right": 949, "bottom": 419},
            "window_position_source": "stable Gr2D layer bounds and camera",
            "buttons": [
                {"control_id": 8002, "enabled": True, "layout_x": 190, "layout_y": 150, "width": 75, "height": 32}
            ],
        }
        self.stage["windows"] = [
            {"vtables": v}
            for v in (
                ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
                ["0xaf7168", "0xaf711c", "0xaf7118"],
                ["0xaf7940", "0xaf78f4", "0xaf78f0"],
            )
        ] + [window]
        self.stage["game_geometry"] = {"x": -495, "y": -60, "width": 1280, "height": 720}
        dialog = {
            "instance_id": "i",
            "client": {"run_id": "r"},
            "unavailable": [],
            "script_dialog_open": False,
            "focused_talk_dialog_open": False,
            "registered_talk_dialog_open": False,
            "focused_window": {
                "address": "0x1",
                "vtables": window["vtables"],
                "game_rect": {"left": 595, "top": 160, "right": 949, "bottom": 419},
                "root_rect": {"left": 100, "top": 100, "right": 454, "bottom": 359},
            },
        }
        self.backend.read.side_effect = lambda name, *args: dialog if name == "dialog" else self.stage

        def desktop(actions):
            if actions[0]["x"] == 272:
                window["raw_gender_selection"] = 0 if actions[0]["y"] == 225 else 1
            return {"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]}

        self.backend.desktop.side_effect = desktop
        self.assertEqual(_gender(self.backend, "i", "r", "female")["action"], "gender_input_dispatched")
        self.assertEqual(self.backend.desktop.call_count, 3)
        self.assertTrue((self.backend.runtime.run_dir / "gui-gender-submitted").exists())
        with self.assertRaises(ClientError):
            _gender(self.backend, "i", "r", "female")
        self.assertEqual(self.backend.desktop.call_count, 3)
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            window["raw_gender_selection"] = 0
            self.assertEqual(_gender(self.backend, "i", "r", "male")["action"], "gender_input_dispatched")
            self.assertEqual(self.backend.desktop.call_count, 1)
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            window["raw_gender_selection"] = 1
            self.assertEqual(_gender(self.backend, "i", "r", "female")["action"], "gender_input_dispatched")
            self.assertEqual(self.backend.desktop.call_count, 1)
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            window["raw_gender_selection"] = 1
            self.assertEqual(_gender(self.backend, "i", "r", "male")["action"], "gender_input_dispatched")
            self.assertEqual(self.backend.desktop.call_count, 3)
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            self.backend.desktop.side_effect = lambda actions: {
                "input_dispatched": True,
                "cancelled": False,
                "timings": [{"action": "click"}],
            }
            window["raw_gender_selection"] = 0
            with self.assertRaises(ClientError):
                _gender(self.backend, "i", "r", "female")
            self.assertEqual(self.backend.desktop.call_count, 2)
            self.assertFalse((self.backend.runtime.run_dir / "gui-gender-submitted").exists())
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            window["raw_gender_selection"] = 0
            window["game_rect"] = {"left": 600, "top": 160, "right": 954, "bottom": 419}
            window["window_position_source"] = "camera"
            with patch("beidou_pilot.gui_login.time.sleep") as sleep:
                with self.assertRaises(ClientError) as error:
                    _gender(self.backend, "i", "r", "male")
            self.assertFalse(error.exception.details["position_source_valid"])
            sleep.assert_not_called()
            self.backend.desktop.assert_not_called()
            dialog["focused_window"] = None
            with self.assertRaises(ClientError):
                _gender(self.backend, "i", "r", "male")
            self.backend.desktop.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            dialog["focused_window"] = None
            window["window_position_source"] = "stable Gr2D layer bounds and camera"
            window["game_rect"] = {"left": 595, "top": 160, "right": 949, "bottom": 419}
            window["raw_gender_selection"] = 0
            self.assertEqual(_gender(self.backend, "i", "r", "male")["action"], "gender_input_dispatched")
            self.backend.desktop.assert_called_once()
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            window.update(game_rect={"left": 595, "top": 160, "right": 949, "bottom": 419},
                          window_position_source="stable Gr2D layer bounds and camera", raw_gender_selection=0)
            def projection_lost(actions):
                window.update(game_rect=None, window_position_source=None)
                return {"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]}
            self.backend.desktop.side_effect = projection_lost
            with self.assertRaises(ClientError) as error:
                _gender(self.backend, "i", "r", "female")
            self.assertEqual(error.exception.code, "gui_gender_projection_pending")
            self.assertIn("未发送后续输入", error.exception.message)
            self.backend.desktop.assert_called_once()
            self.assertTrue((Path(directory) / "gui-gender-selection").exists())
            with patch("beidou_pilot.gui_login.time.sleep"):
                with self.assertRaises(ClientError):
                    _gender(self.backend, "i", "r", "female")
            self.backend.desktop.assert_called_once()
            self.backend.desktop.side_effect = lambda actions: {"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]}
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            window.update(game_rect=None, window_position_source=None, raw_gender_selection=0)
            with patch("beidou_pilot.gui_login.time.sleep"):
                with self.assertRaises(ClientError) as error:
                    _gender(self.backend, "i", "r", "male")
            self.assertEqual(error.exception.details, {"reason": "projection_null"})
            self.backend.desktop.assert_not_called()
            self.assertFalse((Path(directory) / "gui-gender-submitted").exists())
            with patch("beidou_pilot.gui_login.time.sleep"), patch("beidou_pilot.gui_login.time.monotonic", side_effect=[0, 0, 0, 2]):
                with self.assertRaises(ClientError) as expired:
                    _gender(self.backend, "i", "r", "male", deadline=1)
            self.assertEqual(expired.exception.code, "gui_login_timeout")
            self.backend.desktop.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            window.update(game_rect=None, window_position_source=None, raw_gender_selection=0)
            calls = 0

            def projection_becomes_ready(name, *args):
                nonlocal calls
                if name == "dialog":
                    return dialog
                calls += 1
                if calls == 2:
                    self.backend.desktop.assert_not_called()
                    window.update(game_rect={"left": 595, "top": 160, "right": 949, "bottom": 419},
                                  window_position_source="stable Gr2D layer bounds and camera")
                return self.stage

            self.backend.read.side_effect = projection_becomes_ready
            with patch("beidou_pilot.gui_login.time.sleep"):
                self.assertEqual(_gender(self.backend, "i", "r", "male")["action"], "gender_input_dispatched")
            self.backend.desktop.assert_called_once()
            self.backend.read.side_effect = lambda name, *args: dialog if name == "dialog" else self.stage
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            calls = 0
            def second_projection_missing(name, *args):
                nonlocal calls
                if name == "dialog":
                    return dialog
                calls += 1
                window.update(game_rect=None if calls == 2 else {"left": 595, "top": 160, "right": 949, "bottom": 419},
                              window_position_source=None if calls == 2 else "stable Gr2D layer bounds and camera")
                return self.stage
            self.backend.read.side_effect = second_projection_missing
            with patch("beidou_pilot.gui_login.time.sleep"):
                self.assertEqual(_gender(self.backend, "i", "r", "male")["action"], "gender_input_dispatched")
            self.assertGreaterEqual(calls, 6)
            self.backend.desktop.assert_called_once()
            self.backend.read.side_effect = lambda name, *args: dialog if name == "dialog" else self.stage
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            calls = 0

            def changing_read(name, *args):
                nonlocal calls
                if name == "dialog":
                    return dialog
                calls += 1
                if calls == 2:
                    self.stage["game_geometry"] = {"x": -494, "y": -60, "width": 1280, "height": 720}
                return self.stage

            self.backend.read.side_effect = changing_read
            with self.assertRaises(ClientError):
                _gender(self.backend, "i", "r", "male")
            self.backend.desktop.assert_not_called()
            self.stage["game_geometry"] = {"x": -495, "y": -60, "width": 1280, "height": 720}
            self.backend.read.side_effect = lambda name, *args: dialog if name == "dialog" else self.stage
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            calls = 0

            def changing_raw(name, *args):
                nonlocal calls
                if name == "dialog":
                    return dialog
                calls += 1
                if calls == 2:
                    window["raw_gender_selection"] = 1
                return self.stage

            self.backend.read.side_effect = changing_raw
            window["raw_gender_selection"] = 0
            with self.assertRaises(ClientError):
                _gender(self.backend, "i", "r", "male")
            self.backend.desktop.assert_not_called()
            self.backend.read.side_effect = lambda name, *args: dialog if name == "dialog" else self.stage
        with tempfile.TemporaryDirectory() as directory:
            self.backend.runtime.run_dir = Path(directory)
            self.backend.desktop.reset_mock()
            dialog["instance_id"] = "other"
            window["raw_gender_selection"] = 0
            with self.assertRaises(ClientError):
                _gender(self.backend, "i", "r", "male")
            self.backend.desktop.assert_not_called()

    def test_all_script_sessions_and_input_ownership_fail_closed(self):
        from beidou_pilot.gui_login import _require_input_idle

        snapshot = self.bridge.snapshot.return_value
        for scripts in (
            None,
            [{"status": "running", "control_released": False}, {"status": "completed", "control_released": True}],
            [{"status": "completed", "control_released": False}],
            [{"status": "completed"}],
            [{"status": "unknown", "control_released": True}],
        ):
            snapshot["script"] = {"status": "completed"}
            snapshot["scripts"] = scripts
            with self.subTest(scripts=scripts), self.assertRaises(ClientError):
                _require_input_idle(self.backend, "i", "r")
        snapshot.pop("scripts")
        with self.assertRaises(ClientError):
            _require_input_idle(self.backend, "i", "r")
        snapshot["scripts"] = [{"status": "completed", "control_released": True}]
        _require_input_idle(self.backend, "i", "r")
        snapshot["command"] = {"status": "unknown"}
        with self.assertRaises(ClientError):
            _require_input_idle(self.backend, "i", "r")
        snapshot["command"] = {"status": "idle"}
        snapshot["held_keys"] = ["Left"]
        with self.assertRaises(ClientError):
            _require_input_idle(self.backend, "i", "r")

    @patch("beidou_pilot.gui_login.time.sleep")
    @patch("beidou_pilot.gui_login.load_runtime")
    def test_real_steps_world_transition_channel_and_character(self, load, sleep):
        from beidou_pilot.gui_login import execute as run

        load.return_value = self.backend.runtime
        common = [
            ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
            ["0xaf7168", "0xaf711c", "0xaf7118"],
            ["0xaf7a90", "0xaf7a44", "0xaf7a40"],
            ["0xaf70d0", "0xaf7084", "0xaf7080"],
        ]
        windows = [
            {
                "vtables": v,
                **(
                    {
                        "address": "0x1",
                        "window_position_source": "stable Gr2D layer bounds and camera",
                        "game_rect": {"left": 472, "top": 164, "right": 872, "bottom": 264},
                    }
                    if v[0] == "0xaf7a90"
                    else {}
                ),
            }
            for v in common
        ]
        world = dict(
            self.stage,
            stage="WORLD_SELECT",
            windows=windows,
            game_geometry={"x": 10, "y": 20, "width": 1280, "height": 720},
        )
        channel = dict(
            world,
            stage="CHANNEL_SELECT",
            windows=windows + [{"vtables": ["0xaf7b4c", "0xaf7b00", "0xaf7afc"]}],
            channel_panel={
                "channels": [{"channel": 1, "root_rect": {"left": 20, "right": 40, "top": 30, "bottom": 50}}]
            },
        )
        transition = dict(world, stage="TRANSITION")
        chars = dict(
            world,
            stage="CHARACTER_SELECT",
            world_id=0,
            channel=1,
            login={
                "request_pending": False,
                "transition_pending": False,
                "characters_available": True,
                "characters": [],
            },
            windows=[
                {"vtables": v}
                for v in (
                    common[0],
                    common[1],
                    ["0xaf6f04", "0xaf6eb8", "0xaf6eb4"],
                    common[3],
                    common[3],
                    ["0xaf6d90", "0xaf6d44", "0xaf6d40"],
                )
            ],
        )
        for immediate in (True, False):
            with self.subTest(immediate=immediate), tempfile.TemporaryDirectory() as directory:
                self.backend.runtime.run_dir = Path(directory)
                self.backend.read.reset_mock()
                self.backend.desktop.reset_mock()
                after_click = transition if immediate else world
                self.backend.read.side_effect = [world, world, after_click, transition, channel, channel, chars, chars]
                self.backend.desktop.side_effect = lambda actions: {
                    "input_dispatched": True,
                    "cancelled": False,
                    "timings": [{"action": actions[0]["action"], "held_seconds": 0.1}],
                }
                result = run(
                    self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female"
                )
                self.assertEqual(result["phase"], "character_list")
                actions = [call.args[0][0]["action"] for call in self.backend.desktop.call_args_list]
                self.assertEqual(actions, ["click", "double-click"] if immediate else ["click", "hold", "double-click"])
                self.assertTrue((Path(directory) / "gui-world-submitted").exists())
                self.assertTrue((Path(directory) / "gui-channel-submitted").exists())

    @patch("beidou_pilot.gui_login.load_runtime")
    @patch("beidou_pilot.gui_login._step")
    @patch("beidou_pilot.gui_login.time.monotonic", side_effect=[0, 2])
    def test_observation_past_deadline_never_dispatches(self, clock, step, load):
        from beidou_pilot.gui_login import execute as run

        load.return_value = self.backend.runtime
        with self.assertRaises(ClientError) as error:
            run(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female", timeout=1)
        self.assertEqual(error.exception.code, "gui_login_timeout")
        step.assert_not_called()
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.time.monotonic", side_effect=[0, 2])
    @patch("beidou_pilot.gui_login.load_runtime")
    def test_deadline_between_world_click_and_return_stops(self, load, clock):
        load.return_value = self.backend.runtime
        common = [
            ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
            ["0xaf7168", "0xaf711c", "0xaf7118"],
            ["0xaf7a90", "0xaf7a44", "0xaf7a40"],
            ["0xaf70d0", "0xaf7084", "0xaf7080"],
        ]
        self.stage.update(
            stage="WORLD_SELECT",
            windows=[
                {
                    "vtables": v,
                    **(
                        {
                            "address": "0x1",
                            "window_position_source": "stable Gr2D layer bounds and camera",
                            "game_rect": {"left": 472, "top": 164, "right": 872, "bottom": 264},
                        }
                        if v[0] == "0xaf7a90"
                        else {}
                    ),
                }
                for v in common
            ],
            game_geometry={"x": 10, "y": 20, "width": 1280, "height": 720},
        )
        self.backend.desktop.return_value = {
            "input_dispatched": True,
            "cancelled": False,
            "timings": [{"action": "click"}],
        }
        with self.assertRaises(ClientError) as error:
            execute(
                self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female", deadline=1
            )
        self.assertEqual(error.exception.code, "gui_login_timeout")
        self.backend.desktop.assert_called_once()
        self.assertTrue((self.backend.runtime.run_dir / "gui-world-submitted").exists())

    @patch("beidou_pilot.gui_login.load_runtime")
    def test_unowned_transition_stops_without_input(self, load):
        from beidou_pilot.gui_login import execute as run

        load.return_value = self.backend.runtime
        self.stage["stage"] = "TRANSITION"
        with self.assertRaises(ClientError) as error:
            run(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female")
        self.assertEqual(error.exception.code, "gui_login_state_unknown")
        self.backend.desktop.assert_not_called()

    @patch("beidou_pilot.gui_login.time.sleep")
    @patch("beidou_pilot.gui_login.load_runtime")
    @patch("beidou_pilot.gui_first_login.BridgeClient")
    def test_real_step_login_terms_gender_world_channel(self, credential_bridge, load, sleep):
        from beidou_pilot.gui_login import execute as run

        load.return_value = self.backend.runtime
        credential_bridge.return_value = self.bridge
        self.profile.username, self.profile.password = "example", "secret"
        state = {"page": "login", "raw": 0}
        base = [
            {"address": "manager", "width": 1280, "height": 720, "vtables": ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"]},
            {"address": "sidebar", "width": 125, "height": 352, "vtables": ["0xaf7168", "0xaf711c", "0xaf7118"]},
            {
                "address": "login",
                "width": 330,
                "height": 180,
                "vtables": ["0xaf7940", "0xaf78f4", "0xaf78f0"],
                "login_edit_focus": "account",
                "account_empty": True,
                "password_empty": True,
            },
        ]
        geom = {"x": 10, "y": 20, "width": 1280, "height": 720}
        world_extra = [
            {
                "vtables": ["0xaf7a90", "0xaf7a44", "0xaf7a40"],
                "address": "w",
                "window_position_source": "stable Gr2D layer bounds and camera",
                "game_rect": {"left": 472, "top": 164, "right": 872, "bottom": 264},
            },
            {"vtables": ["0xaf70d0", "0xaf7084", "0xaf7080"]},
        ]
        terms = {
            "vtables": ["0xaf79c8", "0xaf797c", "0xaf7978"],
            "address": "t",
            "login_page_candidate": "terms",
            "buttons": [
                {"control_id": 1, "enabled": True, "layout_x": 266, "layout_y": 374, "width": 75, "height": 32}
            ],
        }
        gender = {
            "vtables": ["0xaf7298", "0xaf724c", "0xaf7248"],
            "address": "g",
            "login_page_candidate": "gender",
            "width": 354,
            "height": 259,
            "game_rect": {"left": 595, "top": 160, "right": 949, "bottom": 419},
            "window_position_source": "stable Gr2D layer bounds and camera",
            "buttons": [
                {"control_id": 8002, "enabled": True, "layout_x": 190, "layout_y": 150, "width": 75, "height": 32}
            ],
        }
        terms_focus = {
            "address": "t",
            "vtables": terms["vtables"],
            "width": 431,
            "height": 426,
            "root_rect": {"left": 434, "top": 21, "right": 865, "bottom": 447},
        }
        login_focus = {
            "address": "login",
            "vtables": base[2]["vtables"],
            "width": 330,
            "height": 180,
            "game_rect": {"left": 622, "top": 288, "right": 952, "bottom": 468},
            "root_rect": {"left": 632, "top": 308, "right": 962, "bottom": 488},
            "buttons": [{"control_id": i} for i in range(1000, 1007)],
        }
        gender_focus = {
            "address": "g",
            "vtables": gender["vtables"],
            "game_rect": {"left": 595, "top": 160, "right": 949, "bottom": 419},
            "root_rect": {"left": 605, "top": 180, "right": 959, "bottom": 439},
        }

        def read(name, *args):
            page = state["page"]
            if name == "dialog":
                return {
                    "instance_id": "i",
                    "client": {"run_id": "r"},
                    "unavailable": [],
                    "script_dialog_open": False,
                    "focused_talk_dialog_open": False,
                    "registered_talk_dialog_open": False,
                    "focused_window": login_focus
                    if page == "login"
                    else terms_focus
                    if page == "terms"
                    else gender_focus,
                }
            self.assertEqual(name, "stage")
            result = {**self.stage, "game_geometry": geom, "renderer": "intel"}
            if page in ("login", "terms", "gender"):
                gender["raw_gender_selection"] = state["raw"]
                result.update(
                    stage="LOGIN", windows=base + ([terms] if page == "terms" else [gender] if page == "gender" else [])
                )
            elif page in ("world", "channel"):
                result.update(
                    stage="WORLD_SELECT" if page == "world" else "CHANNEL_SELECT",
                    windows=base[:2]
                    + world_extra
                    + ([{"vtables": ["0xaf7b4c", "0xaf7b00", "0xaf7afc"]}] if page == "channel" else []),
                    channel_panel={
                        "channels": [{"channel": 1, "root_rect": {"left": 20, "right": 40, "top": 30, "bottom": 50}}]
                    },
                )
            else:
                result.update(
                    stage="CHARACTER_SELECT",
                    world_id=0,
                    channel=1,
                    login={
                        "request_pending": False,
                        "transition_pending": False,
                        "characters_available": True,
                        "characters": [],
                    },
                    windows=base[:2]
                    + [
                        {"vtables": ["0xaf6f04", "0xaf6eb8", "0xaf6eb4"]},
                        world_extra[1],
                        world_extra[1],
                        {"vtables": ["0xaf6d90", "0xaf6d44", "0xaf6d40"]},
                    ],
                )
            return result

        def desktop(actions):
            action = actions[0]
            page = state["page"]
            if page == "login" and action["y"] == 356:
                base[2]["login_edit_focus"] = "password"
            elif page == "login" and action["x"] == 890:
                state["page"] = "terms"
            elif page == "terms":
                state["page"] = "gender"
            elif page == "gender" and action["x"] == 777:
                state["raw"] = 1
            elif page == "gender" and action["x"] == 832:
                state["page"] = "world"
            elif page == "world":
                state["page"] = "channel"
            elif page == "channel":
                state["page"] = "characters"
            return {
                "input_dispatched": True,
                "cancelled": False,
                "timings": [{"action": action["action"], "held_seconds": 0.1}],
            }

        def text(*args, **kwargs):
            if kwargs.get("payload") == "example":
                base[2]["account_empty"] = False
            elif kwargs.get("payload") == "secret":
                base[2]["password_empty"] = False

        self.backend.read.side_effect = read
        self.backend.desktop.side_effect = desktop
        self.backend.text.side_effect = text
        self.assertEqual(
            run(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female")["phase"],
            "character_list",
        )
        self.assertEqual(self.backend.text.call_count, 2)
        for marker in (
            "gui-login-submitted",
            "gui-terms-submitted",
            "gui-gender-selection",
            "gui-gender-submitted",
            "gui-world-submitted",
            "gui-channel-submitted",
        ):
            self.assertTrue((self.backend.runtime.run_dir / marker).exists(), marker)

    @patch("beidou_pilot.gui_login.time.monotonic", return_value=1)
    @patch("beidou_pilot.gui_login.load_runtime")
    @patch("beidou_pilot.gui_login._execute_locked", return_value={"phase": "character_list"})
    def test_external_deadline_is_forwarded_without_reset(self, locked, load, clock):
        from beidou_pilot.gui_login import execute as run
        load.return_value = self.backend.runtime
        run(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female", deadline=8)
        self.assertEqual(locked.call_args.kwargs["deadline"], 8)

    @patch("beidou_pilot.gui_login.time.monotonic", return_value=2)
    @patch("beidou_pilot.gui_login.load_runtime")
    def test_external_deadline_elapsed_in_preparation(self, load, clock):
        from beidou_pilot.gui_login import execute as run
        load.return_value = self.backend.runtime
        with self.assertRaises(ClientError) as error:
            run(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female", deadline=1)
        self.assertEqual(error.exception.code, "gui_login_timeout")
        self.backend.read.assert_not_called()
        self.backend.desktop.assert_not_called()
        self.assertFalse((self.backend.runtime.run_dir / "gui-login.lock").exists())

    @patch("beidou_pilot.gui_login.time.monotonic", side_effect=[0, 2])
    @patch("beidou_pilot.gui_login.load_runtime")
    def test_timeout_includes_runtime_preparation(self, load, clock):
        from beidou_pilot.gui_login import execute as run
        load.return_value = self.backend.runtime
        with self.assertRaises(ClientError) as error:
            run(self.backend, self.profile, instance_id="i", run_id="r", accept_terms=True, gender="female", timeout=1)
        self.assertEqual(error.exception.code, "gui_login_timeout")
        self.backend.desktop.assert_not_called()

    def test_character_list(self):
        self.stage.update(stage="CHARACTER_SELECT", world_id=0, channel=1)
        self.stage["windows"] = [
            {"vtables": v}
            for v in (
                ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"],
                ["0xaf7168", "0xaf711c", "0xaf7118"],
                ["0xaf6f04", "0xaf6eb8", "0xaf6eb4"],
                ["0xaf70d0", "0xaf7084", "0xaf7080"],
                ["0xaf70d0", "0xaf7084", "0xaf7080"],
                ["0xaf6d90", "0xaf6d44", "0xaf6d40"],
            )
        ]
        self.stage["login"].update(characters_available=True, characters=[])
        self.assertEqual(self.call()["phase"], "character_list")
        self.stage["world_id"] = 1
        with self.assertRaises(ClientError):
            self.call()
        self.stage.update(world_id=0, channel=2)
        with self.assertRaises(ClientError):
            self.call()
        self.backend.desktop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
