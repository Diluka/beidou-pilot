"""本地官方 WZ XML 的静态名称与地形资料；不读取服务端状态。"""

from functools import cache
from pathlib import Path
import xml.etree.ElementTree as ET

from .backend import ClientError, JsonObject, JsonValue
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
        if wz_root is None:
            wz_root = load_resources(client_root).metadata_root
        self.root = wz_root.resolve()

    @cache
    def _xml(self, relative_path: str) -> ET.Element | None:
        path = self.root / relative_path
        if not path.is_file():
            return None
        try:
            return ET.parse(path).getroot()
        except (ET.ParseError, OSError) as error:
            raise ClientError("metadata_unreadable", "本地 WZ XML 无法读取。",
                              {"path": str(path), "reason": str(error)}) from error

    @cache
    def _names(self, filename: str) -> dict[int, JsonObject]:
        root = self._xml("String.wz/" + filename + ".img.xml")
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
        source = self.root / f"Npc.wz/{npc_id:07d}.img.xml"
        while sprite_id not in visited:
            visited.add(sprite_id)
            source = self.root / f"Npc.wz/{sprite_id:07d}.img.xml"
            root = self._xml(str(source.relative_to(self.root)))
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
        return {"id": npc_id, "name": name, "click_rect": click_rect,
                "metadata_source": [str(self.root / "String.wz/Npc.img.xml"), str(source)],
                "runtime_authority": False,
                "unavailable": [] if name else ["本地静态资料没有该 NPC 名称，保留模板 ID。"]}

    def monster(self, monster_id: int) -> JsonObject:
        name = self.monster_name(monster_id)
        root = self._xml(f"Mob.wz/{monster_id:07d}.img.xml")
        unavailable: list[JsonValue] = []
        if name is None:
            unavailable.append("本地静态资料没有该怪物名称，保留模板 ID。")
        if root is None:
            unavailable.append("本地静态资料没有该怪物属性 XML。")
        return {"id": monster_id, "name": name, "info": _properties(root.find("./imgdir[@name='info']")
                if root is not None else None),
                "metadata_source": [str(self.root / "String.wz/Mob.img.xml"),
                                    str(self.root / f"Mob.wz/{monster_id:07d}.img.xml")],
                "unavailable": unavailable}

    @cache
    def map(self, map_id: int) -> JsonObject:
        relative_path = f"Map.wz/Map/Map{map_id // 100000000}/{map_id:09d}.img.xml"
        root = self._xml(relative_path)
        names = self._names("Map").get(map_id, {})
        result: JsonObject = {"id": map_id, "name": names.get("mapName"), "street_name": names.get("streetName"),
            "metadata_source": [str(self.root / relative_path), str(self.root / "String.wz/Map.img.xml")],
            "source_kind": "local-official-wz-xml", "runtime_authority": False,
            "portals": [], "ropes": [], "footholds": [], "npcs": [], "monsters": [], "unavailable": []}
        unavailable: list[JsonValue] = []
        if root is None:
            unavailable.append("本地静态资料没有该地图 XML；不能推断门户或地形。")
        else:
            info = _properties(root.find("./imgdir[@name='info']"))
            result["info"] = info
            if "link" in info:
                unavailable.append("地图包含link引用；当前只返回本图XML，引用地图地形未合并。")
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
        return result

    @cache
    def item(self, item_id: int) -> JsonObject:
        name = self.item_name(item_id)
        source: Path | None = None
        node: ET.Element | None = None
        category = item_id // 1000000
        if category == 1:
            source = next(self.root.joinpath("Character.wz").glob(f"*/{item_id:08d}.img.xml"), None)
            if source is not None:
                node = self._xml(str(source.relative_to(self.root)))
        else:
            folder = {2: "Consume", 3: "Install", 4: "Etc", 5: "Cash"}.get(category)
            if folder is not None:
                source = self.root / f"Item.wz/{folder}/{item_id // 10000:04d}.img.xml"
                root = self._xml(str(source.relative_to(self.root)))
                if root is not None:
                    node = root.find(f"./imgdir[@name='{item_id:08d}']")
        info = _properties(node.find("./imgdir[@name='info']") if node is not None else None)
        requirements = {key: value for key, value in info.items() if key.startswith("req")}
        unavailable: list[JsonValue] = []
        if name is None:
            unavailable.append("本地静态资料没有该物品名称，保留物品 ID。")
        if node is None:
            unavailable.append("本地静态资料没有该物品属性，装备要求和价格未知。")
        return {"id": item_id, "name": name, "requirements": requirements,
            "price": info.get("price"), "price_kind": "wz-base-price-not-current-shop-price", "info": info,
            "spec": _properties(node.find("./imgdir[@name='spec']") if node is not None else None),
            "metadata_source": [str(self.root / "String.wz" / ({1: "Eqp", 2: "Consume", 3: "Ins",
                4: "Etc", 5: "Cash"}.get(category, "Cash") + ".img.xml")), str(source) if source else None],
            "source_kind": "local-official-wz-xml", "runtime_authority": False,
            "unavailable": unavailable}
