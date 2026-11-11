"""GUI原生窗口/养成控制与鼠标释放合同，不运行游戏。"""

from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot import control_scripts, items
from beidou_pilot.errors import ClientError


class NativeCareContract(unittest.TestCase):
    def test_window_allocation_identity_and_reentrant_mouse_release(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "native-care-contract"
            subprocess.run(
                [
                    "g++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I" + str(root / "shared/lua-runtime"),
                    "-I" + str(root / "beidou-ijl15/ezorsia"),
                    str(root / "shared/lua-runtime/Observation.cpp"),
                    str(root / "cli/test/native_care_contract.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable)], check=True, timeout=10)


class GuiCareProjectionContract(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = SimpleNamespace(
            name="beidou", root=Path("."), read=lambda _: {"windows": [{"address": "0x64", "instance_ref": "window-1"}]}
        )

    def report(self, result, status="completed", session="current"):
        return {"script_id": session, "status": status, "last_state": {"action_result": result}}

    def test_gui_allocate_projects_partial_current_session_and_never_old_session(self) -> None:
        facts = {"kind": "ap", "stat": "intelligence", "requested": 2, "allocated": 1, "point_pending": True}
        result = {"session_id": "current", "effect": "unknown", "allocation": facts}
        with patch.object(control_scripts, "run_source", return_value=self.report(result)) as run:
            with self.assertRaises(ClientError) as failure:
                control_scripts.allocate(self.backend, "intelligence", 2)
            self.assertEqual(facts, failure.exception.details["allocation"])
            run.assert_called_once()
            self.assertIn('game.allocate_ap("intelligence", 2)', run.call_args.args[1])
        result["session_id"] = "previous"
        with patch.object(control_scripts, "run_source", return_value=self.report(result, "cancelled")) as run:
            report = control_scripts.allocate(self.backend, "intelligence", 2)
            self.assertIsNone(report["allocation"])
            self.assertIsNone(report["action_result"])
            self.assertFalse(report["confirmed"])
            run.assert_called_once()

    def test_window_cli_requires_current_native_identity_without_replay(self) -> None:
        result = {
            "session_id": "current",
            "effect": "confirmed",
            "dispatched": True,
            "ui": {"window": "stats", "open": True, "instance_ref": "window-1"},
        }
        with patch.object(control_scripts, "run_source", return_value=self.report(result)) as run:
            report = control_scripts.window(self.backend, "stats")
            self.assertEqual("0x64", report["address"])
            run.assert_called_once()
        self.backend.read = lambda _: {"windows": [{"address": "0x64", "instance_ref": "replacement-window"}]}
        with patch.object(control_scripts, "run_source", return_value=self.report(result)) as run:
            with self.assertRaises(ClientError) as failure:
                control_scripts.window(self.backend, "stats")
            self.assertEqual("ui_window_changed", failure.exception.code)
            run.assert_called_once()

    def test_gui_equipment_selects_one_native_slot_and_passes_exact_object_reference(self) -> None:
        item = {
            "inventory_type": 1,
            "slot": 1,
            "item_id": 1302000,
            "quantity": 1,
            "equipment": {"object_ref": "source-object", "ordinary": True, "body_slots": [-11]},
        }
        inventory = {"items": [item], "equipped": [], "native_values_valid": True, "unavailable": []}
        with patch.object(items, "read_inventory", return_value=inventory):
            with patch.object(items, "_select_slot") as desktop:
                with patch.object(control_scripts, "change_equipment", return_value={"confirmed": True}) as request:
                    result = items.equip(self.backend, 1302000)
        self.assertTrue(result["equipped"])
        self.assertEqual((self.backend, 1, -11), request.call_args.args)
        self.assertEqual("source-object", request.call_args.kwargs["reference"])
        desktop.assert_not_called()
        native_result = {"session_id": "current", "effect": "confirmed"}
        with patch.object(control_scripts, "run_source", return_value=self.report(native_result)) as run:
            control_scripts.change_equipment(self.backend, 1, -11, item_id=1302000, reference="source-object")
        self.assertIn('selected.equipment.object_ref == "source-object"', run.call_args.args[1])
        self.assertIn('game.equip(1, -11, 3, "source-object")', run.call_args.args[1])
