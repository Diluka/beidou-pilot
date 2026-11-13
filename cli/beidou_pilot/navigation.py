"""按目的地图从本地只读门户资料计算跨场景路线，并由客户端 Lua 逐段执行。

路线只来自原版地图资料的有向门户；脚本门户、出租车与飞艇等付费交通不进入静态路线。
场景内寻路由共享平台图和执行器完成，Python 只做资料读取、参数打包和最终结果投影。
"""

import math
from pathlib import Path
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .bridge import BridgeClient, BridgeSnapshot
from .catalog import Catalog
from .control_scripts import run_strategy
from .world_map import route, world_data

# 单次脚本要携带路线内每张地图地形；按 24 段上限控制脚本体积。
MAX_LEGS = 24


def _check_budget(seconds: float, min_hp_ratio: float) -> None:
    if not math.isfinite(seconds) or not 1 <= seconds <= 600:
        raise ClientError("invalid_navigation_budget", "导航时间预算须为1至600秒。")
    if not math.isfinite(min_hp_ratio) or not 0 <= min_hp_ratio <= 1:
        raise ClientError("invalid_hp_limit", "HP安全比例须为0至1。")


def _initial(backend: Backend) -> BridgeSnapshot:
    state = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
    if not state["ready"] or state["character"] is None or state["position"] is None or state["map_id"] is None:
        raise ClientError("navigation_observation_unavailable", "导航所需的原生角色、地图或位置尚不可用。")
    return state


def _compact_terrain(catalog: Catalog, map_id: int, name: str) -> JsonObject:
    """按数组打包 footholds/ropes；地图没有自身地形时明确拒绝，不借用链接地图。"""
    metadata = catalog.map(map_id)
    footholds = cast(list[JsonObject], metadata["footholds"])
    if not footholds:
        raise ClientError(
            "navigation_terrain_unavailable",
            "路线中的地图没有可用地形；不推断链接地图或空地形。",
            {"map_id": map_id, "name": name, "source": metadata.get("geometry_source")},
        )
    ropes = cast(list[JsonObject], metadata["ropes"])
    return {
        "footholds": [[f["id"], f["x1"], f["x2"], f["y1"], f["y2"], f["prev"], f["next"]] for f in footholds],
        "ropes": [[r["index"], r["x"], r["y1"], r["y2"]] for r in ropes],
    }


def route_plan(client_root: Path, start_map: int, goal_map: int) -> JsonObject:
    """计算静态路线并打包每段所需地形；不读取客户端运行状态。"""
    scenes = world_data(client_root)
    for map_id in (start_map, goal_map):
        if map_id not in scenes:
            raise ClientError("navigation_map_unknown", "地图不在本地世界地图资料里。", {"map_id": map_id})
    if start_map == goal_map:
        return {"start": start_map, "goal": goal_map, "goal_name": scenes[goal_map].name, "legs": [], "final": None}
    steps, _ = route(scenes, start_map, goal_map)
    if not steps:
        raise ClientError(
            "navigation_no_route",
            "本地门户资料中没有从起点到目的地图的有向路线。",
            {"start": start_map, "goal": goal_map},
        )
    if len(steps) > MAX_LEGS:
        raise ClientError(
            "navigation_route_too_long",
            "路线段数超过单次脚本上限。",
            {"start": start_map, "goal": goal_map, "legs": len(steps), "limit": MAX_LEGS},
        )
    catalog = Catalog(client_root)
    legs: list[JsonObject] = []
    for step in steps:
        map_id, target_map = int(cast(int, step["from"])), int(cast(int, step["to"]))
        portal_at = cast(list[list[int]], step["portal_at"])
        if not portal_at:
            raise ClientError(
                "navigation_portal_position_unknown",
                "门户在当前地图的入口坐标未知。",
                {"map_id": map_id, "portal": step["portal"], "target": target_map},
            )
        legs.append(
            {
                "map_id": map_id,
                "map_name": scenes[map_id].name,
                "portal": step["portal"],
                "portal_x": portal_at[0][0],
                "portal_y": portal_at[0][1],
                "target_map": target_map,
                "target_name": scenes[target_map].name,
                "terrain": _compact_terrain(catalog, map_id, scenes[map_id].name),
            }
        )
    return {
        "start": start_map,
        "goal": goal_map,
        "goal_name": scenes[goal_map].name,
        "legs": legs,
        "final": {"map_id": goal_map, "terrain": _compact_terrain(catalog, goal_map, scenes[goal_map].name)},
    }


def _route_summary(plan: JsonObject) -> list[JsonObject]:
    return [
        {
            "map_id": leg["map_id"],
            "map_name": leg["map_name"],
            "portal": leg["portal"],
            "target_map": leg["target_map"],
            "target_name": leg["target_name"],
        }
        for leg in cast(list[JsonObject], plan["legs"])
    ]


def navigate(
    backend: Backend,
    goal_map: int,
    *,
    x: int | None = None,
    y: int | None = None,
    seconds: float = 120,
    min_hp_ratio: float = 0.25,
    plan_only: bool = False,
) -> JsonObject:
    """从当前地图自动算路并逐段换图；给出 x/y 时在目的地图内继续走到目标坐标。"""
    _check_budget(seconds, min_hp_ratio)
    if (x is None) != (y is None):
        raise ClientError("invalid_navigation_target", "目的坐标需要同时给出水平与高度。")
    initial = _initial(backend)
    start_map = cast(int, initial["map_id"])
    plan = route_plan(backend.root, start_map, goal_map)
    route_rows = _route_summary(plan)
    if plan_only:
        return {
            "status": "planned",
            "action": "navigate",
            "from": start_map,
            "goal": goal_map,
            "goal_name": plan["goal_name"],
            "legs": route_rows,
            "before": cast(JsonObject, initial),
        }
    if start_map == goal_map:
        from . import travel

        if x is not None and y is not None:
            return {
                **travel.walk_to(backend, x, y, seconds=min(seconds, 120), min_hp_ratio=min_hp_ratio),
                "action": "navigate",
                "from": start_map,
                "goal": goal_map,
                "legs": [],
            }
        return {
            "status": "arrived",
            "action": "navigate",
            "from": start_map,
            "goal": goal_map,
            "goal_name": plan["goal_name"],
            "legs": [],
            "before": cast(JsonObject, initial),
            "after": cast(JsonObject, initial),
            "verification": "already-on-goal-map",
        }
    options: JsonObject = {
        "budget_seconds": max(1, min(seconds - 5, 580)),
        "min_hp_ratio": min_hp_ratio,
        "tolerance": 12,
    }
    if x is not None and y is not None:
        options.update({"goal_x": x, "goal_y": y})
    report = run_strategy(
        backend,
        "travel/navigate",
        options,
        seconds + 5,
        context_state=initial,
        context_extra={"route": plan},
    )
    final = cast(BridgeSnapshot, report["last_state"])
    result: JsonObject = {
        **report,
        "action": "navigate",
        "from": start_map,
        "goal": goal_map,
        "goal_name": plan["goal_name"],
        "legs": route_rows,
        "before": cast(JsonObject, initial),
        "after": cast(JsonObject, final),
    }
    if report["status"] != "completed":
        return result
    character, after = final["character"], final["position"]
    if (
        not final["ready"]
        or final["instance_id"] != initial["instance_id"]
        or final["map_id"] != goal_map
        or character is None
        or character["id"] != cast(JsonObject, initial["character"])["id"]
        or after is None
    ):
        raise ClientError(
            "navigation_map_mismatch",
            "Lua已返回，最终地图、角色或原生实例未确认。",
            {"goal_map": goal_map, "after": cast(JsonObject, final)},
        )
    if x is not None and y is not None and (abs(after["x"] - x) > 60 or abs(after["y"] - y) > 45):
        raise ClientError(
            "navigation_target_not_confirmed",
            "Lua已返回，已到达目的地图但未到达目的坐标。",
            {"target": {"x": x, "y": y}, "after": cast(JsonObject, final)},
        )
    return {**result, "status": "arrived", "verification": "client-map-and-position"}
