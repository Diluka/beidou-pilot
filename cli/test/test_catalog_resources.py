"""静态资料消费者从配置的 XML/NX 取得事实，并保留缺失项及来源。"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from typing import TypeAlias
import unittest

from beidou_pilot.catalog import Catalog


@dataclass(frozen=True)
class _Vector:
    x: int
    y: int


@dataclass(frozen=True)
class _Canvas:
    width: int
    height: int
    children: dict[str, _NxValue]


_NxValue: TypeAlias = int | str | dict[str, "_NxValue"] | _Vector | _Canvas


def _write_nx(path: Path, tree: dict[str, _NxValue]) -> None:
    """按 PKG4 格式写手列资料，独立于生产读取器。"""
    entries: list[tuple[str, _NxValue]] = [("", tree)]
    records: list[tuple[str, int, int, int, bytes | str]] = []
    for name, value in entries:
        children = value if isinstance(value, dict) else value.children if isinstance(value, _Canvas) else {}
        start, count = (len(entries), len(children)) if children else (0, 0)
        entries.extend(sorted(children.items()))
        if isinstance(value, dict):
            kind, payload = 0, bytes(8)
        elif isinstance(value, int):
            kind, payload = 1, struct.pack("<q", value)
        elif isinstance(value, str):
            kind, payload = 3, value
        elif isinstance(value, _Vector):
            kind, payload = 4, struct.pack("<ii", value.x, value.y)
        else:
            kind, payload = 5, struct.pack("<IHH", 0, value.width, value.height)
        records.append((name, start, count, kind, payload))

    strings = list(dict.fromkeys(
        [name for name, *_ in records] + [value for *_, value in records if isinstance(value, str)]
    ))
    string_ids = {value: index for index, value in enumerate(strings)}
    string_table = 52 + len(records) * 20
    string_data = string_table + len(strings) * 8
    encoded = [value.encode("utf-8") for value in strings]
    bitmap_table = string_data + sum(2 + len(value) for value in encoded)
    blob = bytearray(struct.pack("<IIQIQIQIQ", 0x34474B50, len(records), 52,
                                 len(strings), string_table, 1, bitmap_table, 0, 0))
    for name, start, count, kind, payload in records:
        blob.extend(struct.pack("<IIHH", string_ids[name], start, count, kind))
        blob.extend(struct.pack("<II", string_ids[payload], 0) if isinstance(payload, str) else payload)
    for value in encoded:
        blob.extend(struct.pack("<Q", string_data))
        string_data += 2 + len(value)
    for value in encoded:
        blob.extend(struct.pack("<H", len(value)) + value)
    blob.extend(struct.pack("<QI", bitmap_table + 8, 0))
    path.write_bytes(blob)


class CatalogResourceContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.nx = self.root / "nx"
        self.nx.mkdir()
        (self.root / "config").mkdir()
        (self.root / "config/resources.json").write_text(json.dumps({
            "metadata_root": str(self.root / "xml"), "headless_resources": str(self.nx),
        }))
        _write_nx(self.nx / "String.nx", {
            "Map.img": {"maple": {"50000": {"mapName": "蜗牛树林", "streetName": "彩虹岛"}}},
            "Mob.img": {"100100": {"name": "绿蜗牛"}},
            "Npc.img": {"2003": {"name": "罗宾"}},
            "Consume.img": {"2000000": {"name": "红色药水"}},
            "Eqp.img": {"Eqp": {"Weapon": {"1322005": {"name": "木棍"}}}},
        })
        _write_nx(self.nx / "Map002.nx", {"Map": {"Map0": {"000050000.img": {
            "info": {"returnMap": 1000000},
            "portal": {"0": {"pn": "east", "pt": 2, "tm": 1000000, "tn": "west", "x": 1430, "y": 269}},
            "ladderRope": {"1": {"l": 0, "uf": 1, "x": 262, "y1": -23, "y2": 333}},
            "foothold": {"1": {"0": {"5": {"x1": 90, "x2": 180, "y1": 335, "y2": 335,
                                                     "prev": 4, "next": 8}}}},
            "life": {"0": {"type": "n", "id": "2003", "x": 167, "y": 335},
                     "1": {"type": "m", "id": "100100", "x": 500, "y": -25}},
        }}}})
        _write_nx(self.nx / "Item.nx", {"Consume": {"0200.img": {"02000000": {
            "info": {"price": 50}, "spec": {"hp": 50},
        }}}})
        _write_nx(self.nx / "Character.nx", {"Weapon": {"01322005.img": {
            "info": {"reqLevel": 0, "reqSTR": 0, "attackSpeed": 5, "price": 50},
        }}})
        _write_nx(self.nx / "Mob.nx", {"0100100.img": {"info": {"level": 1, "maxHP": 8, "exp": 3}}})
        _write_nx(self.nx / "Npc.nx", {"0002003.img": {
            "info": {}, "stand": {"0": _Canvas(40, 60, {"origin": _Vector(20, 50)})},
        }})

    def test_consumers_read_nx_names_properties_geometry_and_actual_sources(self) -> None:
        catalog = Catalog(self.root)
        map_data = catalog.map(50000)
        monster = catalog.monster(100100)
        npc = catalog.npc(2003)
        potion = catalog.item(2000000)
        weapon = catalog.item(1322005)

        self.assertEqual(("蜗牛树林", "彩虹岛"), (map_data["name"], map_data["street_name"]))
        self.assertEqual({"index": 0, "name": "east", "x": 1430, "y": 269, "type": 2,
                          "target_map_id": 1000000, "target_name": "west", "script": None}, map_data["portals"][0])
        self.assertEqual({"index": 1, "l": 0, "uf": 1, "x": 262, "y1": -23, "y2": 333}, map_data["ropes"][0])
        self.assertEqual({"id": 5, "x1": 90, "x2": 180, "y1": 335, "y2": 335, "prev": 4, "next": 8},
                         map_data["footholds"][0])
        self.assertEqual(("罗宾", "绿蜗牛"), (map_data["npcs"][0]["name"], map_data["monsters"][0]["name"]))
        self.assertEqual("绿蜗牛", monster["name"])
        self.assertEqual({"level": 1, "maxHP": 8, "exp": 3}, monster["info"])
        self.assertEqual("罗宾", npc["name"])
        self.assertEqual({"left": -20, "top": -50, "right": 20, "bottom": 10}, npc["click_rect"])
        self.assertEqual(("红色药水", {"hp": 50}, 50), (potion["name"], potion["spec"], potion["price"]))
        self.assertEqual(("木棍", {"reqLevel": 0, "reqSTR": 0}), (weapon["name"], weapon["requirements"]))

        for result, files in ((map_data, ("Map002.nx", "String.nx")), (monster, ("Mob.nx", "String.nx")),
                              (npc, ("Npc.nx", "String.nx")), (potion, ("Item.nx", "String.nx")),
                              (weapon, ("Character.nx", "String.nx"))):
            with self.subTest(id=result["id"]):
                paths = {str(self.nx / filename) for filename in files}
                self.assertEqual(paths, set(result["metadata_source"]))
                self.assertEqual({path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths},
                                 {entry["path"]: entry["sha256"] for entry in result["metadata_sources"]})
                self.assertEqual("local-official-nx", result["source_kind"])
                self.assertIsNone(result["resource_version"])

    def test_absent_entries_keep_unknown_facts_and_unavailable_reasons(self) -> None:
        catalog = Catalog(self.root)
        potion = catalog.item(2000001)
        npc = catalog.npc(2004)
        monster = catalog.monster(100101)

        self.assertIsNone(potion["name"])
        self.assertIsNone(potion["price"])
        self.assertEqual({}, potion["spec"])
        self.assertEqual({}, potion["requirements"])
        self.assertTrue(potion["unavailable"])
        self.assertIsNone(npc["name"])
        self.assertIsNone(npc["click_rect"])
        self.assertTrue(npc["unavailable"])
        self.assertIsNone(monster["name"])
        self.assertEqual({}, monster["info"])
        self.assertTrue(monster["unavailable"])

    def test_xml_names_override_nx_while_properties_keep_their_nx_source(self) -> None:
        source = self.root / "xml/String.wz/Mob.img.xml"
        source.parent.mkdir(parents=True)
        source.write_text('<imgdir name="Mob.img"><imgdir name="100100">'
                          '<string name="name" value="XML蜗牛"/></imgdir></imgdir>')

        result = Catalog(self.root).monster(100100)

        self.assertEqual("XML蜗牛", result["name"])
        self.assertEqual(8, result["info"]["maxHP"])
        self.assertEqual({str(source), str(self.nx / "Mob.nx")}, set(result["metadata_source"]))
        self.assertEqual("mixed-local-client-resources", result["source_kind"])
        self.assertIsNone(result["resource_version"])

    def test_map_sources_exclude_unrelated_names_previously_read_by_the_catalog(self) -> None:
        _write_nx(self.nx / "Map002.nx", {"Map": {"Map0": {"000050000.img": {
            "info": {}, "foothold": {"1": {"0": {"5": {
                "x1": 90, "x2": 180, "y1": 335, "y2": 335, "prev": 0, "next": 0,
            }}}},
        }}}})
        unrelated = self.root / "xml/String.wz/Npc.img.xml"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text('<imgdir name="Npc.img"><imgdir name="2003">'
                             '<string name="name" value="XML罗宾"/></imgdir></imgdir>')
        catalog = Catalog(self.root)
        self.assertEqual("XML罗宾", catalog.npc_name(2003))

        result = catalog.map(50000)

        self.assertEqual([], result["npcs"])
        self.assertEqual([], result["monsters"])
        self.assertEqual("local-official-nx", result["source_kind"])
        self.assertEqual({str(self.nx / "Map002.nx"), str(self.nx / "String.nx")},
                         set(result["metadata_source"]))
