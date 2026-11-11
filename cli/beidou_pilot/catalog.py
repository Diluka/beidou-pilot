"""本地官方 WZ XML 或同源 NX 的静态资料；不读取服务端状态。"""

from functools import cache
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

from .backend import ClientError, JsonObject, JsonValue
from .nx import read_nx
from .resources import load_resources


def _properties(node: ET.Element | None) -> JsonObject:
    result: JsonObject = {}
    if node is not None:
        for child in node:
            value = child.get("value")
            if value is None:
                continue
            if child.tag in {"int", "short", "long"}:
                result[child.attrib["name"]] = int(value)
            elif child.tag in {"float", "double"}:
                result[child.attrib["name"]] = float(value)
            elif child.tag == "string":
                result[child.attrib["name"]] = value
    return result


class Catalog:
    def __init__(self, client_root: Path, wz_root: Path | None = None) -> None:
        resources = load_resources(client_root)
        if wz_root is None:
            wz_root = resources.metadata_root
        self.root = wz_root.resolve()
        self.nx_root = resources.headless_resources
        self._loaded_sources: dict[str, Path] = {}

    @cache
    def _tree(self, relative_path: str) -> ET.Element | None:
        path = self.root / relative_path
        if not path.is_file():
            package, filename = relative_path.split("/", 1)
            category = package.removesuffix(".wz")
            nx_path = self.nx_root / (category + ".nx")
            if category == "Map" and (self.nx_root / "Map002.nx").is_file():
                nx_path = self.nx_root / "Map002.nx"
            if not nx_path.is_file():
                return None
            self._loaded_sources[relative_path] = nx_path
            parts = tuple(None if part == "*" else part for part in filename.removesuffix(".xml").split("/"))
            return read_nx(nx_path, parts)
        self._loaded_sources[relative_path] = path
        try:
            return ET.parse(path).getroot()
        except (ET.ParseError, OSError) as error:
            raise ClientError("metadata_unreadable", "本地 WZ XML 无法读取。",
                              {"path": str(path), "reason": str(error)}) from error

    @cache
    def _fingerprint(self, path: Path) -> str:
        try:
            with path.open("rb") as stream:
                return hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError as error:
            raise ClientError("metadata_unreadable", "本地静态资料的文件指纹无法读取。",
                              {"path": str(path), "reason": str(error)}) from error

    def _sources(self, *relative_paths: str) -> JsonObject:
        paths = list(dict.fromkeys(self._loaded_sources[name] for name in relative_paths if name in self._loaded_sources))
        kinds = {path.suffix for path in paths}
        return {
            "metadata_source": [str(path) for path in paths],
            "metadata_sources": [{"path": str(path), "sha256": self._fingerprint(path)} for path in paths],
            "source_kind": "local-official-nx" if kinds == {".nx"} else "local-official-wz-xml" if kinds == {".xml"}
                           else "mixed-local-client-resources" if kinds else "unavailable",
            "runtime_authority": False,
            "resource_version": None,
            "resource_manifest": str(self.nx_root / "manifest.json") if ".nx" in kinds
                                 and (self.nx_root / "manifest.json").is_file() else None,
        }

    @cache
    def _names(self, filename: str) -> dict[int, JsonObject]:
        root = self._tree("String.wz/" + filename + ".img.xml")
        names: dict[int, JsonObject] = {}
        if root is not None:
            for node in root.iter("imgdir"):
                name = node.get("name", "")
                if name.isdecimal():
                    properties = _properties(node)
                    if properties:
                        names[int(name)] = properties
        return names

    def map_name(self, map_id: int) -> str | None:
        value = self._names("Map").get(map_id, {}).get("mapName")
        return value if isinstance(value, str) else None

    def npc_name(self, npc_id: int) -> str | None:
        value = self._names("Npc").get(npc_id, {}).get("name")
        return value if isinstance(value, str) else None

    def monster_name(self, monster_id: int) -> str | None:
        value = self._names("Mob").get(monster_id, {}).get("name")
        return value if isinstance(value, str) else None

    def item_name(self, item_id: int) -> str | None:
        filenames = {1: "Eqp", 2: "Consume", 3: "Ins", 4: "Etc", 5: "Cash"}
        filename = filenames.get(item_id // 1000000, "Cash")
        value = self._names(filename).get(item_id, {}).get("name")
        return value if isinstance(value, str) else None

    def npc(self, npc_id: int) -> JsonObject:
        name = self.npc_name(npc_id)
        sprite_id = npc_id
        visited: set[int] = set()
        click_rect: JsonObject | None = None
        sources = ["String.wz/Npc.img.xml"]
        while sprite_id not in visited:
            visited.add(sprite_id)
            relative_path = f"Npc.wz/{sprite_id:07d}.img.xml"
            sources.append(relative_path)
            root = self._tree(relative_path)
            if root is None:
                break
            info = _properties(root.find("./imgdir[@name='info']"))
            keys = ("dcLeft", "dcTop", "dcRight", "dcBottom")
            if all(type(info.get(k)) is int for k in keys):
                click_rect = dict(zip(("left", "top", "right", "bottom"), (info[k] for k in keys)))
                break
            link = info.get("link")
            if link is not None and str(link).isdecimal():
                sprite_id = int(str(link))
                continue
            frame = root.find("./imgdir[@name='stand']/canvas")
            if frame is None:
                frame = root.find("./imgdir[@name='stand1']/canvas")
            origin = frame.find("./vector[@name='origin']") if frame is not None else None
            if frame is not None and origin is not None:
                ox, oy = int(origin.attrib["x"]), int(origin.attrib["y"])
                click_rect = {"left": -ox, "top": -oy,
                              "right": int(frame.attrib["width"]) - ox, "bottom": int(frame.attrib["height"]) - oy}
            break
        unavailable: list[JsonValue] = []
        if name is None:
            unavailable.append("本地静态资料没有该 NPC 名称，保留模板 ID。")
        if click_rect is None:
            unavailable.append("本地静态资料没有该 NPC 的点击范围，保留未知。")
        return {"id": npc_id, "name": name, "click_rect": click_rect,
                **self._sources(*sources), "unavailable": unavailable}

    def monster(self, monster_id: int) -> JsonObject:
        name = self.monster_name(monster_id)
        relative_path = f"Mob.wz/{monster_id:07d}.img.xml"
        root = self._tree(relative_path)
        unavailable: list[JsonValue] = []
        if name is None:
            unavailable.append("本地静态资料没有该怪物名称，保留模板 ID。")
        if root is None:
            unavailable.append("本地静态资料没有该怪物属性。")
        return {"id": monster_id, "name": name, "info": _properties(root.find("./imgdir[@name='info']")
                if root is not None else None),
                **self._sources("String.wz/Mob.img.xml", relative_path),
                "unavailable": unavailable}

    @cache
    def map(self, map_id: int) -> JsonObject:
        relative_path = f"Map.wz/Map/Map{map_id // 100000000}/{map_id:09d}.img.xml"
        root = self._tree(relative_path)
        names = self._names("Map").get(map_id, {})
        result: JsonObject = {"id": map_id, "name": names.get("mapName"), "street_name": names.get("streetName"),
            "info": {},
            "portals": [], "ropes": [], "footholds": [], "npcs": [], "monsters": [], "unavailable": []}
        unavailable: list[JsonValue] = []
        if root is None:
            unavailable.append("本地静态资料没有该地图；不能推断门户或地形。")
        else:
            info = _properties(root.find("./imgdir[@name='info']"))
            result["info"] = info
            if "link" in info:
                unavailable.append("地图包含link引用；当前只返回本图资料，引用地图地形未合并。")
            portals: list[JsonValue] = []
            for node in root.findall("./imgdir[@name='portal']/imgdir"):
                fields = _properties(node)
                portals.append({"index": int(node.attrib["name"]), "name": fields.get("pn"),
                    "x": fields.get("x"), "y": fields.get("y"), "type": fields.get("pt"),
                    "target_map_id": fields.get("tm"), "target_name": fields.get("tn"),
                    "script": fields.get("script")})
            result["portals"] = portals
            result["ropes"] = [{"index": int(node.attrib["name"]), **_properties(node)}
                               for node in root.findall("./imgdir[@name='ladderRope']/imgdir")]
            result["footholds"] = [{"id": int(node.attrib["name"]), **_properties(node)}
                for node in root.findall("./imgdir[@name='foothold']/imgdir/imgdir/imgdir")]
            npcs: list[JsonValue] = []
            monsters: list[JsonValue] = []
            for node in root.findall("./imgdir[@name='life']/imgdir"):
                fields = _properties(node)
                template_id = int(str(fields["id"]))
                if fields.get("type") == "n":
                    npcs.append({**fields, "id": template_id, "name": self.npc_name(template_id)})
                elif fields.get("type") == "m":
                    monsters.append({**fields, "id": template_id, "name": self.monster_name(template_id)})
            result["npcs"] = npcs
            result["monsters"] = monsters
        if not names:
            unavailable.append("本地静态资料没有该地图名称，保留地图 ID。")
        result["unavailable"] = unavailable
        sources = [relative_path, "String.wz/Map.img.xml"]
        if result["npcs"]:
            sources.append("String.wz/Npc.img.xml")
        if result["monsters"]:
            sources.append("String.wz/Mob.img.xml")
        return {**result, "geometry_source": str(self._loaded_sources[relative_path])
                if relative_path in self._loaded_sources else None,
                **self._sources(*sources)}

    @cache
    def item(self, item_id: int) -> JsonObject:
        name = self.item_name(item_id)
        relative_path: str | None = None
        node: ET.Element | None = None
        category = item_id // 1000000
        if category == 1:
            source = next(self.root.joinpath("Character.wz").glob(f"*/{item_id:08d}.img.xml"), None)
            relative_path = (str(source.relative_to(self.root)) if source is not None
                             else f"Character.wz/*/{item_id:08d}.img.xml")
            node = self._tree(relative_path)
        else:
            folder = {2: "Consume", 3: "Install", 4: "Etc", 5: "Cash"}.get(category)
            if folder is not None:
                relative_path = f"Item.wz/{folder}/{item_id // 10000:04d}.img.xml"
                root = self._tree(relative_path)
                if root is not None:
                    node = root.find(f"./imgdir[@name='{item_id:08d}']")
        info = _properties(node.find("./imgdir[@name='info']") if node is not None else None)
        requirements = {key: value for key, value in info.items() if key.startswith("req")}
        unavailable: list[JsonValue] = []
        if name is None:
            unavailable.append("本地静态资料没有该物品名称，保留物品 ID。")
        if node is None:
            unavailable.append("本地静态资料没有该物品属性，装备要求和价格未知。")
        sources = ["String.wz/" + {1: "Eqp", 2: "Consume", 3: "Ins", 4: "Etc", 5: "Cash"}.get(category, "Cash")
                   + ".img.xml"]
        if relative_path is not None:
            sources.append(relative_path)
        return {"id": item_id, "name": name, "requirements": requirements,
            "price": info.get("price"), "price_kind": "wz-base-price-not-current-shop-price", "info": info,
            "spec": _properties(node.find("./imgdir[@name='spec']") if node is not None else None),
            **self._sources(*sources),
            "unavailable": unavailable}
