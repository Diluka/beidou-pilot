#!/usr/bin/env python3
"""分析当前地图的安全挂机平台：不刷怪、怪无法到达且玩家可达。

用法：

    tools/safe_platforms.py dev/NAME
    tools/safe_platforms.py dev/NAME --json

工具通过宿主工作台读取当前场景与静态地图资料：`inspect scene` 提供当前
地图和角色坐标，`inspect map <id>` 提供 footholds、ropes 与刷怪点。
平台由 footholds 按原生导航图相同的链式合并规则组装；移动边按本工具的
保守模型重建。安全平台必须同时满足：

* 平台上及平台边界内没有刷怪点；
* 怪物从刷怪平台出发无法通过行走或向下掉落到达；
* 玩家可从当前平台通过行走、下落、jumpup 或绳索到达。
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
import heapq
import json
from pathlib import Path
import subprocess
import sys


class SafePlatformError(Exception):
    """安全平台分析失败。"""


# 与 shared/lua-runtime/SceneNavigation.h 的 scene_navigation 常量保持一致。
@dataclass(frozen=True)
class Model:
    stand_height: float = 70.0
    jump_rise: float = 75.0
    drop_min: float = 4.0
    drop_max: float = 65.0
    rope_grab: float = 76.0
    jump_gap: float = 145.0
    speed: float = 100.0


@dataclass(frozen=True)
class Platform:
    index: int
    left: float
    right: float
    segments: tuple[tuple[float, float, float, float], ...]
    foothold_ids: tuple[int, ...]


@dataclass(frozen=True)
class Edge:
    kind: str
    source: int
    target: int
    x: float
    destination: float
    rise: float
    cost: float


@dataclass(frozen=True)
class MonsterSpawn:
    monster_id: int | None
    name: str | None
    x: float | None
    y: float | None
    platform: int | None
    located_by: str
    source: str


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(value: object) -> int | None:
    number = _number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _workbench_command(repo_root: Path, workbench: str, *arguments: str) -> list[str]:
    return [str(repo_root / "workbenches/workbench"), workbench, *arguments]


def _read_workbench(repo_root: Path, workbench: str, *arguments: str) -> dict[str, object]:
    result = subprocess.run(
        _workbench_command(repo_root, workbench, *arguments),
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SafePlatformError(f"{' '.join(arguments)} 返回无效 JSON：{error}") from error
    if not isinstance(response, dict):
        raise SafePlatformError(f"{' '.join(arguments)} 返回了非对象 JSON。")
    if response.get("ok") is not True:
        error = response.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        raise SafePlatformError(f"{' '.join(arguments)} 失败：{message or response.get('error')}")
    data = response.get("data")
    if not isinstance(data, dict):
        raise SafePlatformError(f"{' '.join(arguments)} 响应缺少 data 对象。")
    return data


def read_scene(repo_root: Path, workbench: str) -> dict[str, object]:
    return _read_workbench(repo_root, workbench, "inspect", "scene")


def read_map(repo_root: Path, workbench: str, map_id: int) -> dict[str, object]:
    return _read_workbench(repo_root, workbench, "inspect", "map", str(map_id))


def _foothold_fields(foothold: object) -> tuple[int, int, int, int, int, int]:
    if not isinstance(foothold, dict):
        raise SafePlatformError("inspect map 的 footholds 中存在非对象项。")
    fields = tuple(_integer(foothold.get(name)) for name in ("id", "x1", "x2", "y1", "y2", "prev", "next"))
    if any(value is None for value in fields):
        raise SafePlatformError(f"foothold 缺少整数字段：{foothold}")
    return fields  # type: ignore[return-value]


def merge_platforms(footholds: list[object]) -> list[Platform]:
    """按原生导航图相同的 foothold 链式合并规则组装水平平台。"""

    segments: list[dict[str, object]] = []
    for foothold in footholds:
        foothold_id, x1, x2, y1, y2, prev, next_id = _foothold_fields(foothold)
        if x1 == x2:
            continue
        left, right = (x1, x2) if x1 < x2 else (x2, x1)
        segments.append(
            {
                "id": foothold_id,
                "prev": prev,
                "next": next_id,
                "left": float(left),
                "right": float(right),
                "y1": float(y1 if x1 < x2 else y2),
                "y2": float(y2 if x1 < x2 else y1),
            }
        )
    if not segments:
        raise SafePlatformError("地图没有可用于组装平台的水平 foothold。")

    by_id: dict[int, int] = {}
    for index, segment in enumerate(segments):
        by_id[int(segment["id"])] = index
    assigned = [False] * len(segments)
    platforms: list[Platform] = []
    for seed in range(len(segments)):
        if assigned[seed]:
            continue
        parts = [seed]
        assigned[seed] = True
        cursor = 0
        while cursor < len(parts):
            part = segments[parts[cursor]]
            for neighbor_id in (int(part["prev"]), int(part["next"])):
                found = by_id.get(neighbor_id)
                if found is None or assigned[found]:
                    continue
                neighbor = segments[found]
                joins_right = part["right"] == neighbor["left"] and part["y2"] == neighbor["y1"]
                joins_left = part["left"] == neighbor["right"] and part["y1"] == neighbor["y2"]
                if not joins_right and not joins_left:
                    continue
                assigned[found] = True
                parts.append(found)
            cursor += 1
        parts.sort(key=lambda index: float(segments[index]["left"]))
        platform_segments = tuple(
            (
                float(segments[index]["left"]),
                float(segments[index]["right"]),
                float(segments[index]["y1"]),
                float(segments[index]["y2"]),
            )
            for index in parts
        )
        platforms.append(
            Platform(
                index=len(platforms) + 1,
                left=platform_segments[0][0],
                right=platform_segments[-1][1],
                segments=platform_segments,
                foothold_ids=tuple(int(segments[index]["id"]) for index in parts),
            )
        )
    return platforms


def platform_height(platform: Platform, x: float) -> float:
    """平台在 x 处的高度；x 先夹到平台范围内。y 向下为正。"""

    x = min(max(x, platform.left), platform.right)
    for left, right, y1, y2 in platform.segments:
        if x <= right:
            if right == left:
                return y1
            return y1 + (x - left) / (right - left) * (y2 - y1)
    left, right, y1, y2 = platform.segments[-1]
    if right == left:
        return y1
    return y1 + (x - left) / (right - left) * (y2 - y1)


def platform_at(platforms: list[Platform], x: float, y: float, tolerance: float) -> int | None:
    """与 bot/lib/terrain.lua 的 platform_at 同语义的最近平台查找。"""

    best_index: int | None = None
    best_distance: float | None = None
    for platform in platforms:
        if not platform.left <= x <= platform.right:
            continue
        for left, right, y1, y2 in platform.segments:
            if not left <= x <= right:
                continue
            if left == right:
                if y1 != y2:
                    continue
                height = y1
            else:
                height = y1 + (x - left) / (right - left) * (y2 - y1)
            distance = abs(y - height)
            if distance <= tolerance and (best_distance is None or distance < best_distance):
                best_index, best_distance = platform.index, distance
    return best_index


def platform_below(platforms: list[Platform], x: float, y: float) -> int | None:
    """x 正下方最近的平台，用于刷怪点位于平台上方空中时的落点。"""

    best_index: int | None = None
    best_height: float | None = None
    for platform in platforms:
        if not platform.left <= x <= platform.right:
            continue
        height = platform_height(platform, x)
        if height < y - 1:
            continue
        if best_height is None or height < best_height:
            best_index, best_height = platform.index, height
    return best_index


def _edge_cost(kind: str, x: float, destination: float, rise: float, model: Model) -> float:
    horizontal = abs(destination - x)
    if kind == "walk":
        return 0.05 + horizontal / max(1.0, model.speed)
    if kind == "jumpup":
        return 0.6 + horizontal / max(1.0, model.speed)
    if kind == "drop":
        return 0.4 + horizontal / max(1.0, model.speed)
    return 0.8 + abs(rise) / 100


def _add_edge(
    edges: dict[tuple[str, int, int], Edge],
    kind: str,
    source: Platform,
    target: Platform,
    x: float,
    destination: float,
    rise: float,
    model: Model,
) -> None:
    if source.index == target.index:
        return
    x = min(max(x, source.left), source.right)
    destination = min(max(destination, target.left), target.right)
    cost = _edge_cost(kind, x, destination, rise, model)
    key = (kind, source.index, target.index)
    previous = edges.get(key)
    if previous is None or cost < previous.cost:
        edges[key] = Edge(kind, source.index, target.index, x, destination, rise, cost)


def _pair_edges(edges: dict[tuple[str, int, int], Edge], a: Platform, b: Platform, model: Model) -> None:
    overlap_left = max(a.left, b.left)
    overlap_right = min(a.right, b.right)
    if overlap_right > overlap_left:
        # 从平台两端走落可以落到较低的目标平台；窄重叠也要检查。
        for edge_x in (a.left, a.right):
            if b.left <= edge_x <= b.right:
                rise = platform_height(a, edge_x) - platform_height(b, edge_x)
                if rise < -model.drop_min:
                    _add_edge(edges, "drop", a, b, edge_x, edge_x, rise, model)
        if overlap_right - overlap_left >= 10:
            x = (overlap_left + overlap_right) / 2
            rise = platform_height(a, x) - platform_height(b, x)
            if 6 < rise <= model.jump_rise:
                _add_edge(edges, "jumpup", a, b, x, x, rise, model)
            elif rise < -model.drop_min:
                _add_edge(edges, "drop", a, b, x, x, rise, model)
        return

    if a.right < b.left:
        gap = b.left - a.right
        source_x, target_x = a.right - 8, b.left + 8
    elif b.right < a.left:
        gap = a.left - b.right
        source_x, target_x = a.left + 8, b.right - 8
    else:
        gap = 0
        source_x, target_x = a.right, b.left
    rise = platform_height(a, source_x) - platform_height(b, target_x)
    if gap <= 2 and abs(rise) <= 6:
        _add_edge(edges, "walk", a, b, source_x, target_x, rise, model)
    if gap <= model.jump_gap and 6 < rise <= model.jump_rise:
        _add_edge(edges, "jumpup", a, b, source_x, target_x, rise, model)
    if gap <= model.drop_max and rise < -model.drop_min:
        _add_edge(edges, "drop", a, b, source_x, target_x, rise, model)


def _rope_edges(
    edges: dict[tuple[str, int, int], Edge], platforms: list[Platform], ropes: list[object], model: Model
) -> None:
    for rope in ropes:
        if not isinstance(rope, dict):
            raise SafePlatformError("inspect map 的 ropes 中存在非对象项。")
        rope_x = _number(rope.get("x"))
        y1 = _number(rope.get("y1"))
        y2 = _number(rope.get("y2"))
        if rope_x is None or y1 is None or y2 is None:
            raise SafePlatformError(f"rope 缺少数值字段：{rope}")
        touching: list[tuple[float, int]] = []
        for platform in platforms:
            if not platform.left <= rope_x <= platform.right:
                continue
            height = platform_height(platform, rope_x)
            if y1 - 12 <= height <= y2 + model.rope_grab:
                touching.append((height, platform.index))
        touching.sort()
        layers: list[tuple[float, int]] = []
        for height, index in touching:
            if layers and abs(layers[-1][0] - height) <= 6:
                layers[-1] = (layers[-1][0], min(layers[-1][1], index))
            else:
                layers.append((height, index))
        by_index = {platform.index: platform for platform in platforms}
        for lower, upper in zip(layers, layers[1:]):
            lower_platform, upper_platform = by_index[lower[1]], by_index[upper[1]]
            _add_edge(edges, "rope", lower_platform, upper_platform, rope_x, rope_x, upper[0] - lower[0], model)
            _add_edge(edges, "rope", upper_platform, lower_platform, rope_x, rope_x, lower[0] - upper[0], model)


def build_edges(platforms: list[Platform], ropes: list[object], model: Model) -> list[Edge]:
    edges: dict[tuple[str, int, int], Edge] = {}
    for a in platforms:
        for b in platforms:
            if a.index != b.index:
                _pair_edges(edges, a, b, model)
    _rope_edges(edges, platforms, ropes, model)
    return sorted(edges.values(), key=lambda edge: (edge.source, edge.target, edge.kind))


def shortest_paths(start: int, edges: list[Edge]) -> dict[int, tuple[float, list[Edge]]]:
    """Dijkstra；返回每个可达平台的最小代价和边序列。"""

    adjacency: dict[int, list[Edge]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source, []).append(edge)
    for outgoing in adjacency.values():
        outgoing.sort(key=lambda edge: (edge.target, edge.cost, edge.kind))
    distances: dict[int, float] = {start: 0.0}
    previous: dict[int, Edge] = {}
    queue: list[tuple[float, int, str]] = [(0.0, start, "")]
    while queue:
        cost, platform, kind = heapq.heappop(queue)
        if cost != distances.get(platform) or (platform != start and kind == ""):
            continue
        for edge in adjacency.get(platform, []):
            distance = cost + edge.cost
            current = distances.get(edge.target)
            if current is None or distance < current:
                distances[edge.target] = distance
                previous[edge.target] = edge
                heapq.heappush(queue, (distance, edge.target, edge.kind))
    paths: dict[int, tuple[float, list[Edge]]] = {}
    for platform in distances:
        path: list[Edge] = []
        cursor = platform
        while cursor != start:
            edge = previous[cursor]
            path.append(edge)
            cursor = edge.source
        path.reverse()
        paths[platform] = (distances[platform], path)
    return paths


def locate_monsters(monsters: list[object], platforms: list[Platform], model: Model, source: str) -> list[MonsterSpawn]:
    foothold_platform: dict[int, int] = {}
    for platform in platforms:
        for foothold_id in platform.foothold_ids:
            foothold_platform[foothold_id] = platform.index
    located: list[MonsterSpawn] = []
    for monster in monsters:
        if not isinstance(monster, dict):
            raise SafePlatformError(f"inspect {source} 的 monsters 中存在非对象项。")
        monster_id = _integer(monster.get("id"))
        if monster_id is None:
            monster_id = _integer(monster.get("template_id"))
        name = monster.get("name") if isinstance(monster.get("name"), str) else None
        x, y = _number(monster.get("x")), _number(monster.get("y"))
        foothold_id = _integer(monster.get("fh"))
        platform = foothold_platform.get(foothold_id) if foothold_id is not None else None
        located_by = "foothold"
        if platform is None and x is not None and y is not None:
            platform = platform_at(platforms, x, y, model.stand_height)
            located_by = "position"
        if platform is None and x is not None and y is not None:
            platform = platform_below(platforms, x, y)
            located_by = "below"
        if platform is None:
            located_by = "unlocated"
        located.append(MonsterSpawn(monster_id, name, x, y, platform, located_by, source))
    return located


def monster_reachability(
    spawns: list[MonsterSpawn], platforms: list[Platform], edges: list[Edge]
) -> dict[int, list[int]]:
    """从每个可疑刷怪平台出发，只走同平台行走与向下掉落；返回平台 -> 来源平台列表。"""

    roots: set[int] = set()
    unplaced = False
    for spawn in spawns:
        if spawn.platform is None:
            unplaced = True
        else:
            roots.add(spawn.platform)
    allowed = [edge for edge in edges if edge.kind in ("walk", "drop")]
    adjacency: dict[int, list[Edge]] = {}
    for edge in allowed:
        adjacency.setdefault(edge.source, []).append(edge)
    sources: dict[int, set[int]] = {}
    if unplaced:
        return {platform.index: [] for platform in platforms}
    for root in roots:
        reached = {root}
        queue = deque([root])
        while queue:
            platform = queue.popleft()
            for edge in adjacency.get(platform, []):
                if edge.target in reached:
                    continue
                reached.add(edge.target)
                queue.append(edge.target)
        for platform in reached:
            sources.setdefault(platform, set()).add(root)
    return {platform: sorted(roots) for platform, roots in sources.items()}


def _edge_summary(edge: Edge) -> dict[str, object]:
    return {
        "kind": edge.kind,
        "from": edge.source,
        "to": edge.target,
        "x": round(edge.x, 2),
        "destination": round(edge.destination, 2),
        "rise": round(edge.rise, 2),
        "cost": round(edge.cost, 3),
    }


def _platform_summary(platform: Platform) -> dict[str, object]:
    center = (platform.left + platform.right) / 2
    return {
        "platform": platform.index,
        "left": platform.left,
        "right": platform.right,
        "y": round(platform_height(platform, center), 2),
        "center_x": round(center, 2),
        "width": round(platform.right - platform.left, 2),
        "segments": [{"left": left, "right": right, "y1": y1, "y2": y2} for left, right, y1, y2 in platform.segments],
    }


def analyze(scene: dict[str, object], map_data: dict[str, object], model: Model) -> dict[str, object]:
    map_id = _integer(scene.get("map_id"))
    if map_id is None:
        raise SafePlatformError("inspect scene 缺少 map_id。")
    if _integer(map_data.get("id")) not in (None, map_id):
        raise SafePlatformError("inspect map 返回的地图号与当前场景不一致。")
    character = scene.get("player")
    if not isinstance(character, dict):
        character = scene.get("character")
    if not isinstance(character, dict):
        raise SafePlatformError("inspect scene 缺少角色坐标。")
    character_x, character_y = _number(character.get("x")), _number(character.get("y"))
    if character_x is None or character_y is None:
        raise SafePlatformError("inspect scene 的角色缺少数值坐标。")

    footholds = map_data.get("footholds")
    if not isinstance(footholds, list) or not footholds:
        raise SafePlatformError("inspect map 没有可用的 footholds（地图可能只有 link 引用）。")
    platforms = merge_platforms(footholds)
    current_platform = platform_at(platforms, character_x, character_y, model.stand_height)
    if current_platform is None:
        raise SafePlatformError(
            f"角色坐标 ({character_x:g}, {character_y:g}) 附近没有平台；请先落到地面或检查场景是否仍在转场。"
        )
    ropes = map_data.get("ropes")
    if ropes is None:
        ropes = []
    if not isinstance(ropes, list):
        raise SafePlatformError("inspect map 的 ropes 不是数组。")
    edges = build_edges(platforms, ropes, model)
    paths = shortest_paths(current_platform, edges)
    map_monsters = map_data.get("monsters")
    if map_monsters is None:
        map_monsters = []
    if not isinstance(map_monsters, list):
        raise SafePlatformError("inspect map 的 monsters 不是数组。")
    scene_monsters = scene.get("monsters")
    if scene_monsters is None:
        scene_monsters = []
    if not isinstance(scene_monsters, list):
        raise SafePlatformError("inspect scene 的 monsters 不是数组。")
    spawns = locate_monsters(map_monsters, platforms, model, "map")
    scene_spawns = locate_monsters(scene_monsters, platforms, model, "scene")
    spawns.extend(scene_spawns)
    spawn_platforms = sorted({spawn.platform for spawn in spawns if spawn.platform is not None})
    monster_sources = monster_reachability(spawns, platforms, edges)
    unplaced = [spawn for spawn in spawns if spawn.platform is None]

    safe_platforms: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for platform in platforms:
        monster_reachable = platform.index in monster_sources
        reasons: list[str] = []
        spawn_here = [spawn for spawn in spawns if spawn.platform == platform.index]
        if spawn_here:
            reasons.append("spawn")
        elif monster_reachable:
            reasons.append("monster_reachable")
        if unplaced:
            reasons.append("monster_unlocated")
        if platform.index not in paths:
            reasons.append("player_unreachable")
        if reasons:
            excluded.append(
                {
                    **_platform_summary(platform),
                    "reasons": reasons,
                    "spawn_monsters": [
                        {
                            "monster_id": spawn.monster_id,
                            "name": spawn.name,
                            "x": spawn.x,
                            "y": spawn.y,
                            "source": spawn.source,
                        }
                        for spawn in spawn_here
                    ],
                    "monster_sources": monster_sources.get(platform.index, []),
                    "monster_reachable": monster_reachable or bool(unplaced),
                    "player_reachable": platform.index in paths,
                }
            )
            continue
        cost, path = paths[platform.index]
        safe_platforms.append(
            {
                **_platform_summary(platform),
                "path": {
                    "length": len(path),
                    "cost": round(cost, 3),
                    "edges": [_edge_summary(edge) for edge in path],
                },
            }
        )
    safe_platforms.sort(key=lambda item: (item["path"]["cost"], item["platform"]))
    recommended = safe_platforms[0]["platform"] if safe_platforms else None

    return {
        "schema_version": 1,
        "map_id": map_id,
        "map_name": map_data.get("name"),
        "character": {
            "x": character_x,
            "y": character_y,
            "platform": current_platform,
        },
        "model": {
            "stand_height": model.stand_height,
            "jump_rise": model.jump_rise,
            "jump_gap": model.jump_gap,
            "drop_min": model.drop_min,
            "drop_max": model.drop_max,
            "rope_grab": model.rope_grab,
        },
        "counts": {
            "platforms": len(platforms),
            "spawn_platforms": len(spawn_platforms),
            "monster_reachable_platforms": len(monster_sources),
            "player_reachable_platforms": len(paths),
            "safe_platforms": len(safe_platforms),
            "edges": len(edges),
        },
        "spawn_platforms": spawn_platforms,
        "monster_reachable_platforms": sorted(monster_sources),
        "player_reachable_platforms": sorted(paths),
        "unplaced_monsters": [
            {
                "monster_id": spawn.monster_id,
                "name": spawn.name,
                "x": spawn.x,
                "y": spawn.y,
            }
            for spawn in unplaced
        ],
        "scene_monsters": [
            {
                "monster_id": spawn.monster_id,
                "name": spawn.name,
                "x": spawn.x,
                "y": spawn.y,
                "platform": spawn.platform,
                "located_by": spawn.located_by,
            }
            for spawn in scene_spawns
        ],
        "monster_spawns": [
            {
                "monster_id": spawn.monster_id,
                "name": spawn.name,
                "x": spawn.x,
                "y": spawn.y,
                "platform": spawn.platform,
                "located_by": spawn.located_by,
                "source": spawn.source,
            }
            for spawn in spawns
        ],
        "platforms": [_platform_summary(platform) for platform in platforms],
        "edges": [_edge_summary(edge) for edge in edges],
        "safe_platforms": safe_platforms,
        "excluded_platforms": excluded,
        "recommended_platform": recommended,
    }


def _path_text(item: dict[str, object]) -> str:
    path = item["path"]
    assert isinstance(path, dict)
    edges = path["edges"]
    assert isinstance(edges, list)
    if not edges:
        return "0 边（当前平台）"
    parts = [f"{edge['from']} --{edge['kind']}--> {edge['to']}" for edge in edges if isinstance(edge, dict)]
    return f"{path['length']} 边：" + "，".join(parts)


def format_text(result: dict[str, object]) -> str:
    counts = result["counts"]
    assert isinstance(counts, dict)
    character = result["character"]
    assert isinstance(character, dict)
    lines = [
        f"地图 {result['map_id']}（{result.get('map_name') or '未命名'}），"
        f"角色 ({character['x']:g}, {character['y']:g})，当前平台 {character['platform']}",
        f"平台 {counts['platforms']} 个；刷怪平台 {counts['spawn_platforms']} 个；"
        f"怪可达 {counts['monster_reachable_platforms']} 个；玩家可达 {counts['player_reachable_platforms']} 个；"
        f"移动边 {counts['edges']} 条。",
    ]
    unplaced = result["unplaced_monsters"]
    assert isinstance(unplaced, list)
    if unplaced:
        lines.append(f"警告：{len(unplaced)} 个刷怪点无法定位到平台，按全图不安全处理。")
    safe = result["safe_platforms"]
    assert isinstance(safe, list)
    if not safe:
        lines.append("安全平台 0 个：当前地图没有同时满足无刷怪点、怪不可达和玩家可达的平台。")
        return "\n".join(lines)
    recommendation = result["recommended_platform"]
    lines.append(f"安全平台 {len(safe)} 个（按路径代价排序）：")
    for item in safe:
        assert isinstance(item, dict)
        marker = " 推荐" if item["platform"] == recommendation else ""
        lines.append(
            f"  #{item['platform']} x=[{item['left']:g}, {item['right']:g}] y={item['y']:g}"
            f" 宽 {item['width']:g}；{_path_text(item)}{marker}"
        )
    lines.append(f"推荐站位：平台 #{recommendation}；也可从上面列表选择更近的安全平台。")
    excluded = result["excluded_platforms"]
    assert isinstance(excluded, list)
    lines.append(f"排除 {len(excluded)} 个平台：")
    for item in excluded:
        assert isinstance(item, dict)
        reasons = item["reasons"]
        assert isinstance(reasons, list)
        labels: list[str] = []
        if "spawn" in reasons:
            monsters = item["spawn_monsters"]
            assert isinstance(monsters, list)
            names = "、".join(
                f"{monster['name'] or monster['monster_id']}(x={monster['x']:g})"
                if monster["x"] is not None
                else f"{monster['name'] or monster['monster_id']}(坐标未知)"
                for monster in monsters
                if isinstance(monster, dict)
            )
            labels.append(f"有刷怪点：{names}")
        if "monster_reachable" in reasons:
            sources = item["monster_sources"]
            assert isinstance(sources, list)
            labels.append("怪可掉落到达（来自平台 " + "、".join(f"#{source}" for source in sources) + "）")
        if "monster_unlocated" in reasons:
            labels.append("存在无法定位的刷怪点")
        if "player_unreachable" in reasons:
            labels.append("玩家不可达")
        lines.append(
            f"  #{item['platform']} x=[{item['left']:g}, {item['right']:g}] y={item['y']:g}：" + "；".join(labels)
        )
    lines.append("安全判定：平台内无刷怪点，怪物只能同平台行走或向下掉落，玩家可从当前平台到达。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbench", help="live/NAME 或 dev/NAME")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--repo-root", type=Path, help="仓库根（默认按脚本位置推断）")
    parser.add_argument("--jump-rise", type=float, default=Model.jump_rise, help="jumpup 最大上升高度")
    parser.add_argument("--jump-gap", type=float, help="jumpup 最大水平间距（默认 jump_rise + stand_height）")
    parser.add_argument("--drop-max", type=float, default=Model.drop_max, help="从平台边缘下落的最大水平距离")
    parser.add_argument("--stand-height", type=float, default=Model.stand_height, help="角色或刷怪点的高度容差")
    parser.add_argument("--rope-grab", type=float, default=Model.rope_grab, help="绳索抓取高度")
    args = parser.parse_args(argv)
    if not (args.workbench.startswith("live/") or args.workbench.startswith("dev/")):
        parser.error("workbench 必须是 live/NAME 或 dev/NAME")
    if args.jump_rise <= 0 or args.drop_max <= 0 or args.stand_height <= 0 or args.rope_grab <= 0:
        parser.error("模型参数必须为正数")
    jump_gap = args.jump_gap if args.jump_gap is not None else args.jump_rise + args.stand_height
    if jump_gap <= 0:
        parser.error("jump_gap 必须为正数")
    model = Model(
        stand_height=args.stand_height,
        jump_rise=args.jump_rise,
        drop_max=args.drop_max,
        rope_grab=args.rope_grab,
        jump_gap=jump_gap,
    )
    repo_root = (args.repo_root or Path(__file__).resolve().parents[1]).resolve()
    try:
        scene = read_scene(repo_root, args.workbench)
        map_id = _integer(scene.get("map_id"))
        if map_id is None:
            raise SafePlatformError("inspect scene 缺少 map_id。")
        map_data = read_map(repo_root, args.workbench, map_id)
        result = analyze(scene, map_data, model)
    except SafePlatformError as error:
        print(f"安全平台分析失败：{error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
