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
        submit.assert_called_once_with(self.backend, self.profile, "i", "r")
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
    @patch("beidou_pilot.gui_login.time.monotonic", side_effect=[0, 1])
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
            with self.assertRaises(ClientError):
                _gender(self.backend, "i", "r", "male")
            self.backend.desktop.assert_not_called()
            dialog["focused_window"] = None
            with self.assertRaises(ClientError):
                _gender(self.backend, "i", "r", "male")
            self.backend.desktop.assert_not_called()
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
