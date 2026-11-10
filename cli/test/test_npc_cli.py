"""CLI到共享Lua的交互合同；原生替身不代表实际任务或奖励。"""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.cli import main


class NpcCliContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "clientctl.py").touch()
        self.dialog = {
            "dialog_open": True,
            "npc_id": 12101,
            "dialog_type": 4,
            "dialog_reference": "native:7:3",
            "lines": ["选择"],
            "choices": [{"link_id": 7, "text": "继续", "root_rect": None}],
            "buttons": [],
        }
        self.snapshot = {
            "stage": "IN_GAME",
            "scene_generation": 7,
            "dialog": {"open": False},
            "npcs": [
                {"object_id": 24, "template_id": 12101, "name": "瑞恩"},
                {"object_id": 25, "template_id": 12000, "name": "麦"},
                {"object_id": 26, "template_id": 12100, "name": "教官"},
            ],
        }

    def test_headless_npc_responses_and_explicit_quests_require_native_confirmation(self) -> None:
        cases = (
            ["talk", "12101"],
            ["dialog", "select", "7"],
            ["quest", "start", "1040", "--npc", "12000"],
            ["quest", "complete", "1041", "--npc", "12100", "--reward-choice", "0"],
        )
        report = {
            "status": "completed",
            "last_state": {
                "action_result": {
                    "dispatched": True,
                    "control_released": True,
                    "effect": "confirmed",
                    "reason": "native_confirmation",
                }
            },
        }
        for command in cases:
            with (
                self.subTest(command=command),
                patch("beidou_pilot.dialogs.collect", return_value=self.snapshot),
                patch.object(
                    Backend,
                    "read",
                    side_effect=lambda domain, *args: self.dialog if domain == "dialog" else {"quests": []},
                ),
                patch.object(Backend, "desktop") as desktop,
                patch("beidou_pilot.dialogs.run_source", return_value=report) as run,
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(0, main(["--root", str(self.root), "--backend", "headless", "--json", *command]))
                self.assertTrue(json.loads(output.getvalue())["data"]["confirmed"])
                self.assertEqual("headless", run.call_args.args[0].name)
                self.assertEqual(1, run.call_count)
                desktop.assert_not_called()

    def test_an_unconfirmed_completion_is_not_reported_as_success_or_replayed(self) -> None:
        report = {
            "status": "completed",
            "last_state": {
                "action_result": {
                    "dispatched": True,
                    "control_released": True,
                    "effect": "unknown",
                    "reason": "quest_not_confirmed",
                }
            },
        }
        with (
            patch("beidou_pilot.dialogs.collect", return_value=self.snapshot),
            patch("beidou_pilot.dialogs.run_source", return_value=report) as run,
        ):
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
                            "complete",
                            "1041",
                            "--npc",
                            "12100",
                        ]
                    ),
                )
        result = json.loads(output.getvalue())
        self.assertEqual("quest_not_confirmed", result["error"]["code"])
        self.assertEqual("unknown", result["error"]["details"]["action_result"]["effect"])
        self.assertEqual(1, run.call_count)

    def test_gui_does_not_gain_the_headless_quest_action(self) -> None:
        output = io.StringIO()
        with patch("beidou_pilot.dialogs.collect") as observed, redirect_stdout(output):
            self.assertEqual(
                2,
                main(
                    [
                        "--root",
                        str(self.root),
                        "--backend",
                        "beidou",
                        "--json",
                        "quest",
                        "start",
                        "1040",
                        "--npc",
                        "12000",
                    ]
                ),
            )
        self.assertEqual("unsupported_capability", json.loads(output.getvalue())["error"]["code"])
        observed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
