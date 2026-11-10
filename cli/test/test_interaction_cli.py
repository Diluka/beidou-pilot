"""通用控件激活的CLI消费合同；不以原生替身声称游戏结果。"""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.cli import main
from beidou_pilot.errors import ClientError


class InteractionCliContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "clientctl.py").touch()

    def test_headless_click_activates_once_without_python_target_resolution(self) -> None:
        result = {"dispatched": True, "control_released": True, "effect": "unknown", "reason": "control_activated"}
        report = {"status": "completed", "last_state": {"action_result": result}}
        with (
            patch("beidou_pilot.control_scripts.run_source", return_value=report) as run,
            patch.object(Backend, "read") as read,
            patch.object(Backend, "desktop") as desktop,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    0,
                    main(["--root", str(self.root), "--backend", "headless", "--json", "click", "opaque-control-ref"]),
                )
        self.assertEqual(result, json.loads(output.getvalue())["data"]["action_result"])
        self.assertEqual(1, run.call_count)
        read.assert_not_called()
        desktop.assert_not_called()

    def test_native_ref_rejection_is_not_refreshed_or_replayed_by_python(self) -> None:
        error = ClientError("bridge_script_error", "stale interaction ref")
        with (
            patch("beidou_pilot.control_scripts.run_source", side_effect=error) as run,
            patch.object(Backend, "read") as read,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    2, main(["--root", str(self.root), "--backend", "headless", "--json", "click", "old-control-ref"])
                )
        self.assertEqual("bridge_script_error", json.loads(output.getvalue())["error"]["code"])
        self.assertEqual(1, run.call_count)
        read.assert_not_called()

    def test_headless_does_not_turn_desktop_options_into_activation_options(self) -> None:
        with patch("beidou_pilot.control_scripts.run_source") as run:
            for arguments in (["click", "20", "30"], ["click", "opaque-control-ref", "--double"]):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(2, main(["--root", str(self.root), "--backend", "headless", "--json", *arguments]))
                self.assertEqual("unsupported_capability", json.loads(output.getvalue())["error"]["code"])
            run.assert_not_called()

    def test_withdrawn_quest_command_is_not_an_activation_alias(self) -> None:
        with patch("beidou_pilot.control_scripts.run_source") as run:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    2,
                    main(
                        [
                            "--root",
                            str(self.root),
                            "--backend",
                            "headless",
                            "--json",
                            "quest",
                            "start",
                            "1040",
                            "--npc",
                            "12000",
                        ]
                    ),
                )
        self.assertEqual("usage", json.loads(output.getvalue())["error"]["code"])
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
