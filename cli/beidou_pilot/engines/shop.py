"""通过原生观察API读取普通NPC商店，不派发交易。"""

import json
from typing import TypedDict, cast

from .ui import UIWindow
from ..observations import observe_domain, project_geometry


class ShopItem(TypedDict):
    index: int
    item_id: int
    unit_price: int | float | None
    raw_price: int
    quantity: int
    bundle_quantity: int
    inventory_type: int | None
    inventory_slot: int | None


class QuantityDialog(TypedDict):
    window: UIWindow
    text: str
    value: int | None
    minimum: int
    maximum: int


class ShopTab(TypedDict):
    index: int
    left: int
    right: int


class ShopSnapshot(TypedDict):
    observed_at: str
    source: str
    readonly: bool
    open: bool
    window: UIWindow | None
    npc_id: int | None
    buy_items: list[ShopItem]
    sell_items: list[ShopItem]
    buy_first_index: int | None
    sell_first_index: int | None
    buy_selected_index: int | None
    sell_selected_index: int | None
    busy: bool | None
    quantity_dialog: QuantityDialog | None
    sell_tab_index: int | None
    sell_tabs: list[ShopTab]
    unavailable: list[str]
    not_covered: list[str]


# 两处构造器均加载官方 Shop/backgrnd；实际列表布局仍需当前窗口校准。
# BeiDou.exe: 0x424312 -> 0xAF0AF8；0x75712F -> 0xAFE110。
SHOP_VTABLES = {"0xaf0af8", "0xafe110"}


def read_shop() -> ShopSnapshot:
    return cast(ShopSnapshot, project_geometry(observe_domain("shop")))


if __name__ == "__main__":
    print(json.dumps(read_shop(), ensure_ascii=False))
