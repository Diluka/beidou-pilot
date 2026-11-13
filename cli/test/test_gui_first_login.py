"""单样本 GUI 登录原语的离线合同，不代表真实页面识别覆盖。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from beidou_pilot.errors import ClientError
from beidou_pilot.gui_first_login import submit_credentials_once
from beidou_pilot.profile import AccountProfile


class GuiFirstLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.backend = Mock()
        self.backend.name = "beidou"
        self.backend.runtime = SimpleNamespace(running=True, run_id="run", character_id=None,
                                               world=0, channel=0, run_dir=Path(self.temp.name))
        identity = {"instance_id": "instance", "client": {"run_id": "run"}}
        self.stage = {**identity, "stage": "LOGIN", "renderer": "intel",
                      "login": {"raw_step": 0, "request_pending": False, "transition_pending": False},
                      "game_geometry": {"x": 10, "y": 20, "width": 1280, "height": 720}}
        self.dialog = {**identity, "unavailable": [], "script_dialog_open": False,
                       "focused_talk_dialog_open": False, "registered_talk_dialog_open": False,
                       "focused_window": {"vtables": ["0xaf7940", "0xaf78f4", "0xaf78f0"],
                                          "width": 330, "height": 180,
                                          "game_rect": {"left": 622, "top": 288, "right": 952, "bottom": 468},
                                          "root_rect": {"left": 632, "top": 308, "right": 962, "bottom": 488},
                                          "buttons": [{"control_id": i} for i in range(1000, 1007)]}}
        self.backend.read.side_effect = lambda domain: self.stage if domain == "stage" else self.dialog
        self.profile = AccountProfile("example", "secret")

    def submit(self):
        return submit_credentials_once(self.backend, profile=self.profile,
                                       instance_id="instance", run_id="run")

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
