"""技能内自包含的世界图资料解析，不导入 beidou_pilot 包，也不读取客户端运行状态。

从本地原版客户端 IMG 读取地图号、名称、门户坐标与目的地图，按地图号归组为区域。
只保留离线资料生成需要的解析、门户边、区域与展示函数；跨图路线由客户端原生
`beidou-pilot world-map route` 提供，本模块不计算路线。

需要共享 IMG 解析库：生成器默认在检出目录的 `headless/build/libbeidou-img.so` 查找，
也可用 BEIDOU_IMG_LIBRARY 显式指定。
"""

from collections import Counter, defaultdict
from ctypes import (
    CDLL,
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_double,
    c_int,
    c_int32,
    c_int64,
    c_size_t,
    c_uint16,
    c_uint32,
    c_void_p,
    create_string_buffer,
    string_at,
)
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import cache
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

# 与客户端 Portal::Type 对应；脚本门户与包含脚本字段的普通门户不能静态保证目的地。
ENTRANCES = {1, 2, 3, 6, 10}
EXTERNAL_TARGET = 999999999
# 一个区域通常有 10 张以上带门户的场景；不足的单元并入同一地图组里够大的单元
REGION_SIZE = 10


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


class _NodeInfo(Structure):
    _fields_ = [
        ("name_string_id", c_uint32),
        ("children", c_uint32),
        ("value_string_id", c_uint32),
        ("source_file_id", c_uint32),
        ("source_order", c_uint32),
        ("bitmap_id", c_uint32),
        ("audio_id", c_uint32),
        ("audio_length", c_uint32),
        ("child_count", c_uint16),
        ("type", c_uint16),
        ("bitmap_width", c_uint16),
        ("bitmap_height", c_uint16),
        ("integer", c_int64),
        ("real", c_double),
        ("vector_x", c_int32),
        ("vector_y", c_int32),
    ]


@cache
def _library() -> CDLL:
    """最小只读 IMG 解码绑定；技能生成器不依赖客户端 Python 包。"""
    checkout = Path(__file__).resolve().parents[4]
    configured = os.environ.get("BEIDOU_IMG_LIBRARY")
    candidates = [Path(configured).expanduser()] if configured else [
        checkout / "headless/build/libbeidou-img.so",
        checkout / "lib/libbeidou-img.so",
    ]
    path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise SystemExit(
            "共享 IMG 解析库不可用；用 BEIDOU_IMG_LIBRARY 指向 libbeidou-img.so。"
            f"已查找：{[str(candidate) for candidate in candidates]}"
        )
    library = CDLL(str(path))
    library.beidou_img_directory_open.argtypes = [c_char_p, c_int, POINTER(c_void_p), c_char_p, c_size_t]
    library.beidou_img_directory_open.restype = c_int
    library.beidou_img_directory_node_count.argtypes = [c_void_p]
    library.beidou_img_directory_node_count.restype = c_size_t
    library.beidou_img_directory_node.argtypes = [c_void_p, c_size_t, POINTER(_NodeInfo)]
    library.beidou_img_directory_node.restype = c_int
    library.beidou_img_directory_string.argtypes = [c_void_p, c_size_t, POINTER(c_size_t)]
    library.beidou_img_directory_string.restype = c_void_p
    return library


class _ImgDirectory:
    """读取一个原版 IMG 目录里的节点树；生成器只在初始化时打开目录。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._library = _library()
        self._handle = c_void_p()
        error = create_string_buffer(4096)
        if not self._library.beidou_img_directory_open(
            os.fsencode(path), 0, byref(self._handle), error, len(error)
        ):
            reason = error.value.decode("utf-8", errors="replace")
            raise SystemExit(f"原版 IMG 目录无法读取：{path}（{reason}）")
        self._node_count = self._library.beidou_img_directory_node_count(self._handle)

    def _string(self, index: int) -> str:
        length = c_size_t()
        pointer = self._library.beidou_img_directory_string(self._handle, index, byref(length))
        return string_at(pointer, length.value).decode("utf-8")

    def _node(self, index: int) -> _NodeInfo:
        if index >= self._node_count:
            raise SystemExit(f"原版 IMG 解析器返回了无效节点索引：{self.path}")
        result = _NodeInfo()
        if not self._library.beidou_img_directory_node(self._handle, index, byref(result)):
            raise SystemExit(f"原版 IMG 解析器无法读取节点：{self.path}")
        return result

    def _element(self, index: int) -> ET.Element:
        node = self._node(index)
        attributes = {"name": self._string(node.name_string_id)}
        if node.type == 1:
            element = ET.Element("long", {**attributes, "value": str(node.integer)})
        elif node.type == 2:
            element = ET.Element("double", {**attributes, "value": repr(node.real)})
        elif node.type == 3:
            element = ET.Element("string", {**attributes, "value": self._string(node.value_string_id)})
        elif node.type == 4:
            element = ET.Element("vector", {**attributes, "x": str(node.vector_x), "y": str(node.vector_y)})
        elif node.type == 5:
            element = ET.Element("canvas", {**attributes, "width": str(node.bitmap_width),
                                            "height": str(node.bitmap_height)})
        elif node.type == 6:
            element = ET.Element("sound", {**attributes, "length": str(node.audio_length)})
        elif node.type == 7:
            element = ET.Element("uol", {**attributes, "path": self._string(node.value_string_id)})
        else:
            element = ET.Element("imgdir", attributes)
        for child in range(node.children, node.children + node.child_count):
            element.append(self._element(child))
        return element

    def read_tree(self, parts: tuple[str, ...]) -> ET.Element | None:
        index = 0
        for part in parts:
            parent = self._node(index)
            index = next(
                (child for child in range(parent.children, parent.children + parent.child_count)
                 if self._string(self._node(child).name_string_id) == part),
                None,
            )
            if index is None:
                return None
        return self._element(index)


def game_data_root(client_root: Path) -> Path:
    """读取资源配置里的 game_data；未配置时用 <client_root>/Data。"""
    configured_file = os.environ.get("MAPLE_RESOURCES_CONFIG")
    config_file = (Path(configured_file).expanduser().resolve() if configured_file
                   else client_root.resolve() / "config/resources.json")
    if not configured_file and not config_file.is_file():
        return client_root.resolve() / "Data"
    try:
        resources = json.loads(config_file.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"资源配置无法读取：{config_file}（{error}）") from error
    value = resources.get("game_data") if isinstance(resources, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"资源配置缺少有效的 game_data：{config_file}")
    path = Path(value).expanduser()
    return (path if path.is_absolute() else config_file.parent / path).resolve()


def world_data(game_data: Path) -> dict[int, Scene]:
    """带门户的地图；名称与街名取自 String/Map.img，门户取自各张地图。"""
    names = _string_names(game_data)
    scenes = {}
    for map_id, (portals, link) in _map_data(game_data).items():
        scene_names = names.get(map_id, {})
        scenes[map_id] = Scene(map_id, scene_names.get("mapName") or f"地图{map_id}", map_id // 10000,
                               scene_names.get("streetName") or None, tuple(portals), link)
    return scenes


def _string_names(game_data: Path) -> dict[int, dict[str, str]]:
    """String/Map.img 里按地图号建立的 mapName、streetName；只取地图号节点。"""
    tree = _ImgDirectory(game_data / "String").read_tree(("Map.img",))
    names: dict[int, dict[str, str]] = {}
    for node in tree.iter() if tree is not None else ():
        key = node.get("name", "")
        if key.isdecimal():
            values = {child.get("name", ""): str(child.get("value"))
                      for child in node if child.get("value") is not None}
            if "mapName" in values or "streetName" in values:
                names[int(key)] = values
    return names


def display_regions(game_data: Path) -> dict[str, set[int]]:
    """按客户端世界地图资源文件提取展示关系；同一地图可出现在多张图中。"""
    root = game_data / ("Map002" if (game_data / "Map002").is_dir() else "Map")
    world = root / "WorldMap"
    paths = sorted(world.glob("WorldMap*.img")) if world.is_dir() else []
    if not paths:
        return {}
    directory = _ImgDirectory(root)
    result = {}
    for path in paths:
        tree = directory.read_tree(("WorldMap", path.name))
        if tree is None:
            continue
        ids = set()
        for node in tree.iter():
            if node.get("name") != "mapNo":
                continue
            for child in node:
                try:
                    value = Decimal(child.get("value", ""))
                    if value.is_finite() and value == value.to_integral_value() and value >= 0:
                        ids.add(int(value))
                except InvalidOperation:
                    continue
        result[path.stem] = ids
    return result


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
    directory = _ImgDirectory(root)
    result = {}
    for folder in sorted((root / "Map").iterdir()):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix != ".img":
                continue
            tree = directory.read_tree(("Map", folder.name, path.name))
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
