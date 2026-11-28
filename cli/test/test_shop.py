"""普通商店轮询等待的离线合同（GUI 商店 #388）。"""

import itertools
import unittest
from unittest.mock import patch

from beidou_pilot import shop


def snapshot(**overrides):
    base = {
        "observed_at": "2026-01-01T00:00:00+00:00",
        "source": "test",
        "readonly": True,
        "open": True,
        "window": {
            "address": "0x1",
            "vtables": ["0xafe110"],
            "width": 300,
            "height": 200,
            "root_rect": {"left": 0, "top": 0, "right": 300, "bottom": 200},
            "buttons": [
                {"control_id": 1000, "layout_x": 10, "layout_y": 10, "width": 10, "height": 10},
                {"control_id": 1001, "layout_x": 20, "layout_y": 10, "width": 10, "height": 10},
            ],
            "type_name": None,
            "game_rect": None,
            "instance_ref": None,
        },
        "npc_id": 11100,
        "buy_items": [
            {
                "index": 0,
                "item_id": 2000000,
                "unit_price": 50,
                "bundle_quantity": 1,
                "quantity": None,
                "inventory_slot": None,
            }
        ],
        "sell_items": [
            {"index": 0, "item_id": 4000000, "unit_price": 10, "bundle_quantity": 1, "quantity": 2, "inventory_slot": 1}
        ],
        "buy_first_index": 0,
        "sell_first_index": 0,
        "buy_selected_index": None,
        "sell_selected_index": None,
        "busy": False,
        "quantity_dialog": None,
        "sell_tab_index": 2,
        "sell_tabs": [{"index": i, "left": 6 + i * 40, "right": 39 + i * 40} for i in range(5)],
        "unavailable": [],
        "not_covered": [],
    }
    base.update(overrides)
    return base


class FakeBackend:
    """商店假后端：desktop 动作提交后同步更新金币/背包，供确认轮询读取。"""

    def __init__(self, snapshots, item_id=2000000, quantity=0, mesos=1000):
        self.snapshots = list(snapshots)
        self.character = {"mesos": mesos, "mesos_checksum_valid": True}
        self.inventory = {"items": [{"item_id": item_id, "quantity": quantity, "slot": 3}]}

    def read(self, domain, *args):
        if domain == "shop":
            return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
        if domain == "character":
            return self.character
        if domain == "dialog":
            return {"focused_window": {"width": 505, "height": 116, "buttons": [{"control_id": 6}, {"control_id": 7}]}}
        raise AssertionError(f"unexpected domain {domain}")

    def desktop(self, actions):
        # 数量框提交（hold/wait 序列）即视为交易完成：金币/背包同步变化，供确认轮询读取
        self.character = {"mesos": self.character["mesos"] - 50, "mesos_checksum_valid": True}
        self.inventory = {"items": [{"item_id": 2000000, "quantity": 1}]}


class ShopPollingContract(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = patch.object(shop, "read_inventory", side_effect=lambda backend, *_: backend.inventory)
        self.inventory.start()
        self.addCleanup(self.inventory.stop)

    def test_buy_waits_for_selection_and_quantity_dialog(self) -> None:
        initial = snapshot()
        selected = snapshot(buy_selected_index=0)
        prompt = snapshot(
            buy_selected_index=0,
            quantity_dialog={
                "window": initial["window"],
                "text": "1",
                "value": 1,
                "minimum": 1,
                "maximum": 100,
                "buttons": [{"control_id": 2, "action": "ok"}],
            },
        )
        backend = FakeBackend([initial, selected, prompt])
        with patch.object(shop, "click_window"), patch.object(shop, "click_control"):
            result = shop.buy(backend, 2000000, 1)
        self.assertEqual(1, result["count"])
        self.assertEqual(950, backend.character["mesos"])

    def test_selection_timeout_reports_error(self) -> None:
        backend = FakeBackend([snapshot()])
        with (
            patch.object(shop.time, "monotonic", side_effect=itertools.count(0, 0.1)),
            patch.object(shop.time, "sleep"),
            patch.object(shop, "click_window"),
        ):
            with self.assertRaises(shop.ClientError) as raised:
                shop.buy(backend, 2000000, 1)
        self.assertEqual("shop_selection_timeout", raised.exception.code)

    def test_quantity_dialog_timeout_reports_error(self) -> None:
        backend = FakeBackend([snapshot(), snapshot(buy_selected_index=0)])
        with (
            patch.object(shop.time, "monotonic", side_effect=itertools.count(0, 0.1)),
            patch.object(shop.time, "sleep"),
            patch.object(shop, "click_window"),
            patch.object(shop, "click_control"),
        ):
            with self.assertRaises(shop.ClientError) as raised:
                shop.buy(backend, 2000000, 1)
        self.assertEqual("shop_quantity_dialog_timeout", raised.exception.code)

    def test_equipment_timeout_preserves_receipt_and_never_replays(self) -> None:
        item = {
            "index": 0,
            "item_id": 1060013,
            "unit_price": 10,
            "bundle_quantity": 1,
            "quantity": 1,
            "inventory_slot": 3,
        }
        backend = FakeBackend(
            [
                snapshot(sell_tab_index=0, sell_items=[item]),
                snapshot(sell_tab_index=0, sell_items=[item], sell_selected_index=0),
            ],
            item_id=1060013,
            quantity=1,
        )
        with (
            patch.object(shop.time, "monotonic", side_effect=itertools.count(0, 0.1)),
            patch.object(shop.time, "sleep"),
            patch.object(shop, "click_window"),
            patch.object(shop, "click_control") as click,
        ):
            with self.assertRaises(shop.ClientError) as raised:
                shop.sell(backend, 1060013, 1, 3)
        self.assertEqual("shop_quantity_dialog_timeout", raised.exception.code)
        self.assertEqual("unknown", raised.exception.details["trade_result"])
        self.assertEqual(3, raised.exception.details["inventory_slot"])
        self.assertEqual(505, raised.exception.details["focused_window"]["width"])
        self.assertEqual([6, 7], [b["control_id"] for b in raised.exception.details["focused_window"]["buttons"]])
        self.assertEqual(1, click.call_count)
        self.assertEqual(1, backend.inventory["items"][0]["quantity"])

    def test_equipment_confirmation_checks_slot_and_wallet(self) -> None:
        item = {
            "index": 0,
            "item_id": 1060013,
            "unit_price": 10,
            "bundle_quantity": 1,
            "quantity": 1,
            "inventory_slot": 3,
        }
        backend = FakeBackend(
            [
                snapshot(sell_tab_index=0, sell_items=[item]),
                snapshot(sell_tab_index=0, sell_items=[item], sell_selected_index=0),
            ],
            item_id=1060013,
            quantity=1,
        )
        read = backend.read
        confirm = {"width": 506, "height": 116, "buttons": [{"control_id": 6}, {"control_id": 7}]}

        def observe(domain, *args):
            return {"focused_window": confirm} if domain == "dialog" else read(domain, *args)

        def click(_backend, _window, control):
            if control == 6:
                backend.inventory = {"items": []}
                backend.character["mesos"] += 10

        with (
            patch.object(backend, "read", side_effect=observe),
            patch.object(shop, "click_window"),
            patch.object(shop, "click_control", side_effect=click) as controls,
        ):
            result = shop.sell(backend, 1060013, 1, 3)
        self.assertTrue(result["trade_result"] and result["slot_cleared"])
        self.assertEqual([1001, 6], [call.args[2] for call in controls.call_args_list])

    def test_equipment_confirmation_without_effect_is_unknown(self) -> None:
        item = {
            "index": 0,
            "item_id": 1060013,
            "unit_price": 10,
            "bundle_quantity": 1,
            "quantity": 1,
            "inventory_slot": 3,
        }
        backend = FakeBackend(
            [
                snapshot(sell_tab_index=0, sell_items=[item]),
                snapshot(sell_tab_index=0, sell_items=[item], sell_selected_index=0),
            ],
            item_id=1060013,
            quantity=1,
        )
        read = backend.read
        confirm = {"width": 506, "height": 116, "buttons": [{"control_id": 6}, {"control_id": 7}]}
        with (
            patch.object(
                backend,
                "read",
                side_effect=lambda domain, *a: {"focused_window": confirm} if domain == "dialog" else read(domain, *a),
            ),
            patch.object(shop.time, "monotonic", side_effect=itertools.count(0, 0.5)),
            patch.object(shop.time, "sleep"),
            patch.object(shop, "click_window"),
            patch.object(shop, "click_control") as click,
        ):
            with self.assertRaises(shop.ClientError) as raised:
                shop.sell(backend, 1060013, 1, 3)
        self.assertEqual("shop_trade_not_confirmed", raised.exception.code)
        self.assertEqual("unknown", raised.exception.details["trade_result"])
        self.assertEqual([1001, 6], [c.args[2] for c in click.call_args_list])


if __name__ == "__main__":
    unittest.main()
