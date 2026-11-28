"""现金商城只读探测；未经校准的交易和输入一律不派发。"""

from typing import cast

from .backend import Backend, ClientError, JsonObject

# 三个窗口的类型与尺寸来自开发服商城画面和同次 ui read；不能据此推断商品或余额。
_WINDOWS = {"0xaf1ca8": (545, 56), "0xaf1c24": (412, 430), "0xaf1ba0": (508, 78)}
_PRODUCTS = {
    "equip": (9111000, 50200093, 6400, 2006),
    "use": (9112000, 50200094, 6800, 2009),
    "setup": (9113000, 50200099, 6800, 2012),
    "etc": (9114000, 50200095, 6800, 2015),
}


def read_cashshop(backend: Backend) -> JsonObject:
    ui = backend.read("ui")
    windows = cast(list[JsonObject], ui["windows"])
    counts = {key: 0 for key in _WINDOWS}
    for window in windows:
        vtables = window.get("vtables")
        if not isinstance(vtables, list) or not vtables:
            continue
        key = vtables[0]
        if key in _WINDOWS and (window.get("width"), window.get("height")) == _WINDOWS[key]:
            counts[key] += 1
    observed = not ui.get("unavailable") and all(count == 1 for count in counts.values())
    return {
        "open": True if observed else None,
        "balance": {"nx": None, "credit_card": None, "coupon": None},
        "category": None,
        "page": None,
        "status": "candidate_open" if observed else "unknown",
        "not_covered": ["cashshop_closed", "balance", "category", "page", "product_identity", "coordinates"],
    }


def unavailable(backend: Backend, action: str) -> JsonObject:
    snapshot = read_cashshop(backend)
    raise ClientError(
        "cashshop_unverified", "现金商城操作尚未校准；未发送输入。", {"action": action, "cashshop": snapshot}
    )


def plan_expand(backend: Backend, item_type: str, count: int) -> JsonObject:
    if count < 1:
        raise ClientError("invalid_count", "扩展次数必须为正整数。")
    item_id, sn, price, button = _PRODUCTS[item_type]
    return {
        "dry_run": True,
        "cashshop": read_cashshop(backend),
        "requested": {"type": item_type, "count": count, "item_id": item_id, "sn": sn, "unit_price": price},
        "candidate": {"category": "其他/游戏", "page": 3, "button_id": button},
        "candidate_verified": False,
        "status": "unknown",
        "input_dispatched": False,
    }
