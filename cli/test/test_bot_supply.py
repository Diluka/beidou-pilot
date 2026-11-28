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

    def test_equipment_preview_is_unknown_and_apply_fails_closed(self) -> None:
        items = [{"item_id": 1060013, "slot": 1, "quantity": 1, "inventory_type": 1}]
        with patch.object(bot_supply, "read_items", return_value=items), patch.object(bot_supply, "sell") as sell:
            preview = bot_supply.do_junk("dev/test", True, True)
            self.assertEqual([], preview["candidates"])
            self.assertEqual("instance_attributes_unavailable", preview["equipment_unknown"][0]["reason"])
            with self.assertRaises(SystemExit):
                bot_supply.do_junk("dev/test", False, True)
            sell.assert_not_called()

    def test_junk_apply_requires_explicit_confirmations(self) -> None:
        items = [
            {"item_id": 4000999, "slot": 3, "quantity": 5, "inventory_type": 4},
            {"item_id": 1060013, "slot": 1, "quantity": 1, "inventory_type": 1},
        ]
        with patch.object(bot_supply, "read_items", return_value=items), patch.object(bot_supply, "sell") as sell:
            preview = bot_supply.do_junk("dev/test", True, True, equipment_slots=(1,))
            self.assertEqual("instance_attributes_unavailable", preview["equipment_unknown"][0]["reason"])
            with self.assertRaisesRegex(SystemExit, "未指定人工确认"):
                bot_supply.do_junk("dev/test", False, False)
            sell.assert_not_called()

    def test_confirmed_slots_are_sold_in_current_shop(self) -> None:
        items = [
            {"item_id": 4000999, "slot": 3, "quantity": 5, "inventory_type": 4},
            {"item_id": 1060013, "slot": 1, "quantity": 1, "inventory_type": 1},
        ]
        with (
            patch.object(bot_supply, "read_items", return_value=items),
            patch.object(
                bot_supply, "read_shop", return_value={"open": True, "window": {"address": "x"}, "unavailable": []}
            ),
            patch.object(bot_supply, "sell", return_value={"completed": True, "trade_result": True}) as sell,
            patch.object(bot_supply, "travel") as travel,
        ):
            report = bot_supply.do_junk("dev/test", False, True, (1,), (4000999,), 6)
        self.assertEqual(2, len(report["results"]))
        self.assertEqual(
            [("dev/test", 4000999, 5, 3), ("dev/test", 1060013, 1, 1)], [call.args for call in sell.call_args_list]
        )
        travel.assert_not_called()

    def test_junk_rejects_protected_changed_and_unknown_receipt(self) -> None:
        protected = [{"item_id": 4000003, "slot": 3, "quantity": 1, "inventory_type": 4}]
        with patch.object(bot_supply, "read_items", return_value=protected), patch.object(bot_supply, "sell") as sell:
            with self.assertRaises(SystemExit):
                bot_supply.do_junk("dev/test", False, False, sell_etc=(4000003,))
            sell.assert_not_called()
        item = {"item_id": 1060013, "slot": 1, "quantity": 1, "inventory_type": 1}
        shop = {"open": True, "window": {"address": "x"}, "unavailable": []}
        with (
            patch.object(bot_supply, "read_items", side_effect=[[item], []]),
            patch.object(bot_supply, "read_shop", return_value=shop),
            patch.object(bot_supply, "sell") as sell,
        ):
            with self.assertRaisesRegex(SystemExit, "已变化"):
                bot_supply.do_junk("dev/test", False, False, equipment_slots=(1,))
            sell.assert_not_called()
        with (
            patch.object(bot_supply, "read_items", return_value=[item]),
            patch.object(bot_supply, "read_shop", return_value=shop),
            patch.object(bot_supply, "sell", return_value={"trade_result": "unknown"}) as sell,
        ):
            with self.assertRaisesRegex(SystemExit, "不重试"):
                bot_supply.do_junk("dev/test", False, False, equipment_slots=(1,))
            self.assertEqual(1, sell.call_count)

    def test_junk_preserves_completed_receipts_when_next_read_fails(self) -> None:
        items = [
            {"item_id": 1060013, "slot": 1, "quantity": 1, "inventory_type": 1},
            {"item_id": 1060014, "slot": 2, "quantity": 1, "inventory_type": 1},
        ]
        shop = {"open": True, "window": {"address": "x"}, "unavailable": []}
        with (
            patch.object(bot_supply, "read_items", side_effect=[items, items, SystemExit("失联")]),
            patch.object(bot_supply, "read_shop", return_value=shop),
            patch.object(bot_supply, "sell", return_value={"completed": True, "trade_result": True}) as sell,
        ):
            with self.assertRaises(SystemExit) as error:
                bot_supply.do_junk("dev/test", False, False, equipment_slots=(1, 2))
            self.assertIn('"item_id": 1060013', str(error.exception))
            self.assertIn("不重试", str(error.exception))
            self.assertEqual(1, sell.call_count)

    def test_junk_rejects_excess_and_invalid_slots_before_sale(self) -> None:
        items = [
            {"item_id": 1060013, "slot": 1, "quantity": 1, "inventory_type": 1},
            {"item_id": 4000999, "slot": 2, "quantity": 5, "inventory_type": 4},
        ]
        with patch.object(bot_supply, "read_items", return_value=items), patch.object(bot_supply, "sell") as sell:
            for slots, ids, limit in (((1, 1), (), 10), ((0,), (), 10), ((1,), (4000999,), 5), ((9,), (), 10)):
                with self.subTest(slots=slots, ids=ids), self.assertRaises(SystemExit):
                    bot_supply.do_junk("dev/test", False, False, slots, ids, limit)
            sell.assert_not_called()

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
            patch.object(bot_supply, "junk_list", return_value=[]),
        ):
            report = bot_supply.restock("live/hero", dry_run=True)
        self.assertTrue(report["dry_run"])
        self.assertEqual(100000102, report["shop_map"])
        self.assertEqual(10, report["buy"][bot_supply.RED_POTION])

    def test_restock_caps_budget_and_stops_on_partial_purchase(self) -> None:
        plan = {"map_id": 1, "gaps": {"red": 2, "blue": 0, "arrow": 100}}
        shop = {
            "buy_items": [
                {"item_id": bot_supply.RED_POTION, "unit_price": 10, "bundle_quantity": 1},
                {"item_id": bot_supply.ARROW, "unit_price": 2, "bundle_quantity": 1},
            ]
        }
        with (
            patch.object(bot_supply, "supply_plan", return_value=plan),
            patch.object(bot_supply, "nearest_potion_shop", return_value=(1, {"npc": "shop"})),
            patch.object(bot_supply, "junk_list", return_value=[]),
            patch.object(bot_supply, "ensure_gui"),
            patch.object(bot_supply, "open_shop"),
            patch.object(bot_supply, "close_shop") as close,
            patch.object(bot_supply, "read_character", return_value={"mesos": 1000}),
            patch.object(bot_supply, "read_shop", return_value=shop),
            patch.object(bot_supply, "buy", return_value={}) as buy,
            patch.object(bot_supply, "travel") as travel,
        ):
            with self.assertRaisesRegex(SystemExit, "上限不足"):
                bot_supply.restock("dev/test", False, max_cost=30, max_count=100)
        self.assertEqual([2, 5], [call.args[2] for call in buy.call_args_list])
        close.assert_called_once()
        travel.assert_not_called()

    def test_restock_sells_etc_first_and_checks_inventory(self) -> None:
        plan = {"map_id": 1, "gaps": {"red": 0, "blue": 0, "arrow": 3}}
        after = {"gaps": {"red": 0, "blue": 0, "arrow": 0}}
        calls = []
        with (
            patch.object(bot_supply, "supply_plan", side_effect=[plan, after]),
            patch.object(bot_supply, "nearest_potion_shop", return_value=(1, {"npc": "shop"})),
            patch.object(bot_supply, "junk_list", return_value=[{"item_id": 4000999, "quantity": 2}]),
            patch.object(bot_supply, "ensure_gui"),
            patch.object(bot_supply, "open_shop"),
            patch.object(bot_supply, "close_shop"),
            patch.object(bot_supply, "read_character", return_value={"mesos": 10}),
            patch.object(
                bot_supply,
                "read_shop",
                return_value={"buy_items": [{"item_id": bot_supply.ARROW, "unit_price": 1, "bundle_quantity": 1}]},
            ),
            patch.object(bot_supply, "sell", side_effect=lambda *args: calls.append("sell")),
            patch.object(bot_supply, "buy", side_effect=lambda *args: calls.append("buy")),
        ):
            report = bot_supply.restock("dev/test", False, sell_etc=(4000999,))
        self.assertEqual(["sell", "buy"], calls)
        self.assertEqual(after, report["after"])

    def test_travel_diagnostic_preserves_response_and_does_not_buy(self) -> None:
        import subprocess

        output = '{"error":"start","padding":"' + ("x" * 500) + '","end":true}'
        with (
            patch.object(bot_supply, "read_character", return_value={"map_id": 1}),
            patch.object(bot_supply, "write_route") as route,
            patch.object(
                bot_supply, "workbench", return_value=subprocess.CompletedProcess([], 1, output, "reason")
            ) as workbench,
        ):
            with self.assertRaises(SystemExit) as error:
                bot_supply.travel("dev/test", 2, 240)
        self.assertIn(output, str(error.exception))
        self.assertIn("尚未购买", str(error.exception))
        route.assert_called_once_with("dev/test", 1, 2)
        self.assertEqual("bot/supply_travel.lua", workbench.call_args.args[3])

    def test_travel_refuses_unconfirmed_destination(self) -> None:
        import subprocess

        with (
            patch.object(bot_supply, "read_character", side_effect=[{"map_id": 1}, {"map_id": 1}]),
            patch.object(bot_supply, "write_route"),
            patch.object(bot_supply, "workbench", return_value=subprocess.CompletedProcess([], 0, "{}", "")),
        ):
            with self.assertRaisesRegex(SystemExit, "未确认到达目标"):
                bot_supply.travel("dev/test", 2, 240)

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
