"""从本地原版地图资料生成世界地图 graph：按游戏区域分册，场景是节点，传送门是带坐标的边。

只读取静态 IMG 中的地图号、名称、门户坐标与目的地图，不读取客户端运行状态。
"""

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

from .catalog import Catalog
from .img_resources import ImgDirectory

# 与客户端 Portal::Type 对应；脚本门户与包含脚本字段的普通门户不能静态保证目的地。
ENTRANCES = {1, 2, 3, 6, 10}
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
    link: int | None = None

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
    """带门户的地图；名称与街名取自 String.wz/Map.img，门户取自各张地图。"""
    catalog = Catalog(client_root)
    names = _string_names(catalog)
    scenes = {}
    for map_id, (portals, link) in _map_data(catalog.root).items():
        scene_names = names.get(map_id, {})
        scenes[map_id] = Scene(map_id, scene_names.get("mapName") or f"地图{map_id}", map_id // 10000,
                               scene_names.get("streetName") or None, tuple(portals), link)
    return scenes


def _string_names(catalog: Catalog) -> dict[int, dict[str, str]]:
    """String.wz/Map.img 里按地图号建立的 mapName、streetName；只取地图号节点。"""
    tree = catalog._tree("String.wz/Map.img.xml")
    names: dict[int, dict[str, str]] = {}
    for node in tree.iter() if tree is not None else ():
        key = node.get("name", "")
        if key.isdecimal():
            values = {child.get("name", ""): str(child.get("value"))
                      for child in node if child.get("value") is not None}
            if "mapName" in values or "streetName" in values:
                names[int(key)] = values
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


def _map_data(game_data: Path) -> dict[int, tuple[list[dict[str, int | str | None]], int | None]]:
    """读取每张地图的原始门户与 link；不将 link 推断为可通行边。"""
    root = game_data / ("Map002" if (game_data / "Map002").is_dir() else "Map")
    directory = ImgDirectory(root)
    result = {}
    for folder in sorted((root / "Map").iterdir()):
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
                    "type": _int(fields.get("pt")),
                    "target": _int(fields.get("tm")),
                    "target_name": fields.get("tn") or None,
                    "script": fields.get("script") or None,
                })
            link_node = tree.find("./imgdir[@name='info']/*[@name='link']")
            link = _int(link_node.get("value")) if link_node is not None else None
            result[int(path.stem)] = (portals, link)
    return result


def _int(value: object) -> int | None:
    return int(str(value)) if value is not None and str(value).lstrip("-").isdecimal() else None


def receiver(scene: Scene, name: str | None) -> dict[str, int | str | None] | None:
    """只返回唯一匹配的目标门户；缺失或重名时保留未知。"""
    matches = [portal for portal in scene.named if name is not None and portal["name"] == name]
    return matches[0] if len(matches) == 1 else None


def edges_of(scene: Scene, scenes: dict[int, Scene]) -> list[Edge]:
    """场景的跨场景传送门；同一门户名与同一目的地图的多个入口合并成一条边。"""
    sources: dict[tuple[int, str | None, str | None, str | None], list[tuple[int, int]]] = defaultdict(list)
    for portal in scene.named:
        target = portal["target"]
        if portal["type"] not in ENTRANCES or target in (None, EXTERNAL_TARGET):
            continue
        key = (int(target), portal["name"], portal["target_name"], portal["script"])
        sources[key].append((int(portal["x"]), int(portal["y"])))
    edges = []
    for (target, name, target_name, script), points in sources.items():
        arrived = receiver(scenes[target], target_name) if target in scenes else None
        edges.append(Edge(name or "", target,
                          arrived["name"] if arrived is not None else target_name,
                          script, tuple(points),
                          ((int(arrived["x"]), int(arrived["y"])),) if arrived is not None else ()))
    return edges


def _sites(points: tuple[tuple[int, int], ...]) -> str:
    return " ".join(f"{x},{y}" for x, y in points)


def scene_lines(scene: Scene, scenes: dict[int, Scene]) -> list[str]:
    xs = [int(portal["x"]) for portal in scene.named]
    ys = [int(portal["y"]) for portal in scene.named]
    bounds = f"门户坐标范围 x {min(xs)}~{max(xs)}, y {min(ys)}~{max(ys)}" if xs else "门户坐标未知"
    lines = [f"### {scene.name} `{scene.map_id}`", bounds]
    if scene.link is not None:
        lines.append(f"地图资源 link 指向 `{scene.link}`；本图未合并引用地图的门户，实际行为待核实。")
    for edge in edges_of(scene, scenes):
        if edge.target == scene.map_id:
            continue
        known = scenes[edge.target].name if edge.target in scenes else "区域外，见对应区域"
        destination = (f"目的门户 `{edge.target_name}` {_sites(edge.receivers)}" if edge.receivers
                       else f"目的门户 `{edge.target_name}` 的落点未知")
        qualifier = "（资源含脚本字段，去向及条件需核实）" if edge.script else "（静态候选，实际通行待核实）"
        lines.append(f"- `{edge.name}` {_sites(edge.sources)} → {edge.target} {known}；{destination}{qualifier}")
    lines.append("原始门户（编号、名称、类型、坐标、目标地图、目标门户、脚本）：")
    for portal in scene.portals:
        lines.append(f"- {portal['index']} `{portal['name']}` 类型 {portal['type']} "
                     f"坐标 ({portal['x']},{portal['y']}) → {portal['target']} "
                     f"`{portal['target_name']}` 脚本 `{portal['script']}`")
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
        lines.append(f'| [{region.name}](world-map/{region.entity:05d}.md) | `{region.entity:05d}` | {len(region.map_ids)} '
                     f'| {region.map_ids[0]}～{region.map_ids[-1]} |')
    return "\n".join(lines)


def route(scenes: dict[int, Scene], start: int, goal: int) -> tuple[list[dict[str, object]], bool]:
    """按资源中的有向门户执行 BFS；未记录反向边时不推断反向可达。"""
    previous: dict[int, tuple[int, Edge]] = {}
    queue = deque([start])
    visited = {start}
    while queue:
        current = queue.popleft()
        for edge in edges_of(scenes[current], scenes):
            if edge.script or edge.target not in scenes or edge.target in visited:
                continue
            visited.add(edge.target)
            previous[edge.target] = (current, edge)
            if edge.target == goal:
                queue.clear()
                break
            queue.append(edge.target)
    if goal not in previous:
        return [], False
    steps: list[dict[str, object]] = []
    node = goal
    while node != start:
        origin, edge = previous[node]
        steps.append({"from": origin, "portal": edge.name, "to": node,
                      "portal_at": list(edge.sources), "portal_at_destination": list(edge.receivers),
                      "script": edge.script, "reversed": False})
        node = origin
    return list(reversed(steps)), False


def route_text(scenes: dict[int, Scene], start: int, goal: int) -> str:
    for map_id in (start, goal):
        if map_id not in scenes:
            return f"地图 {map_id} 没有门户数据，不在世界地图 graph 里。"
    if start == goal:
        return f"起点与终点相同（{start} {scenes[start].name}），无需换场景。"
    steps, estimated = route(scenes, start, goal)
    if not steps:
        return (f"从 {start} 到 {goal} 未在已收录的有向门户中找到线路；原因可能是资料不完整、"
                "需要其他交通方式，或确实不可达，不能仅凭此结果判断。")
    lines = [f"{start} {scenes[start].name} → {goal} {scenes[goal].name}，换 {len(steps)} 次场景：",
             "静态候选路线，未核实场景内可达性、任务条件及当前服务器行为。"]
    for number, step in enumerate(steps, 1):
        origin, target = int(step["from"]), int(step["to"])
        if step["reversed"]:
            lines.append(f"{number}. 估计：从 {origin} {scenes[origin].name} 反向走对侧门户"
                         f"（原方向入口 `{step['portal']}` {_sites(tuple(step['source']))}）→ {target} {scenes[target].name}")
            continue
        arrival = (f"，落点 {_sites(tuple(step['portal_at_destination']))}" if step["portal_at_destination"]
                   else "，目的门户坐标未知")
        script = "（脚本门户，可能另有条件）" if step["script"] else ""
        lines.append(f"{number}. {origin} {scenes[origin].name}：走 `{step['portal']}` "
                     f"{_sites(tuple(step['portal_at']))} → {target} {scenes[target].name}{arrival}{script}")
    if estimated:
        lines.append("注：其中含反向穿越的估计步骤，需现场确认。")
    return "\n".join(lines)
