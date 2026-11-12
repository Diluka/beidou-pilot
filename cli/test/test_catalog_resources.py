"""Static catalogue contracts against original-format IMG resources."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from beidou_pilot.catalog import Catalog
from beidou_pilot.img_resources import ImgDirectory
from test.img_fixture import Canvas, Uol, Vector, write_img


class CatalogResourceContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "Data"
        self._write_resources()
        (self.root / "config").mkdir()
        (self.root / "config/resources.json").write_text(json.dumps({"game_data": str(self.data)}))

    def _write_resources(self) -> None:
        write_img(
            self.data / "String/Map.img",
            {"50000": {"mapName": "蜗牛树林", "streetName": "彩虹岛"}},
        )
        write_img(self.data / "String/Mob.img", {"100100": {"name": "绿蜗牛"}})
        write_img(self.data / "String/Npc.img", {"2003": {"name": "罗宾"}})
        write_img(self.data / "String/Consume.img", {"2000000": {"name": "红色药水"}})
        write_img(self.data / "String/Eqp.img", {"1322005": {"name": "木棍"}})
        write_img(
            self.data / "Map002/Map/Map0/000050000.img",
            {
                "info": {"returnMap": 1000000},
                "portal": {"0": {"pn": "east", "pt": 2, "tm": 1000000, "tn": "west", "x": 1430, "y": 269}},
                "ladderRope": {"1": {"l": 0, "uf": 1, "x": 262, "y1": -23, "y2": 333}},
                "foothold": {"1": {"0": {"5": {"x1": 90, "x2": 180, "y1": 335, "y2": 335, "prev": 4, "next": 8}}}},
                "life": {
                    "0": {"type": "n", "id": "2003", "x": 167, "y": 335},
                    "1": {"type": "m", "id": "100100", "x": 500, "y": -25},
                },
            },
        )
        write_img(
            self.data / "Item/Consume/0200.img",
            {"02000000": {"info": {"zMarker": 1, "price": 50}, "spec": {"hp": 50}}},
        )
        write_img(
            self.data / "Character/Weapon/01322005.img",
            {"info": {"reqLevel": 0, "reqSTR": 0, "attackSpeed": 5, "price": 50}},
        )
        write_img(self.data / "Mob/0100100.img", {"info": {"level": 1, "maxHP": 8, "exp": 3}})
        write_img(
            self.data / "Npc/0002003.img",
            {"info": {}, "stand": {"0": Uol("../../0002004.img/stand/0")}},
        )
        write_img(
            self.data / "Npc/0002004.img",
            {"stand": {"0": Canvas(40, 60, {"origin": Vector(20, 50)})}},
        )
        write_img(
            self.data / "Npc/0002005.img",
            {
                "info": {},
                "stand": {"0": Uol("../../missing.img/0002004.img/stand/0")},
                "walk": {"0": Uol("../../../0002004.img/stand/0")},
            },
        )

    def test_consumers_read_img_names_properties_geometry_and_real_sources(self) -> None:
        catalog = Catalog(self.root)
        map_data = catalog.map(50000)
        monster = catalog.monster(100100)
        npc = catalog.npc(2003)
        potion = catalog.item(2000000)
        weapon = catalog.item(1322005)

        self.assertEqual(("蜗牛树林", "彩虹岛"), (map_data["name"], map_data["street_name"]))
        self.assertEqual(
            {
                "index": 0,
                "name": "east",
                "x": 1430,
                "y": 269,
                "type": 2,
                "target_map_id": 1000000,
                "target_name": "west",
                "script": None,
            },
            map_data["portals"][0],
        )
        self.assertEqual({"index": 1, "l": 0, "uf": 1, "x": 262, "y1": -23, "y2": 333}, map_data["ropes"][0])
        self.assertEqual(
            {"id": 5, "x1": 90, "x2": 180, "y1": 335, "y2": 335, "prev": 4, "next": 8},
            map_data["footholds"][0],
        )
        self.assertEqual(("罗宾", "绿蜗牛"), (map_data["npcs"][0]["name"], map_data["monsters"][0]["name"]))
        self.assertEqual("绿蜗牛", monster["name"])
        self.assertEqual({"level": 1, "maxHP": 8, "exp": 3}, monster["info"])
        self.assertEqual("罗宾", npc["name"])
        self.assertEqual({"left": -20, "top": -50, "right": 20, "bottom": 10}, npc["click_rect"])
        self.assertEqual(("红色药水", {"hp": 50}, 50), (potion["name"], potion["spec"], potion["price"]))
        self.assertEqual(("木棍", {"reqLevel": 0, "reqSTR": 0}), (weapon["name"], weapon["requirements"]))

        item_tree, _ = ImgDirectory(self.data / "Item").read_tree(("Consume", "0200.img"))
        info = item_tree.find("./imgdir[@name='02000000']/imgdir[@name='info']")
        price = info.find("./long[@name='price']")
        self.assertEqual("1", price.attrib["sourceOrder"])
        self.assertEqual(["price", "zMarker"], [child.attrib["name"] for child in info])

        expected = {
            "map": {
                self.data / "Map002/Map/Map0/000050000.img",
                self.data / "String/Map.img",
                self.data / "String/Npc.img",
                self.data / "String/Mob.img",
            },
            "monster": {self.data / "Mob/0100100.img", self.data / "String/Mob.img"},
            "npc": {self.data / "Npc/0002003.img", self.data / "Npc/0002004.img", self.data / "String/Npc.img"},
            "potion": {self.data / "Item/Consume/0200.img", self.data / "String/Consume.img"},
            "weapon": {self.data / "Character/Weapon/01322005.img", self.data / "String/Eqp.img"},
        }
        for key, result in (
            ("map", map_data),
            ("monster", monster),
            ("npc", npc),
            ("potion", potion),
            ("weapon", weapon),
        ):
            with self.subTest(id=result["id"]):
                paths = {str(path) for path in expected[key]}
                self.assertEqual(paths, set(result["metadata_source"]))
                self.assertEqual(
                    {path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths},
                    {entry["path"]: entry["sha256"] for entry in result["metadata_sources"]},
                )
                self.assertEqual("local-original-img", result["source_kind"])
                self.assertIsNone(result["resource_version"])
                self.assertIsNone(result["resource_manifest"])
        self.assertEqual(str(self.data / "Map002/Map/Map0/000050000.img"), map_data["geometry_source"])

    def test_absent_entries_and_unresolved_links_remain_unknown(self) -> None:
        catalog = Catalog(self.root)
        potion = catalog.item(2000001)
        npc = catalog.npc(2005)
        monster = catalog.monster(100101)

        self.assertIsNone(potion["name"])
        self.assertIsNone(potion["price"])
        self.assertEqual({}, potion["spec"])
        self.assertEqual({}, potion["requirements"])
        self.assertTrue(potion["unavailable"])
        self.assertIsNone(npc["name"])
        self.assertIsNone(npc["click_rect"])
        self.assertTrue(npc["unavailable"])
        self.assertNotIn(str(self.data / "Npc/missing.img"), npc["metadata_source"])
        unresolved, _ = ImgDirectory(self.data / "Npc").read_tree(("0002005.img",))
        self.assertEqual(
            "../../missing.img/0002004.img/stand/0", unresolved.find("./imgdir[@name='stand']/uol").attrib["path"]
        )
        self.assertEqual("../../../0002004.img/stand/0", unresolved.find("./imgdir[@name='walk']/uol").attrib["path"])
        self.assertIsNone(monster["name"])
        self.assertEqual({}, monster["info"])
        self.assertTrue(monster["unavailable"])

    def test_unresolved_img_references_do_not_supply_placeholder_geometry(self) -> None:
        write_img(
            self.data / "String/Npc.img",
            {
                "2003": {"name": "罗宾"},
                "2006": {"name": "缺失引用"},
                "2007": {"name": "未解析引用链"},
                "2008": {"name": "缺失地图引用"},
                "2009": {"name": "有效外链"},
                "2010": {"name": "缺失来源"},
                "2011": {"name": "有效来源"},
                "2012": {"name": "未解析来源链"},
            },
        )
        write_img(
            self.data / "Npc/0002006.img",
            {"stand": {"0": Canvas(10, 20, {"origin": Vector(1, 2), "_outlink": "missing.img/b.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002007.img",
            {"stand": {"0": Canvas(12, 24, {"origin": Vector(2, 4), "_outlink": "0002006.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002008.img",
            {"stand": {"0": Canvas(14, 28, {"origin": Vector(3, 6), "_outlink": "Map/Map0/000050000.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002009.img",
            {"stand": {"0": Canvas(1, 1, {"origin": Vector(20, 50), "_outlink": "0002004.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002010.img",
            {"stand": {"0": Canvas(10, 20, {"origin": Vector(1, 2), "source": "missing.img/b.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002011.img",
            {"stand": {"0": Canvas(1, 1, {"origin": Vector(20, 50), "source": "0002004.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002012.img",
            {"stand": {"0": Canvas(12, 24, {"origin": Vector(2, 4), "source": "0002010.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/b.img",
            {"stand": {"0": Canvas(91, 92, {"origin": Vector(20, 50)})}},
        )
        catalog = Catalog(self.root)
        for npc_id in (2006, 2007, 2008, 2010, 2012):
            with self.subTest(npc_id=npc_id):
                npc = catalog.npc(npc_id)
                self.assertIsNone(npc["click_rect"])
                self.assertNotIn(str(self.data / "Npc/b.img"), npc["metadata_source"])

        linked = catalog.npc(2009)
        sourced = catalog.npc(2011)
        self.assertEqual({"left": -20, "top": -50, "right": 20, "bottom": 10}, linked["click_rect"])
        self.assertEqual(linked["click_rect"], sourced["click_rect"])
        self.assertIn(str(self.data / "Npc/0002004.img"), linked["metadata_source"])
        self.assertIn(str(self.data / "Npc/0002004.img"), sourced["metadata_source"])

    def test_mixed_reference_chains_wait_for_resolved_geometry(self) -> None:
        write_img(
            self.data / "Npc/0002013.img",
            {"stand": {"0": Canvas(1, 1, {"source": "0002014.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002014.img",
            {"stand": {"0": Canvas(3, 4, {"_outlink": "missing.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002015.img",
            {"stand": {"0": Canvas(1, 1, {"source": "0002016.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002016.img",
            {"stand": {"0": Canvas(3, 4, {"_outlink": "0002004.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002017.img",
            {"stand": {"0": Uol("../../0002014.img/stand/0")}},
        )
        write_img(
            self.data / "Npc/0002018.img",
            {"stand": {"0": Canvas(1, 1, {"_outlink": "0002019.img/stand/0"})}},
        )
        write_img(
            self.data / "Npc/0002019.img",
            {"stand": {"0": Canvas(5, 6, {"_inlink": "missing/0"})}},
        )

        directory = ImgDirectory(self.data / "Npc")
        for npc_id in (2013, 2017, 2018):
            with self.subTest(npc_id=npc_id):
                tree, _ = directory.read_tree((f"{npc_id:07d}.img",))
                self.assertIsNone(tree.find("./imgdir[@name='stand']/canvas[@name='0']"))
        tree, sources = directory.read_tree(("0002015.img",))
        canvas = tree.find("./imgdir[@name='stand']/canvas[@name='0']")
        self.assertEqual(("40", "60"), (canvas.attrib["width"], canvas.attrib["height"]))
        self.assertEqual({"0002015.img", "0002004.img"}, {path.name for path in sources})

    def test_legacy_xml_and_nx_are_not_catalog_sources(self) -> None:
        xml = self.root / "xml/String.wz/Mob.img.xml"
        xml.parent.mkdir(parents=True)
        xml.write_text(
            '<imgdir name="Mob.img"><imgdir name="100100"><string name="name" value="XML蜗牛"/></imgdir></imgdir>'
        )
        (self.root / "nx").mkdir()
        (self.root / "nx/Mob.nx").write_bytes(b"PKG4")

        result = Catalog(self.root).monster(100100)

        self.assertEqual("绿蜗牛", result["name"])
        self.assertEqual(8, result["info"]["maxHP"])
        self.assertEqual(
            {str(self.data / "String/Mob.img"), str(self.data / "Mob/0100100.img")}, set(result["metadata_source"])
        )
        self.assertEqual("local-original-img", result["source_kind"])
        self.assertIsNone(result["resource_version"])

    def test_map_sources_exclude_unrelated_static_names(self) -> None:
        write_img(
            self.data / "Map002/Map/Map0/000050000.img",
            {"info": {}, "foothold": {"1": {"0": {"5": {"x1": 90, "x2": 180, "y1": 335, "y2": 335}}}}},
        )
        result = Catalog(self.root).map(50000)

        self.assertEqual([], result["npcs"])
        self.assertEqual([], result["monsters"])
        self.assertEqual("local-original-img", result["source_kind"])
        self.assertEqual(
            {str(self.data / "Map002/Map/Map0/000050000.img"), str(self.data / "String/Map.img")},
            set(result["metadata_source"]),
        )


if __name__ == "__main__":
    unittest.main()
