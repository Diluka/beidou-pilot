"""bot_supply 补给/卖垃圾/装备建议的离线合同。"""

import unittest
from unittest.mock import patch

from tools import bot_supply


class BotSupplyContract(unittest.TestCase):
    def test_supply_plan_gaps_and_low_flags(self) -> None:
        character = {"level": 15, "job": 300, "hp": 397, "mp": 219, "mesos": 152, "map_id": 100000000}
        items = [
            {"item_id": bot_supply.RED_POTION, "quantity": 3, "inventory_type": 2},
            {"item_id": bot_supply.ARROW, "quantity": 40, "inventory_type": 2},
        ]
        with (
            patch.object(bot_supply, "read_character", return_value=character),
            patch.object(bot_supply, "read_items", return_value=items),
        ):
            plan = bot_supply.supply_plan("live/hero")
        self.assertEqual(22, plan["gaps"]["red"])  # 目标 25 - 现有 3
        self.assertEqual(560, plan["gaps"]["arrow"])  # 600 - 40
        self.assertTrue(plan["low"]["red"])
        self.assertTrue(plan["low"]["arrow"])
        self.assertEqual(22 * 50 + 15 * 100 + 560, plan["estimated_cost"])

    def test_targets_level_band(self) -> None:
        self.assertEqual((25, 15, 600), bot_supply.targets_for({"level": 15, "job": 300}))
        self.assertEqual((40, 30, 900), bot_supply.targets_for({"level": 30, "job": 300}))
        self.assertEqual((20, 10, 0), bot_supply.targets_for({"level": 9, "job": 400}))

    def test_junk_protects_quest_and_equipment(self) -> None:
        items = [
            {"item_id": 4000003, "quantity": 2, "inventory_type": 4},  # 任务树枝：保护
            {"item_id": 4000016, "quantity": 1, "inventory_type": 4},
            {"item_id": 4030000, "quantity": 1, "inventory_type": 4},  # 任务前缀：保护
            {"item_id": 4000999, "quantity": 5, "inventory_type": 4},  # 普通 etc：可卖
            {"item_id": 1452051, "quantity": 1, "inventory_type": 1},  # 装备默认不卖
        ]
        with (
            patch.object(bot_supply, "read_items", return_value=items),
            patch.object(bot_supply, "read_equipped", return_value={1452051}),
        ):
            plain = bot_supply.junk_list("live/hero", False)
            equipment = bot_supply.junk_list("live/hero", True)
        self.assertEqual([4000999], sorted(entry["item_id"] for entry in plain))
        self.assertEqual([4000999], sorted(entry["item_id"] for entry in equipment))
        self.assertNotIn(1452051, [entry["item_id"] for entry in equipment])

    def test_nearest_shop_selects_shortest_route(self) -> None:
        character = {"map_id": 100000000}
        with (
            patch.object(bot_supply, "read_character", return_value=character),
            patch.object(bot_supply, "route_legs", side_effect=[[1, 2, 3], [1]]),
        ):
            shop_map, shop = bot_supply.nearest_potion_shop("live/hero")
        self.assertEqual(1000003, shop_map)
        self.assertEqual("露茜", shop["npc"])

    def test_restock_dry_run_does_not_touch_client(self) -> None:
        plan = {"map_id": 100000000, "gaps": {"red": 10, "blue": 5, "arrow": 100}}
        with (
            patch.object(bot_supply, "supply_plan", return_value=plan),
            patch.object(bot_supply, "nearest_potion_shop", return_value=(100000102, {"npc": "卢娜", "legs": [1, 2]})),
        ):
            report = bot_supply.restock("live/hero", dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(100000102, report["shop_map"])
        self.assertEqual(10, report["buy"][bot_supply.RED_POTION])

    def test_gear_advice_filters_by_level(self) -> None:
        with patch.object(bot_supply, "read_character", return_value={"level": 15, "job": 300}):
            advice = bot_supply.gear_advice("live/hero")
        self.assertEqual(1, len(advice["suggestions"]))
        self.assertEqual(15, advice["suggestions"][0]["level"])

    def test_main_prints_json(self) -> None:
        with patch.object(bot_supply, "supply_plan", return_value={"level": 15}), patch("builtins.print") as printed:
            code = bot_supply.main(["status", "live/hero"])
        self.assertEqual(0, code)
        self.assertIn("level", "".join(str(call.args[0]) for call in printed.call_args_list))


if __name__ == "__main__":
    unittest.main()
