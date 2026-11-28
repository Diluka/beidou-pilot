"""只读现金商城并预检扩容；未建立原子输入安全边界。"""
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .observations import NativeObserver, project_geometry

_PRODUCTS = {
    "equip": (9111000, 50200093, 6400),
    "use": (9112000, 50200094, 6800),
    "setup": (9113000, 50200099, 6800),
    "etc": (9114000, 50200095, 6800),
}


def read_cashshop(backend: Backend) -> JsonObject:
    return project_geometry(NativeObserver(backend.root, backend.name, backend.instance).observe("cashshop"))


def expand(backend: Backend, item_type: str, count: int, dry_run: bool) -> JsonObject:
    if count != 1:
        raise ClientError("invalid_count", "当前仅支持每次预检一次扩容。")
    item_id, sn, price = _PRODUCTS[item_type]
    snapshot = read_cashshop(backend)
    grid = snapshot.get("grid")
    matches = []
    if snapshot.get("grid_count") == 1 and isinstance(grid, dict):
        items = grid.get("items")
        if isinstance(items, list):
            matches = [item for item in items if isinstance(item, dict)
                       and item.get("item_id_candidate") == item_id and item.get("sn_candidate") == sn
                       and item.get("price_candidate") == price and item.get("secure_value_checksum_valid") is True]
    blockers = []
    if snapshot.get("grid_count") != 1 or not isinstance(grid, dict):
        blockers.append("grid_unavailable")
    if snapshot.get("modal_count") != 0 or "modal" not in snapshot or snapshot["modal"] is not None:
        blockers.append("modal_present_or_unknown")
    if not isinstance(grid, dict) or grid.get("balance_checksums_valid") is not True:
        blockers.append("balance_unavailable")
    if len(matches) != 1:
        blockers.append("candidate_not_unique")
    blockers.extend(["atomic_click_unavailable", "external_input_exclusivity_unavailable", "final_version_not_validated"])
    plan: JsonObject = {
        "dry_run": dry_run, "state": "preflight_blocked", "input_dispatched": False,
        "requested": {"type": item_type, "count": count, "item_id_candidate": item_id,
                      "sn_candidate": sn, "unit_price_candidate": price},
        "candidate_matches": cast(list[JsonObject], matches), "blockers": blockers, "cashshop": snapshot,
    }
    if not dry_run:
        raise ClientError("cashshop_unverified", "商城原子校验和输入独占尚不可用；未发送输入。", plan)
    return plan
