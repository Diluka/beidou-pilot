"""以静态资料规划单根绳梯/门户，持续控制与等待由客户端 Lua 执行。"""

import math
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .bridge import BridgeClient, BridgeSnapshot
from .catalog import Catalog
from .control_scripts import run_strategy


def _budget(seconds: float, min_hp_ratio: float) -> None:
    if not math.isfinite(seconds) or not 1 <= seconds <= 60:
        raise ClientError("invalid_travel_budget", "移动时间预算须为1至60秒。")
    if not math.isfinite(min_hp_ratio) or not 0 <= min_hp_ratio <= 1:
        raise ClientError("invalid_hp_limit", "HP安全比例须为0至1。")


def _initial(backend: Backend) -> BridgeSnapshot:
    state = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
    if not state["ready"] or state["character"] is None or state["position"] is None or state["map_id"] is None:
        raise ClientError("travel_observation_unavailable", "移动所需的原生角色、地图或位置尚不可用。")
    return state


def _options(seconds: float, min_hp_ratio: float) -> JsonObject:
    return {"budget_seconds": seconds, "min_hp_ratio": min_hp_ratio}


def climb(backend: Backend, x: int, to_y: int, *, direction: str | None = None,
          seconds: float = 20, tolerance: int = 10, min_hp_ratio: float = .25) -> JsonObject:
    _budget(seconds, min_hp_ratio)
    if direction not in {None, "up", "down", "Up", "Down"} or not 1 <= tolerance <= 40:
        raise ClientError("invalid_climb_direction", "请指定up/down，容差为1至40。")
    initial = _initial(backend)
    metadata = Catalog(backend.root).map(cast(int, initial["map_id"]))
    ropes = cast(list[JsonObject], metadata["ropes"])
    rope_top = next((rope["y1"] for rope in ropes
                     if abs(cast(float, rope["x"]) - x) <= 3 and abs(cast(float, rope["y1"]) - to_y) <= tolerance), None)
    options = {**_options(seconds, min_hp_ratio), "x": x, "y": to_y,
               "tolerance": tolerance, "direction": direction.lower() if direction else None, "rope_top": rope_top}
    report = run_strategy(backend, "travel/climb_to", options, seconds + 1, context_state=initial)
    final = cast(BridgeSnapshot, report["last_state"])
    if report["status"] == "completed":
        character, position = final["character"], final["position"]
        if (not final["ready"] or final["instance_id"] != initial["instance_id"]
                or final["map_id"] != initial["map_id"] or final["scene_generation"] != initial["scene_generation"]
                or character is None or character["id"] != cast(JsonObject, initial["character"])["id"]
                or position is None or abs(position["x"] - x) > 18 or abs(position["y"] - to_y) > tolerance):
            raise ClientError("climb_not_confirmed", "Lua已返回，最终绳梯位置或场景未确认。", {"after": cast(JsonObject, final)})
    return {**report, "status": "arrived" if report["status"] == "completed" else report["status"],
            "action": "climb", "target": {"x": x, "y": to_y},
            "before": cast(JsonObject, initial), "after": cast(JsonObject, final)}


def portal(backend: Backend, name: str, *, seconds: float = 20, catalog: Catalog | None = None,
           tolerance: int = 10, y_tolerance: int = 55, min_hp_ratio: float = .25) -> JsonObject:
    _budget(seconds, min_hp_ratio)
    if not 1 <= tolerance <= 50 or not 1 <= y_tolerance <= 150:
        raise ClientError("invalid_travel_tolerance", "水平容差须为1至50，平台高度容差须为1至150。")
    initial = _initial(backend)
    metadata = (catalog or Catalog(backend.root)).map(cast(int, initial["map_id"]))
    portals = cast(list[JsonObject], metadata["portals"])
    matches = [entry for entry in portals if entry.get("name") == name]
    if len(matches) != 1:
        raise ClientError("portal_not_unique", "静态资料未找到唯一同名门户，未输入。",
                          {"map_id": initial["map_id"], "name": name, "matches": matches,
                           "metadata_source": metadata["metadata_source"], "unavailable": metadata["unavailable"]})
    selected = matches[0]
    x, y, target_map = selected.get("x"), selected.get("y"), selected.get("target_map_id")
    if type(x) not in (int, float) or type(y) not in (int, float) or type(target_map) is not int:
        raise ClientError("portal_metadata_incomplete", "门户坐标或目的地图资料不完整，未输入。", {"portal": selected})
    position = initial["position"]
    assert position is not None
    if abs(position["y"] - cast(float, y)) > y_tolerance:
        raise ClientError("portal_other_layer", "门户位于另一层，请先按现场地形移动或爬绳。", {"portal": selected})
    destinations = [entry for entry in portals if entry.get("name") == selected.get("target_name")] if target_map == initial["map_id"] else []
    destination = destinations[0] if len(destinations) == 1 else None
    options: JsonObject = {**_options(seconds, min_hp_ratio), "x": x, "y": y,
                           "target_map": target_map, "tolerance": tolerance, "y_tolerance": y_tolerance}
    if destination is not None and type(destination.get("x")) is int and type(destination.get("y")) is int:
        options.update(destination_x=destination["x"], destination_y=destination["y"])
    report = run_strategy(backend, "travel/enter_portal", options, seconds + 3, context_state=initial)
    final = cast(BridgeSnapshot, report["last_state"])
    result: JsonObject = {**report, "action": "portal", "portal": selected,
                          "before": cast(JsonObject, initial), "after": cast(JsonObject, final)}
    if report["status"] != "completed":
        return result
    character, after = final["character"], final["position"]
    if (not final["ready"] or final["instance_id"] != initial["instance_id"]
            or character is None or character["id"] != cast(JsonObject, initial["character"])["id"] or after is None):
        raise ClientError("portal_identity_changed", "Lua已返回，最终角色和原生实例未确认。", {"after": cast(JsonObject, final)})
    if final["map_id"] != initial["map_id"]:
        if target_map != 999999999 and final["map_id"] != target_map:
            raise ClientError("portal_unexpected_map", "进入地图与静态目的地不符。", {"after": cast(JsonObject, final)})
        return {**result, "status": "arrived" if target_map != 999999999 else "transitioned",
                "destination_confirmed": target_map != 999999999, "verification": "client-map-changed"}
    if (destination is not None and "destination_x" in options
            and abs(after["x"] - cast(float, options["destination_x"])) <= 80
            and abs(after["y"] - cast(float, options["destination_y"])) <= 80
            and abs(after["x"] - cast(float, x)) + abs(after["y"] - cast(float, y)) > 60):
        return {**result, "status": "arrived", "verification": "client-position-at-same-map-destination"}
    raise ClientError("portal_transition_unconfirmed", "Lua已返回，未确认地图或同图目的地变化。", {"after": cast(JsonObject, final)})
