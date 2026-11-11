"""通用气泡CLI合同：未知种类、实际按钮和派发结果分别保留。"""

from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.cli import main
from beidou_pilot.engines.desktop import DesktopActions
from beidou_pilot.errors import ClientError, JsonObject
from .test_bridge import BridgeFiles


class NotificationContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = BridgeFiles(self.root)
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.present = True
        self.run_id = self.files.environment["RUN_ID"]
        self.button = {
            "control_id": 2001,
            "action": "dismiss",
            "layout_x": 20,
            "layout_y": 20,
            "width": 20,
            "height": 20,
        }
        self.notification = {
            "id": "current-window",
            "native_kind": 99,
            "kind": None,
            "source_text": None,
            "text": None,
            "sender_id": None,
            "party_id": None,
            "interaction_id": None,
            "quest_id": None,
            "expires_at_ms": None,
            "remaining_ms": None,
            "pending": True,
            "available": True,
            "window": {
                "width": 120,
                "height": 60,
                "root_rect": {"left": 10, "top": 10, "right": 130, "bottom": 70},
                "buttons": [self.button],
            },
            "buttons": [self.button],
        }

        def read(domain: str, *arguments: str) -> JsonObject:
            if domain != "notifications":
                raise AssertionError((domain, arguments))
            return {
                "instance_id": "client-1",
                "client": {"run_id": self.run_id},
                "scene_generation": 1,
                "notifications": [copy.deepcopy(self.notification)] if self.present else [],
            }

        self.read = self.enterContext(patch.object(Backend, "read", side_effect=read))
        self.desktop = self.enterContext(patch.object(Backend, "desktop", side_effect=self.dismiss))

    def dismiss(self, actions: DesktopActions) -> JsonObject:
        self.present = False
        return {}

    def invoke(self, *arguments: str) -> tuple[int, JsonObject]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(self.root), "--json", *arguments])
        return code, json.loads(output.getvalue())

    def reference(self) -> str:
        code, result = self.invoke("notifications")
        self.assertEqual(0, code, result)
        return result["data"]["notifications"][0]["ref"]

    def test_unknown_kind_with_one_button_and_no_timeout_can_be_observed_and_dismissed(self) -> None:
        code, result = self.invoke("notifications")
        notification = result["data"]["notifications"][0]
        self.assertEqual(0, code, result)
        self.assertEqual((99, None, None), (notification["native_kind"], notification["kind"], notification["text"]))
        self.assertIsNone(notification["expires_at_ms"])
        code, result = self.invoke("notifications", "respond", notification["ref"], "--button", "2001")
        self.assertEqual(0, code, result)
        self.assertTrue(result["data"]["input_dispatched"])
        self.assertFalse(result["data"]["after"]["present"])
        self.assertEqual("unknown", result["data"]["effect"])
        self.desktop.assert_called_once()

    def test_missing_button_never_dispatches_a_different_control(self) -> None:
        code, result = self.invoke("notifications", "respond", self.reference(), "--button", "2000")
        self.assertEqual((2, "notification_button_unavailable"), (code, result["error"]["code"]))
        self.desktop.assert_not_called()

    def test_primary_can_leave_the_notification_present_without_claiming_a_business_result(self) -> None:
        self.notification["native_kind"] = 4
        self.button.update(control_id=2000, action="primary")
        self.desktop.side_effect = None
        self.desktop.return_value = {}
        code, result = self.invoke("notifications", "respond", self.reference(), "--button", "2000")
        self.assertEqual(0, code, result)
        self.assertTrue(result["data"]["after"]["present"])
        self.assertTrue(result["data"]["after"]["pending"])
        self.assertEqual("unknown", result["data"]["effect"])
        self.desktop.assert_called_once()

    def test_old_run_and_expired_window_references_never_click(self) -> None:
        reference = self.reference()
        self.run_id = "run-2"
        code, result = self.invoke("notifications", "respond", reference, "--button", "2001")
        self.assertEqual((2, "stale_notification"), (code, result["error"]["code"]))
        reference = self.reference()
        self.notification["expires_at_ms"] = round(time.time() * 1000) - 1
        code, result = self.invoke("notifications", "respond", reference, "--button", "2001")
        self.assertEqual((2, "stale_notification"), (code, result["error"]["code"]))
        self.desktop.assert_not_called()

    def test_after_observation_failure_keeps_the_already_dispatched_input_explicit(self) -> None:
        reference = self.reference()

        def dispatch_then_observation_failure(actions: DesktopActions) -> JsonObject:
            self.read.side_effect = ClientError("native_observation_not_ready", "sampling paused")
            return {}

        self.desktop.side_effect = dispatch_then_observation_failure
        code, result = self.invoke("notifications", "respond", reference, "--button", "2001")
        self.assertEqual(0, code, result)
        self.assertTrue(result["data"]["input_dispatched"])
        self.assertIsNone(result["data"]["after"])
        self.assertEqual("native_observation_not_ready", result["data"]["observation_error"]["code"])
        self.desktop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
