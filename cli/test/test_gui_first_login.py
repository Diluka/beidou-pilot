"""单样本 GUI 登录原语的离线合同，不代表真实页面识别覆盖。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from beidou_pilot.bridge import require_input_idle
from beidou_pilot.errors import ClientError
from beidou_pilot.gui_first_login import submit_credentials_once
from beidou_pilot.profile import AccountProfile


class GuiFirstLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = Mock()
        self.backend.name = "beidou"
        self.bridge = patch("beidou_pilot.gui_first_login.BridgeClient").start()
        self.addCleanup(patch.stopall)
        self.bridge.return_value.snapshot.return_value = {
            "instance_id": "instance",
            "run_id": "run",
            "script": None,
            "scripts": [],
            "command": {"status": "idle"},
            "held_keys": [],
        }
        self.backend.runtime = SimpleNamespace(
            running=True, run_id="run", character_id=None, world=0, channel=0, run_dir=Path(self.temp.name)
        )
        identity = {"instance_id": "instance", "client": {"run_id": "run"}}
        self.stage = {
            **identity,
            "stage": "LOGIN",
            "renderer": "intel",
            "login": {"raw_step": 0, "request_pending": False, "transition_pending": False},
            "game_geometry": {"x": 10, "y": 20, "width": 1280, "height": 720},
            "windows": [
                {
                    "address": "window",
                    "vtables": ["0xaf7940", "0xaf78f4", "0xaf78f0"],
                    "login_edit_focus": "account",
                    "account_empty": True,
                    "password_empty": True,
                    "width": 330,
                    "height": 180,
                },
                {"address": "manager", "vtables": ["0xb3f13c", "0xb3f0f0", "0xb3f0ec"], "width": 1280, "height": 720},
                {"address": "sidebar", "vtables": ["0xaf7168", "0xaf711c", "0xaf7118"], "width": 125, "height": 352},
            ],
        }
        self.dialog = {
            **identity,
            "unavailable": [],
            "script_dialog_open": False,
            "focused_talk_dialog_open": False,
            "registered_talk_dialog_open": False,
            "focused_window": {
                "address": "window",
                "vtables": ["0xaf7940", "0xaf78f4", "0xaf78f0"],
                "width": 330,
                "height": 180,
                "game_rect": {"left": 622, "top": 288, "right": 952, "bottom": 468},
                "root_rect": {"left": 632, "top": 308, "right": 962, "bottom": 488},
                "buttons": [{"control_id": i} for i in range(1000, 1007)],
            },
        }
        self.backend.read.side_effect = lambda domain: self.stage if domain == "stage" else self.dialog

        def desktop(actions):
            if actions[0]["y"] == 356:
                self.stage["windows"][0]["login_edit_focus"] = "password"
            return {"cancelled": False, "input_dispatched": True, "timings": [{"action": "click"}]}

        def text(*args, **kwargs):
            if kwargs.get("payload") == "example":
                self.stage["windows"][0]["account_empty"] = False
            elif kwargs.get("payload") == "secret":
                self.stage["windows"][0]["password_empty"] = False

        self.backend.desktop.side_effect = desktop
        self.backend.text.side_effect = text
        self.profile = AccountProfile("example", "secret")

    def submit(self):
        return submit_credentials_once(self.backend, profile=self.profile, instance_id="instance", run_id="run")

    def test_submit_once_never_reports_authentication_success(self) -> None:
        result = self.submit()
        self.assertEqual("unknown", result["status"])
        self.assertTrue(result["credentials_submitted"])
        self.assertNotIn("secret", repr(result))
        self.assertEqual(0o600, (Path(self.temp.name) / "gui-login-submitted").stat().st_mode & 0o777)
        with self.assertRaises(ClientError) as error:
            self.submit()
        self.assertEqual("gui_login_already_attempted", error.exception.code)
        self.assertEqual(3, self.backend.desktop.call_count)

    def test_cli_dispatch_holds_one_real_input_lock(self) -> None:
        import json
        from contextlib import redirect_stdout
        from io import StringIO
        from beidou_pilot.cli import main

        root = Path(self.temp.name)
        account = root / "account.json"
        account.write_text(json.dumps({"username": "example", "password": "secret"}))
        account.chmod(0o600)
        self.backend.root = root
        self.backend.instance = "default"
        self.backend.paths = SimpleNamespace(state_directory=root, input_lock=root / "input.lock")
        with patch("beidou_pilot.cli.Backend", return_value=self.backend), redirect_stdout(StringIO()):
            self.assertEqual(
                0, main(["--json", "gui-login-experiment", "--instance-id", "instance", "--run-id", "run"])
            )
        self.assertEqual(3, self.backend.desktop.call_count)

    def test_busy_or_unavailable_native_bridge_never_sends_input(self) -> None:
        state = self.bridge.return_value.snapshot.return_value
        state["scripts"] = [{"status": "running", "control_released": False}]
        with self.assertRaises(ClientError):
            self.submit()
        self.backend.desktop.assert_not_called()
        state["scripts"] = []
        state["instance_id"] = "other"
        with self.assertRaises(ClientError):
            self.submit()
        self.bridge.return_value.snapshot.side_effect = ClientError("bridge_unavailable", "unavailable")
        with self.assertRaises(ClientError):
            self.submit()
        self.backend.text.assert_not_called()

    def test_other_running_session_and_missing_or_unreleased_list_are_blocked(self) -> None:
        state = self.bridge.return_value.snapshot.return_value
        state["script"] = {"status": "completed", "control_released": True}
        for scripts in (
            None,
            [{"status": "completed"}],
            [{"status": "completed", "control_released": False}],
            [{"status": "completed", "control_released": True}, {"status": "running", "control_released": False}],
        ):
            with self.subTest(scripts=scripts):
                state["scripts"] = scripts
                with self.assertRaises(ClientError):
                    self.submit()
                self.backend.text.assert_not_called()

    def test_other_session_starts_after_account_click_stops_username(self) -> None:
        def desktop(actions):
            self.bridge.return_value.snapshot.return_value["scripts"] = [
                {"status": "running", "control_released": False}
            ]
            return {"cancelled": False, "input_dispatched": True, "timings": [{"action": "click"}]}

        self.backend.desktop.side_effect = desktop
        with self.assertRaises(ClientError):
            self.submit()
        self.backend.text.assert_not_called()
        self.assertTrue((Path(self.temp.name) / "gui-login-submitted").exists())

    def test_other_session_starts_after_username_stops_password(self) -> None:
        def text(*args, **kwargs):
            if kwargs.get("payload") == "example":
                self.stage["windows"][0]["account_empty"] = False
                self.bridge.return_value.snapshot.return_value["scripts"] = [
                    {"status": "running", "control_released": False}
                ]

        self.backend.text.side_effect = text
        with self.assertRaises(ClientError):
            self.submit()
        self.assertNotIn("secret", [call.kwargs.get("payload") for call in self.backend.text.call_args_list])
        self.assertTrue((Path(self.temp.name) / "gui-login-submitted").exists())

    def test_idle_helper_rejects_missing_and_unknown_native_states(self) -> None:
        bridge = self.bridge.return_value
        baseline = {
            "instance_id": "instance",
            "run_id": "run",
            "scripts": [],
            "command": {"status": "idle"},
            "held_keys": [],
        }
        cases = [
            {key: value for key, value in baseline.items() if key != "scripts"},
            {**baseline, "scripts": [{"status": "unknown", "control_released": True}]},
            {**baseline, "command": {"status": "unknown"}},
            {**baseline, "command": {"status": "running"}},
            {**baseline, "held_keys": ["Left"]},
            {**baseline, "instance_id": "other"},
            {**baseline, "run_id": "other"},
        ]
        for state in cases:
            with self.subTest(state=state):
                bridge.snapshot.return_value = state
                with self.assertRaises(ClientError):
                    require_input_idle(bridge, "instance", "run")
        bridge.snapshot.return_value = baseline
        require_input_idle(bridge, "instance", "run")

    def test_cancelled_and_missing_click_confirmation_never_type(self) -> None:
        for result in (
            {"cancelled": True, "input_dispatched": False, "timings": []},
            {"cancelled": False, "input_dispatched": True, "timings": []},
        ):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as directory:
                self.backend.runtime.run_dir = Path(directory)
                self.backend.desktop.side_effect = None
                self.backend.desktop.return_value = result
                self.backend.text.reset_mock()
                with self.assertRaises(ClientError) as error:
                    self.submit()
                self.assertNotIn("secret", str(error.exception))
                self.backend.text.assert_not_called()
                self.assertTrue((Path(directory) / "gui-login-submitted").exists())

    def test_password_click_cancelled_stops_before_password(self) -> None:
        self.backend.desktop.side_effect = [
            {"cancelled": False, "input_dispatched": True, "timings": [{"action": "click"}]},
            {"cancelled": True, "input_dispatched": False, "timings": []},
        ]
        with self.assertRaises(ClientError):
            self.submit()
        self.assertNotIn("secret", [call.kwargs.get("payload") for call in self.backend.text.call_args_list])
        self.assertTrue((Path(self.temp.name) / "gui-login-submitted").exists())

    def test_form_change_after_username_stops_before_password(self) -> None:
        def text(*args, **kwargs):
            if kwargs.get("payload") == "example":
                self.stage = {**self.stage, "stage": "UNKNOWN"}

        self.backend.text.side_effect = text
        with self.assertRaises(ClientError):
            self.submit()
        self.assertNotIn("secret", [call.kwargs.get("payload") for call in self.backend.text.call_args_list])
        self.assertTrue((Path(self.temp.name) / "gui-login-submitted").exists())

    def test_nonempty_or_unknown_input_never_types(self) -> None:
        for field, value in (("account_empty", False), ("password_empty", False), ("account_empty", None)):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                self.backend.runtime.run_dir = Path(directory)
                self.stage["windows"][0][field] = value
                self.backend.text.reset_mock()
                with self.assertRaises(ClientError):
                    self.submit()
                self.backend.text.assert_not_called()
                self.assertTrue((Path(directory) / "gui-login-submitted").exists())
                self.stage["windows"][0][field] = True

    def test_wrong_focus_stops_before_private_input(self) -> None:
        self.stage["windows"][0]["login_edit_focus"] = "password"
        with self.assertRaises(ClientError):
            self.submit()
        self.backend.text.assert_not_called()
        with self.assertRaises(ClientError) as error:
            self.submit()
        self.assertEqual("gui_login_already_attempted", error.exception.code)

    def test_unknown_window_after_username_stops_before_password(self) -> None:
        def text(*args, **kwargs):
            if kwargs.get("payload") == "example":
                self.stage["windows"][0]["account_empty"] = False
                self.stage["windows"].append({"address": "modal", "vtables": ["unknown"], "width": 100, "height": 100})

        self.backend.text.side_effect = text
        with self.assertRaises(ClientError):
            self.submit()
        self.assertNotIn("secret", [call.kwargs.get("payload") for call in self.backend.text.call_args_list])
        self.assertTrue((Path(self.temp.name) / "gui-login-submitted").exists())

    def test_unknown_window_initially_never_inputs(self) -> None:
        self.stage["windows"].append({"address": "modal", "vtables": ["unknown"], "width": 100, "height": 100})
        with self.assertRaises(ClientError):
            self.submit()
        self.backend.text.assert_not_called()

    def test_uncertain_form_never_sends_input(self) -> None:
        self.dialog["focused_window"]["vtables"] = ["unknown"]
        with self.assertRaises(ClientError):
            self.submit()
        self.backend.desktop.assert_not_called()
        self.backend.text.assert_not_called()

    def test_failed_input_leaves_marker_and_blocks_replay(self) -> None:
        self.backend.desktop.side_effect = RuntimeError("input failure")
        with self.assertRaises(ClientError):
            self.submit()
        self.backend.desktop.side_effect = None
        with self.assertRaises(ClientError) as error:
            self.submit()
        self.assertEqual("gui_login_already_attempted", error.exception.code)


if __name__ == "__main__":
    unittest.main()
