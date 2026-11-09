"""以当前普通商店 UI 为依据读取商品，交易通过普通鼠键完成。"""

import time
from typing import Literal, cast

from .backend import Backend, ClientError, JsonObject
from .catalog import Catalog
from .engines.character import CharacterSnapshot
from .engines.desktop import Action
from .engines.shop import ShopSnapshot
from .items import read_inventory
from .ui import click_control, click_window


def read_shop(backend: Backend) -> JsonObject:
    snapshot = backend.read("shop")
    catalog = Catalog(backend.root)
    for side in ("buy_items", "sell_items"):
        for item in cast(list[JsonObject], snapshot[side]):
            item["name"] = catalog.item_name(cast(int, item["item_id"]))
    return snapshot


def close_shop(backend: Backend) -> JsonObject:
    snapshot = cast(ShopSnapshot, backend.read("shop"))
    if snapshot["unavailable"]:
        raise ClientError("shop_unavailable", "当前商店状态不可用于确认关闭。",
                          {"unavailable": snapshot["unavailable"]})
    if not snapshot["open"]:
        return {"closed": True, "already_closed": True, "changed": False,
                "quantity_cancelled": False}
    window = snapshot["window"]
    if window is None:
        raise ClientError("shop_window_unavailable", "当前商店窗口不能唯一确认。")
    prompt = snapshot["quantity_dialog"]
    if prompt is not None:
        click_control(backend, prompt["window"], 2)
        deadline = time.monotonic() + 1.2
        snapshot = cast(ShopSnapshot, backend.read("shop"))
        while snapshot["quantity_dialog"] is not None:
            if time.monotonic() >= deadline:
                raise ClientError("shop_quantity_cancel_not_confirmed", "数量框取消后仍未关闭，未继续退出商店。")
            time.sleep(0.1)
            snapshot = cast(ShopSnapshot, backend.read("shop"))
        if snapshot["unavailable"]:
            raise ClientError("shop_unavailable", "取消数量框后商店状态不可用。",
                              {"unavailable": snapshot["unavailable"]})
    if snapshot["open"]:
        current = snapshot["window"]
        if current is None or current["address"] != window["address"]:
            raise ClientError("shop_window_changed", "取消数量框后商店窗口变化，未继续退出。")
        click_control(backend, current, 2)
        deadline = time.monotonic() + 1.2
        snapshot = cast(ShopSnapshot, backend.read("shop"))
        while snapshot["open"]:
            if time.monotonic() >= deadline:
                raise ClientError("shop_close_not_confirmed", "退出按钮已点击，商店仍未关闭。")
            time.sleep(0.1)
            snapshot = cast(ShopSnapshot, backend.read("shop"))
    if snapshot["unavailable"]:
        raise ClientError("shop_unavailable", "退出商店后读数不可用，未确认关闭。",
                          {"unavailable": snapshot["unavailable"]})
    return {"closed": True, "already_closed": False, "changed": True,
            "quantity_cancelled": prompt is not None}


def buy(backend: Backend, item_id: int, count: int = 1) -> JsonObject:
    return _trade(backend, "buy", item_id, count)


def sell(backend: Backend, item_id: int, count: int = 1, slot: int | None = None) -> JsonObject:
    return _trade(backend, "sell", item_id, count, slot)


def _trade(backend: Backend, direction: Literal["buy", "sell"], item_id: int, count: int,
           slot: int | None = None) -> JsonObject:
    if not 1 <= count <= 1000:
        raise ClientError("invalid_count", "单次交易数量须为 1 至 1000。")
    snapshot = cast(ShopSnapshot, backend.read("shop"))
    window = snapshot["window"]
    if not snapshot["open"] or window is None:
        raise ClientError("shop_closed", "请先正常打开普通 NPC 商店。")
    if snapshot["unavailable"] or window["vtables"][0] != "0xafe110":
        raise ClientError("shop_unavailable", "当前商店读数不可用于交易。",
                          {"unavailable": snapshot["unavailable"]})
    if snapshot["busy"] or snapshot["quantity_dialog"] is not None:
        raise ClientError("shop_transaction_pending", "当前商店已有待处理的交易。")
    inventory_type = item_id // 1000000
    if inventory_type not in (1, 2, 3, 4):
        raise ClientError("shop_item_unsupported", "只支持普通装备、消费、设置和其他物品。")
    if direction == "sell" and snapshot["sell_tab_index"] != inventory_type - 1:
        tab = next((tab for tab in snapshot["sell_tabs"] if tab["index"] == inventory_type - 1), None)
        if tab is None:
            raise ClientError("shop_tab_unavailable", "当前商店没有可确认的目标库存页签。")
        click_window(backend, window, 235 + (tab["left"] + tab["right"]) // 2, 105)
        snapshot = cast(ShopSnapshot, backend.read("shop"))
        if snapshot["sell_tab_index"] != inventory_type - 1:
            raise ClientError("shop_tab_not_confirmed", "商店卖出页签切换未确认。")
    side = "buy_items" if direction == "buy" else "sell_items"
    matches = [item for item in snapshot[side] if item["item_id"] == item_id
               and (slot is None or item["inventory_slot"] == slot)]
    if len(matches) != 1:
        raise ClientError("shop_item_ambiguous" if matches else "shop_item_missing",
                          "请按当前商店列表指定唯一物品；卖出多堆物品时指定库存槽位。",
                          {"item_id": item_id, "slot": slot})
    item = matches[0]
    price = item["unit_price"]
    if price is None or price < 0 or item["bundle_quantity"] > 1:
        raise ClientError("shop_price_unsupported", "当前商品涉及未覆盖的折扣、补充或成组交易。")
    if direction == "sell" and item["quantity"] < count:
        raise ClientError("insufficient_items", "选中库存槽位的数量不足。")
    wallet = cast(CharacterSnapshot, backend.read("character"))
    if not wallet["mesos_checksum_valid"] or wallet["mesos"] is None:
        raise ClientError("mesos_unavailable", "当前金币读数不可用。")
    money_before = wallet["mesos"]
    if direction == "buy" and money_before < price * count:
        raise ClientError("insufficient_mesos", "金币不足。",
                          {"available": money_before, "required": price * count})
    inventory = read_inventory(backend, inventory_type)
    quantities = [entry["quantity"] for entry in inventory["items"] if entry["item_id"] == item_id]
    if any(quantity is None for quantity in quantities):
        raise ClientError("inventory_unavailable", "交易物品的库存数量未知。")
    quantity_before = sum(cast(list[int], quantities))
    index = item["index"]
    first_field = "buy_first_index" if direction == "buy" else "sell_first_index"
    selected_field = "buy_selected_index" if direction == "buy" else "sell_selected_index"
    x = 85 if direction == "buy" else 315
    for _ in range(len(snapshot[side]) + 1):
        first = snapshot[first_field]
        if first is None:
            raise ClientError("shop_layout_unavailable", "当前商店滚动位置未知。")
        if first <= index < first + 5:
            break
        previous = first
        click_window(backend, window, x, 140)
        backend.read("desktop", "scroll", "up" if index < first else "down", "--ticks", "1")
        snapshot = cast(ShopSnapshot, backend.read("shop"))
        if snapshot["window"] is None or snapshot["window"]["address"] != window["address"] \
                or snapshot[first_field] == previous:
            raise ClientError("shop_scroll_not_confirmed", "商店列表滚动未确认，已停止交易。")
        window = snapshot["window"]
    first = snapshot[first_field]
    if first is None or not first <= index < first + 5:
        raise ClientError("shop_item_not_visible", "目标商品尚未进入可见行。")
    click_window(backend, window, x, 144 + (index - first) * 40)
    snapshot = cast(ShopSnapshot, backend.read("shop"))
    if snapshot[selected_field] != index:
        raise ClientError("shop_selection_not_confirmed", "未确认选中目标商品，已停止交易。")
    click_control(backend, window, 1000 if direction == "buy" else 1001)
    snapshot = cast(ShopSnapshot, backend.read("shop"))
    prompt = snapshot["quantity_dialog"]
    if prompt is None:
        raise ClientError("shop_quantity_dialog_missing", "交易按钮后未出现已识别的数量框，未继续确认。")
    if not prompt["minimum"] <= count <= prompt["maximum"]:
        raise ClientError("shop_quantity_out_of_range", "请求数量超出当前商店数量框范围。",
                          {"minimum": prompt["minimum"], "maximum": prompt["maximum"]})
    actions: list[Action] = [{"action": "hold", "keys": ["Control_L", "a"], "seconds": 0.06}]
    actions.extend({"action": "hold", "keys": [digit], "seconds": 0.06} for digit in str(count))
    actions.append({"action": "wait", "seconds": 0.1})
    backend.desktop(actions)
    snapshot = cast(ShopSnapshot, backend.read("shop"))
    typed = snapshot["quantity_dialog"]
    if typed is None or typed["window"]["address"] != prompt["window"]["address"] or typed["value"] != count:
        raise ClientError("shop_quantity_not_confirmed", "数量框实际值未等于请求数量，未提交交易。")
    click_control(backend, typed["window"], 1)
    expected_quantity = quantity_before + (count if direction == "buy" else -count)
    expected_money = money_before + (price * count if direction == "sell" else -price * count)
    deadline = time.monotonic() + 2
    while True:
        inventory = read_inventory(backend, inventory_type)
        quantities = [entry["quantity"] for entry in inventory["items"] if entry["item_id"] == item_id]
        if any(quantity is None for quantity in quantities):
            raise ClientError("inventory_unavailable", "提交交易后库存数量未知；请核对现场，勿重放交易。")
        quantity_after = sum(cast(list[int], quantities))
        wallet = cast(CharacterSnapshot, backend.read("character"))
        money_after = wallet["mesos"] if wallet["mesos_checksum_valid"] else None
        if (quantity_after == expected_quantity and money_after == expected_money) or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    details: JsonObject = {"direction": direction, "item_id": item_id, "count": count,
        "shop_quote": price, "mesos_before": money_before, "mesos_after": money_after,
        "quantity_before": quantity_before, "quantity_after": quantity_after,
        "quantity_changed": quantity_after == expected_quantity,
        "actual_total_price": abs(money_after - money_before) if money_after is not None else None}
    if quantity_after != expected_quantity or money_after != expected_money:
        raise ClientError("shop_trade_not_confirmed", "交易提交后金币与库存未同时符合预期；请核对现场，勿重放交易。", details)
    details["completed"] = True
    return details
