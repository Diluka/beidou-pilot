"""恢复品走客户端Lua，GUI专属物品保留实际入口。"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from beidou_pilot.backend import Backend
from beidou_pilot.errors import ClientError
from beidou_pilot.instances import InstancePaths
from beidou_pilot.items import use


class ItemUseContract(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temporary)
        self.backend = Mock(spec=Backend)
        self.backend.name = "beidou"
        self.backend.instance = "default"
        self.backend.root = self.root
        self.backend.paths = InstancePaths(self.root, "beidou")
        self.character = {"id": 6, "hp": 50, "max_hp": 100, "mp": 20, "max_mp": 30}
        self.observation = {"native_values_valid": True, "character": self.character,
                            "map_id": 100, "position": {"x": 10, "y": 20}, "unavailable": []}
        self.inventory = {"native_values_valid": True, "items": [
            {"inventory_type": 2, "slot": 1, "item_id": 2000000, "quantity": 4}], "unavailable": []}
        self.backend.read.side_effect = lambda name, *args: {
            "observe": self.observation, "inventory": self.inventory,
            "hotkeys": {"bindings": [{"type": 2, "id": 2000000, "key": "Shift_L", "key_code": 42}],
                        "unavailable": []}}[name]
        self.focus = self.enterContext(patch("beidou_pilot.items.focus_game"))
        self.bridge = self.enterContext(patch("beidou_pilot.control_scripts.BridgeClient")).return_value

    def metadata(self, item_id: int, properties: str) -> None:
        directory = self.root / "resources/wz/Item.wz/Consume"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{item_id // 10000:04d}.img.xml").write_text(
            f'<imgdir name="consume"><imgdir name="{item_id:08d}"><imgdir name="spec">'
            + properties + '</imgdir></imgdir></imgdir>')

    def complete(self, item_id: int, quantity: int, *, hp: int) -> None:
        self.bridge.run_script.return_value = {"status": "completed", "reason": "script_returned",
            "last_state": {"character": {**self.character, "hp": hp},
                           "inventory": [{"item_id": item_id, "quantity": quantity}]}}

    def test_gui_potion_uses_native_strategy_without_binding_lookup(self) -> None:
        self.metadata(2000000, '<int name="hp" value="50"/>')
        self.complete(2000000, 3, hp=100)
        result = use(self.backend, 2000000, count=2, until_hp=100)
        self.assertEqual("recovery/recover", result["strategy"])
        self.assertEqual("native_lua", result["input_method"])
        self.assertEqual(1, result["used"])
        self.assertEqual("target_reached", result["reason"])
        self.assertTrue(result["effect_confirmed"])
        self.assertIsNone(result["key"])
        self.assertNotIn("hotkeys", [call.args[0] for call in self.backend.read.call_args_list])
        self.backend.desktop.assert_not_called()

    def test_headless_count_does_not_require_optional_xml(self) -> None:
        self.backend.name = "headless"
        self.backend.paths = InstancePaths(self.root, "headless")
        self.complete(2000000, 2, hp=80)
        result = use(self.backend, 2000000, count=2)
        self.assertEqual(2, result["used"])
        self.assertEqual("count_reached", result["reason"])
        self.assertEqual("native_lua", result["input_method"])
        self.focus.assert_not_called()
        self.backend.desktop.assert_not_called()

    def test_unknown_healing_type_rejects_target_before_dispatch(self) -> None:
        self.backend.name = "headless"
        with self.assertRaises(ClientError) as failure:
            use(self.backend, 2000000, until_hp=90)
        self.assertEqual("healing_metadata_missing", failure.exception.code)
        self.bridge.run_script.assert_not_called()

    def test_headless_task_food_consumption_at_full_resources_preserves_unknown_recovery(self) -> None:
        self.backend.name = "headless"
        self.backend.paths = InstancePaths(self.root, "headless")
        self.character.update(hp=100, mp=30)
        self.inventory["items"] = [{"inventory_type": 2, "slot": 1, "item_id": 2010000, "quantity": 1}]
        self.complete(2010000, 0, hp=100)
        result = use(self.backend, 2010000)
        self.assertEqual(1, result["used"])
        self.assertEqual("count_reached", result["reason"])
        self.assertEqual("consumption", result["effect"])
        self.assertTrue(result["effect_confirmed"])
        self.assertIsNone(result["recovery_confirmed"])
        self.assertFalse(result["healing_metadata_known"])
        self.assertTrue(result["metadata_unavailable"])
        self.assertEqual("native_lua", result["input_method"])
        self.focus.assert_not_called()
        self.backend.desktop.assert_not_called()

    def test_headless_food_rejects_unrequested_multiple_consumption(self) -> None:
        self.backend.name = "headless"
        with self.assertRaises(ClientError) as failure:
            use(self.backend, 2010000, count=2)
        self.assertEqual("invalid_food_options", failure.exception.code)
        self.bridge.run_script.assert_not_called()

    def test_headless_other_consumables_are_explicitly_unsupported(self) -> None:
        self.backend.name = "headless"
        with self.assertRaises(ClientError) as failure:
            use(self.backend, 2030000)
        self.assertEqual("unsupported_capability", failure.exception.code)
        self.bridge.run_script.assert_not_called()

    def test_bound_food_remains_a_gui_consumable(self) -> None:
        self.metadata(2010001, '<int name="hp" value="50"/>')
        before = {**self.inventory, "items": [{"slot": 1, "item_id": 2010001, "quantity": 2}]}
        after = {**before, "items": [{"slot": 1, "item_id": 2010001, "quantity": 1}]}
        inventories = iter([before, after])
        observations = iter([self.observation, {**self.observation, "character": {**self.character, "hp": 100}}])
        hotkeys = {"bindings": [{"type": 2, "id": 2010001, "key": "z", "key_code": 44}], "unavailable": []}
        self.backend.read.side_effect = lambda name, *args: (
            next(observations) if name == "observe" else hotkeys if name == "hotkeys" else next(inventories))
        with patch("beidou_pilot.items.read_ui", return_value={"windows": []}):
            with patch("beidou_pilot.items._select_slot", return_value={"address": "inventory"}) as select:
                with patch("beidou_pilot.items.close_window", return_value={"closed": True}):
                    result = use(self.backend, 2010001)
        self.assertEqual("inventory", result["input_method"])
        self.assertEqual(1, result["used"])
        select.assert_called_once()
        self.bridge.run_script.assert_not_called()

    def test_teleport_scroll_retains_single_gui_use_and_map_confirmation(self) -> None:
        self.metadata(2030000, '<int name="moveTo" value="200"/>')
        before = {**self.inventory, "items": [{"slot": 1, "item_id": 2030000, "quantity": 1}]}
        after = {**before, "items": []}
        inventories = iter([before, after])
        observations = iter([self.observation, self.observation,
                             {**self.observation, "map_id": 200, "position": {"x": 0, "y": 0}}])
        self.backend.read.side_effect = lambda name, *args: (
            next(observations) if name == "observe" else next(inventories))
        ui = {"windows": [], "dialog": {"script_dialog_open": False,
              "focused_talk_dialog_open": False, "registered_talk_dialog_open": False}}
        with patch("beidou_pilot.items.read_ui", return_value=ui):
            with patch("beidou_pilot.items._select_slot", return_value={"address": "inventory"}) as select:
                result = use(self.backend, 2030000)
        self.assertEqual("inventory", result["input_method"])
        self.assertEqual(1, result["used"])
        self.assertEqual("teleport_confirmed", result["reason"])
        self.assertEqual(200, result["map_after"])
        select.assert_called_once()
        self.bridge.run_script.assert_not_called()


if __name__ == "__main__":
    unittest.main()
