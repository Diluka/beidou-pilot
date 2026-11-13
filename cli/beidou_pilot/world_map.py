"""从本地原版地图资料生成世界地图 graph：按游戏区域分册，场景是节点，传送门是带坐标的边。

只读取静态 IMG 中的地图号、名称、门户坐标与目的地图，不读取客户端运行状态。
"""

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from .catalog import Catalog
from .img_resources import ImgDirectory

PORTAL_NAMED = 1  # 只有编号和名称的门户，两侧成对使用
PORTAL_MAP = 2  # 连到其他地图的门户
PORTAL_SCRIPT = 6  # 由服务端脚本决定去处的传送点
ENTRANCES = {PORTAL_NAMED, PORTAL_MAP, PORTAL_SCRIPT}
EXTERNAL_TARGET = 999999999
# 一个区域通常有 10 张以上带门户的场景；不足的单元并入同一地图组里够大的单元
REGION_SIZE = 10
LOCAL_LIMIT = 16


@dataclass(frozen=True)
class Scene:
    map_id: int
    name: str
    entity: int
    street: str | None
    portals: tuple[dict[str, int | str | None], ...]

    @property
    def named(self) -> list[dict[str, int | str | None]]:
        return [portal for portal in self.portals if portal["x"] is not None and portal["y"] is not None]


@dataclass(frozen=True)
class Region:
    entity: int
    name: str
    map_ids: list[int]


@dataclass(frozen=True)
class Edge:
    name: str
    target: int
    target_name: str | None
    script: str | None
    sources: tuple[tuple[int, int], ...]
    receivers: tuple[tuple[int, int], ...]


def world_data(client_root: Path) -> dict[int, Scene]:
    """带门户的地图；名称与街名取自 String/Map.img，门户取自各张地图。"""
    catalog = Catalog(client_root)
    names = _string_names(catalog)
    scenes = {}
    for map_id, portals in _map_data(catalog.root).items():
        scene_names = names.get(map_id, {})
        scenes[map_id] = Scene(map_id, scene_names.get("mapName") or f"地图{map_id}", map_id // 10000,
                               scene_names.get("streetName") or None, tuple(portals))
    return scenes


def _string_names(catalog: Catalog) -> dict[int, dict[str, str]]:
    """String/Map.img 里按地图号建立的 mapName、streetName；只取地图号节点。"""
    tree = catalog._tree("String/Map.img")
    names: dict[int, dict[str, str]] = {}
    for node in tree.iter() if tree is not None else ():
        key = node.get("name", "")
        if key.isdecimal() and len(key) >= 6:
            names[int(key)] = {child.get("name", ""): str(child.get("value"))
                               for child in node if child.get("value") is not None}
    return names


def regions_of(scenes: dict[int, Scene]) -> list[Region]:
    """地图号去掉后四位得到单元；小单元并入同一地图组（百位）里够大的单元。"""
    cells = sorted({scene.entity for scene in scenes.values()})
    sizes = Counter(scene.entity for scene in scenes.values())
    grouped: dict[int, list[int]] = defaultdict(list)
    for scene in scenes.values():
        enough = [cell for cell in cells if cell // 10 == scene.entity // 10 and sizes[cell] >= REGION_SIZE]
        grouped[min(enough) if enough else scene.entity].append(scene.map_id)
    regions = []
    for cell, map_ids in sorted(grouped.items()):
        map_ids.sort(key=lambda map_id: (scenes[map_id].entity, map_id))
        regions.append(Region(cell, _region_name(scenes, map_ids), map_ids))
    return regions


def _region_name(scenes: dict[int, Scene], map_ids: list[int]) -> str:
    """区域名取地图组里排第一的以 000 结尾的地图（城镇、门户或区域入口）的 mapName。

    街名太泛，金银岛、神秘岛这类名字会横跨十几个区域，不用。
    """
    start = next((map_id for map_id in map_ids if map_id % 1000 == 0), map_ids[0])
    scene = scenes[start]
    return scene.name if not scene.name.startswith("地图") else str(scene.map_id)


def _map_data(game_data: Path) -> dict[int, list[dict[str, int | str | None]]]:
    """全部地图的门户清单；没有门户的地图不返回。"""
    directory = ImgDirectory(game_data / "Map")
    result = {}
    for folder in sorted((game_data / "Map/Map").iterdir()):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix != ".img":
                continue
            tree, _ = directory.read_tree(("Map", folder.name, path.name))
            if tree is None:
                continue
            portals = []
            for node in tree.findall("./imgdir[@name='portal']/imgdir"):
                fields = {child.get("name", ""): child.get("value") for child in node}
                portals.append({
                    "index": int(node.get("name", "0")),
                    "name": fields.get("pn"),
                    "x": _int(fields.get("x")),
                    "y": _int(fields.get("y")),
                    "type": _int(fields.get("pt")) or 0,
                    "target": _int(fields.get("tm")),
                    "target_name": fields.get("tn") or None,
                    "script": fields.get("script") or None,
                })
            if portals:
                result[int(path.stem)] = portals
    return result


def _int(value: object) -> int | None:
    return int(str(value)) if value is not None and str(value).lstrip("-").isdecimal() else None


def receiver(scene: Scene, name: str | None) -> dict[str, int | str | None] | None:
    """目的地图里与门户 tn 同名的门户；找不到时按服务端做法落到 0 号门户。"""
    matches = [portal for portal in scene.named if portal["name"] == name]
    if len(matches) == 1:
        return matches[0]
    return next((portal for portal in scene.named if portal["index"] == 0), None)


def edges_of(scene: Scene, scenes: dict[int, Scene]) -> list[Edge]:
    """场景的跨场景传送门；同一门户名与同一目的地图的多个入口合并成一条边。"""
    sources: dict[tuple[int, str | None], list[tuple[int, int]]] = defaultdict(list)
    names: dict[tuple[int, str | None], str | None] = {}
    scripts: dict[tuple[int, str | None], str | None] = {}
    for portal in scene.named:
        target = portal["target"]
        if portal["type"] not in ENTRANCES or target in (None, EXTERNAL_TARGET):
            continue
        key = (int(target), portal["name"] if isinstance(portal["name"], str) else None)
        sources[key].append((int(portal["x"]), int(portal["y"])))
        names[key] = portal["target_name"] if isinstance(portal["target_name"], str) else None
        scripts[key] = portal["script"] if isinstance(portal["script"], str) else None
    edges = []
    for (target, name), points in sources.items():
        arrived = receiver(scenes[target], names[(target, name)]) if target in scenes else None
        edges.append(Edge(name or "", target,
                          arrived["name"] if arrived is not None else names[(target, name)],
                          scripts[(target, name)], tuple(points),
                          ((int(arrived["x"]), int(arrived["y"])),) if arrived is not None else ()))
    return edges


def _sites(points: tuple[tuple[int, int], ...]) -> str:
    return " ".join(f"{x},{y}" for x, y in points)


def scene_lines(scene: Scene, scenes: dict[int, Scene]) -> list[str]:
    xs = [int(portal["x"]) for portal in scene.named]
    ys = [int(portal["y"]) for portal in scene.named]
    lines = [f"### {scene.name} `{scene.map_id}`", f"平面 x {min(xs)}~{max(xs)}, y {min(ys)}~{max(ys)}"]
    for edge in edges_of(scene, scenes):
        if edge.target == scene.map_id:
            continue
        known = scenes[edge.target].name if edge.target in scenes else "区域外，见对应区域"
        destination = (f"目的门户 `{edge.target_name}` {_sites(edge.receivers)}" if edge.receivers
                       else f"目的门户 `{edge.target_name or 0}` 未找到同名门户，按服务端规则落到 0 号门户")
        lines.append(f"- `{edge.name}` {_sites(edge.sources)} → {edge.target} {known}；{destination}")
    local = [portal for portal in scene.named if portal["type"] not in ENTRANCES]
    if local:
        sites = " ".join(f"{portal['name']}@{portal['x']},{portal['y']}" for portal in local[:LOCAL_LIMIT])
        more = f" 等 {len(local)} 个" if len(local) > LOCAL_LIMIT else ""
        lines.append(f"- 出生点/局部传送点 {sites}{more}")
    lines.append("")
    return lines


def region_section(region: Region, scenes: dict[int, Scene]) -> str:
    lines = [f"## {region.name}", "", f"区域号 `{region.entity:05d}`，{len(region.map_ids)} 张场景。", ""]
    for map_id in region.map_ids:
        lines.extend(scene_lines(scenes[map_id], scenes))
    return "\n".join(lines)


def index(regions: list[Region]) -> str:
    lines = ["| 区域 | 区域号 | 场景数 | 地图号范围 |", "| --- | --- | --- | --- |"]
    for region in regions:
        lines.append(f'| {region.name} | `{region.entity:05d}` | {len(region.map_ids)} '
                     f'| {region.map_ids[0]}～{region.map_ids[-1]} |')
    return "\n".join(lines)


def route(scenes: dict[int, Scene], start: int, goal: int) -> tuple[list[dict[str, object]], bool]:
    """BFS 找从 start 到 goal 最少换几次场景。

    先只走单向门户；走不通时允许反向穿越两侧成对的 1 号门户（同一场景内两侧共用一张地图），
    返回结果会标成估计线路。港口、地铁和任务脚本等通路不在这里。
    """

    def search(bidirectional: bool) -> list[dict[str, object]] | None:
        reverse: dict[int, list[tuple[int, Edge]]] = defaultdict(list)
        if bidirectional:
            for scene in scenes.values():
                for edge in edges_of(scene, scenes):
                    if edge.name and edge.target in scenes:
                        reverse[edge.target].append((scene.map_id, edge))
        previous: dict[int, tuple[int, Edge, bool]] = {}
        queue = [start]
        visited = {start}
        while queue:
            current = queue.pop(0)
            moves = [(edge, False) for edge in edges_of(scenes[current], scenes)]
            if bidirectional:
                moves += [(edge, True) for _, edge in reverse.get(current, [])]
            for edge, reversed_ in moves:
                if edge.target not in scenes or edge.target == current or edge.target in visited:
                    continue
                visited.add(edge.target)
                previous[edge.target] = (current, edge, reversed_)
                if edge.target == goal:
                    queue.clear()
                    break
                queue.append(edge.target)
        if goal not in previous:
            return None
        steps: list[dict[str, object]] = []
        node = goal
        while node != start:
            origin, edge, reversed_ = previous[node]
            if reversed_:
                steps.append({"from": origin, "portal": edge.name, "to": edge.target,
                              "portal_at": [], "portal_at_destination": [], "script": edge.script,
                              "reversed": True, "source": list(edge.sources)})
                node = edge.target
            else:
                steps.append({"from": origin, "portal": edge.name, "to": node,
                              "portal_at": list(edge.sources), "portal_at_destination": list(edge.receivers),
                              "script": edge.script, "reversed": False})
                node = origin
        return list(reversed(steps))

    steps = search(False)
    if steps is not None:
        return steps, False
    return search(True) or [], True


def route_text(scenes: dict[int, Scene], start: int, goal: int) -> str:
    for map_id in (start, goal):
        if map_id not in scenes:
            return f"地图 {map_id} 没有门户数据，不在世界地图 graph 里。"
    if start == goal:
        return f"起点与终点相同（{start} {scenes[start].name}），无需换场景。"
    steps, estimated = route(scenes, start, goal)
    if not steps:
        return (f"从 {start} 到 {goal} 没有只用门户的线路；它们之间多半要港口乘船、地铁或任务脚本，"
                "这部分不在 graph 里，需要按攻略手动接上。")
    lines = [f"{start} {scenes[start].name} → {goal} {scenes[goal].name}，换 {len(steps)} 次场景："]
    for number, step in enumerate(steps, 1):
        origin, target = int(step["from"]), int(step["to"])
        if step["reversed"]:
            lines.append(f"{number}. 估计：从 {origin} {scenes[origin].name} 反向走对侧门户"
                         f"（原方向入口 `{step['portal']}` {_sites(tuple(step['source']))}）→ {target} {scenes[target].name}")
            continue
        arrival = (f"，落点 {_sites(tuple(step['portal_at_destination']))}" if step["portal_at_destination"]
                   else "，落点门户未找到，按服务端规则落到 0 号门户")
        script = "（脚本门户，可能另有条件）" if step["script"] else ""
        lines.append(f"{number}. {origin} {scenes[origin].name}：走 `{step['portal']}` "
                     f"{_sites(tuple(step['portal_at']))} → {target} {scenes[target].name}{arrival}{script}")
    if estimated:
        lines.append("注：其中含反向穿越的估计步骤，需现场确认。")
    return "\n".join(lines)
