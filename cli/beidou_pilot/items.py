"""GUI 背包点击换装，并核对已装备负槽位。"""

import time
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .catalog import Catalog
from .engines.inventory import InventorySnapshot
from .ui import click_window, open_window, read_ui


# 以 CUIItem 原点为基准；已用普通开窗和现存截图校准。
BAG_EQUIP_TAB = (19, 34)


def _select_slot(backend: Backend, slot: int) -> None:
    window = open_window(backend, "inventory")
    click_window(backend, window, *BAG_EQUIP_TAB)
    window = next(item for item in read_ui(backend)["windows"] if item["address"] == window["address"])
    view = window["inventory"]
    if view is None or view["selected_type"] != 1:
        raise ClientError("inventory_tab_not_confirmed", "未确认背包切换到装备类型。")
    if view["expanded"]:
        raise ClientError("inventory_layout_unverified", "当前是展开背包，请先切回普通背包。")
    while not view["first_slot"] <= slot < view["first_slot"] + 24:
        direction = "up" if slot < view["first_slot"] else "down"
        previous_first = view["first_slot"]
        click_window(backend, window, 80, 90)
        backend.read("desktop", "scroll", direction, "--ticks", "1")
        window = next(item for item in read_ui(backend)["windows"] if item["address"] == window["address"])
        view = window["inventory"]
        if (view is None or view["selected_type"] != 1
                or (direction == "down" and view["first_slot"] <= previous_first)
                or (direction == "up" and view["first_slot"] >= previous_first)):
            raise ClientError("inventory_scroll_not_confirmed", "背包滚动未确认，已停止物品操作。")
    index = slot - view["first_slot"]
    # 客户端自身的普通背包槽位命中矩形中心；不依赖桌面偏移。
    click_window(backend, window, 24 + index % 4 * 36, 66 + index // 4 * 34, double=True)


def read_inventory(backend: Backend, inventory_type: int, *, equipped: bool = False) -> InventorySnapshot:
    arguments = ["--type", str(inventory_type)]
    if equipped:
        arguments.append("--equipped")
    snapshot = cast(InventorySnapshot, backend.read("inventory", *arguments))
    if snapshot["native_values_valid"] is not True or snapshot["unavailable"]:
        raise ClientError("inventory_unavailable", "当前背包读数不可用。",
                          {"unavailable": snapshot["unavailable"]})
    return snapshot


def equip(backend: Backend, item_id: int) -> JsonObject:
    before = read_inventory(backend, 1, equipped=True)
    wearing = next((item for item in before["equipped"] if item["item_id"] == item_id), None)
    if wearing:
        return {"item_id": item_id, "equipped": True, "changed": False, "slot": wearing["slot"]}
    item = next((item for item in before["items"] if item["item_id"] == item_id), None)
    if item is None:
        raise ClientError("item_missing", "装备背包中没有该物品。", {"item_id": item_id})
    slot = item["slot"]
    properties = item.get("equipment")
    if properties is None or not properties.get("object_ref"):
        raise ClientError("equipment_metadata_unavailable", "当前装备对象引用不可用，未执行换装。")
    if properties.get("ordinary") is not True:
        raise ClientError("unsupported_capability", "当前只支持已核实的普通装备。")
    slots = properties.get("body_slots")
    if not slots:
        raise ClientError("equipment_slot_requirement", "本端未提供当前角色可确认的兼容身上槽位。")
    # 客户端自身的双击命中矩形完成换装；不在 Python 侧猜目的槽位。
    _select_slot(backend, slot)
    deadline = time.monotonic() + 1.2
    after = read_inventory(backend, 1, equipped=True)
    wearing = next((entry for entry in after["equipped"] if entry["item_id"] == item_id), None)
    while wearing is None and time.monotonic() < deadline:
        time.sleep(0.1)
        after = read_inventory(backend, 1, equipped=True)
        wearing = next((entry for entry in after["equipped"] if entry["item_id"] == item_id), None)
    if wearing is None:
        raise ClientError("equip_not_confirmed", "双击后未在已装备负槽位确认该物品。",
                          {"item_id": item_id, "bag_slot": slot,
                           "requirements": Catalog(backend.root).item(item_id)["requirements"]})
    return {"item_id": item_id, "equipped": True, "changed": True,
            "bag_slot": slot, "slot": wearing["slot"]}
