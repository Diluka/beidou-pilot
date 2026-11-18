"""一次普通复活请求及其同角色效果核验合同。"""

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
        self.window = {
            "address": "0x1234",
            "vtables": ["0xb3b1a8"],
            "buttons": [{"control_id": 1, "enabled": True}],
        }

    @staticmethod
    def ui(windows: list[dict]) -> dict:
        return {"unavailable": [], "windows": windows}

    def test_gui_clicks_once_and_requires_same_character_recovery_and_closed_dialog(self) -> None:
        with (
            patch.object(self.backend, "read", side_effect=[self.before, self.after]),
            patch("beidou_pilot.recovery.read_ui", side_effect=[self.ui([self.window]), self.ui([])]),
            patch("beidou_pilot.recovery.click_control") as click,
        ):
            result = revive(self.backend)
        click.assert_called_once_with(self.backend, self.window, 1)
        self.assertEqual("revived", result["status"])
        self.assertTrue(result["changed"])
        self.assertEqual(7, result["state"]["character"]["id"])

    def test_gui_hp_recovery_with_confirmation_still_open_is_not_success(self) -> None:
        with (
            patch.object(self.backend, "read", side_effect=[self.before, self.after]),
            patch("beidou_pilot.recovery.read_ui", side_effect=[self.ui([self.window]), self.ui([self.window])]),
            patch("beidou_pilot.recovery.click_control") as click,
            patch("beidou_pilot.recovery.time.monotonic", side_effect=[0, 0, 0, 0, 7]),
            patch("beidou_pilot.recovery.time.sleep"),
        ):
            with self.assertRaises(ClientError) as raised:
                revive(self.backend)
        click.assert_called_once()
        self.assertEqual("revive_not_confirmed", raised.exception.code)

    def test_gui_unavailable_window_sample_is_not_treated_as_closed(self) -> None:
        unavailable = self.ui([])
        unavailable["unavailable"] = ["Scene camera is unavailable"]
        with (
            patch.object(self.backend, "read", side_effect=[self.before, self.after]),
            patch("beidou_pilot.recovery.read_ui", side_effect=[self.ui([self.window]), unavailable]),
            patch("beidou_pilot.recovery.click_control") as click,
            patch("beidou_pilot.recovery.time.monotonic", side_effect=[0, 0, 0, 0, 7]),
            patch("beidou_pilot.recovery.time.sleep"),
        ):
            with self.assertRaises(ClientError) as raised:
                revive(self.backend)
        click.assert_called_once()
        self.assertEqual("revive_not_confirmed", raised.exception.code)

    def test_alive_or_disabled_confirmation_never_clicks(self) -> None:
        alive = {**self.before, "character": {"id": 7, "hp": 1}}
        with (
            patch.object(self.backend, "read", return_value=alive),
            patch("beidou_pilot.recovery.read_ui") as ui,
            patch("beidou_pilot.recovery.click_control") as click,
        ):
            result = revive(self.backend)
        self.assertEqual("already_alive", result["status"])
        ui.assert_not_called()
        click.assert_not_called()

        disabled = {**self.window, "buttons": [{"control_id": 1, "enabled": False}]}
        with (
            patch.object(self.backend, "read", return_value=self.before),
            patch("beidou_pilot.recovery.read_ui", return_value=self.ui([disabled])),
            patch("beidou_pilot.recovery.click_control") as click,
        ):
            with self.assertRaises(ClientError) as raised:
                revive(self.backend)
        self.assertEqual("revive_layout_changed", raised.exception.code)
        click.assert_not_called()
