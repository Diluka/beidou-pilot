"""技能内世界图资料解析的离线合同：解析、门户边、区域归组与自包含边界。"""

import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from test.img_fixture import write_img

TOOLS = Path(__file__).resolve().parents[2] / ".agents/skills/beidou-game-guide/tools"


def load_tool(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


world_map_data = load_tool("world_map_data")


class SkillLocalBoundary(unittest.TestCase):
    def test_skill_tools_do_not_import_client_package(self) -> None:
        for path in TOOLS.glob("*.py"):
            imported = set()
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    imported.add(node.module)
            self.assertFalse({name for name in imported if name.split(".")[0] == "beidou_pilot"}, path.name)

    def test_data_module_has_no_route_computation(self) -> None:
        self.assertFalse({"route", "route_text", "paid_route", "transport_edges"} & set(dir(world_map_data)))

    def test_generator_points_route_queries_at_client_native_command(self) -> None:
        generator = load_tool("world_map")

        self.assertIn("beidou-pilot world-map route", generator.HEADER)
        self.assertNotIn("world_route.py", generator.HEADER)
        self.assertNotIn("线路示例", generator.HEADER)

    def test_generator_does_not_overwrite_when_display_data_missing(self) -> None:
        generator = load_tool("world_map")
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory)
            (skill / "references").mkdir()
            output = skill / "references/world-map.md"
            output.write_text("保留原有攻略")
            with patch.object(generator, "SKILL", skill), \
                 patch.object(generator, "game_data_root", return_value=Path("/unused")), \
                 patch.object(generator, "world_data", return_value={1: object()}), \
                 patch.object(generator, "display_regions", return_value={}):
                with self.assertRaisesRegex(SystemExit, "未覆盖"):
                    generator.main()
            self.assertEqual(output.read_text(), "保留原有攻略")


class WorldMapData(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "Data"
        self.names = ""
        self._write_resources()
        self.scenes = world_map_data.world_data(self.data)

    def test_game_data_root_uses_config_or_default(self) -> None:
        with patch.dict(os.environ, {"MAPLE_RESOURCES_CONFIG": ""}):
            self.assertEqual(self.data, world_map_data.game_data_root(self.root))
            config = self.root / "config/resources.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"game_data": "Data"}))
            self.assertEqual(self.root / "config/Data", world_map_data.game_data_root(self.root))
        config.write_text(json.dumps({"game_data": str(self.data)}))
        with patch.dict(os.environ, {"MAPLE_RESOURCES_CONFIG": str(config)}):
            self.assertEqual(self.data, world_map_data.game_data_root(Path("/unrelated")))

    def test_display_regions(self) -> None:
        self.assertEqual(world_map_data.display_regions(self.data), {})
        write_img(self.data / "Map/WorldMap/WorldMapA.img",
                  {"MapList": {"0": {"mapNo": {"0": 100000000, "1": "5363.0", "2": "bad"}}}})
        write_img(self.data / "Map/WorldMap/WorldMapB.img", {"MapList": {"0": {"mapNo": {"0": "100000000"}}}})
        self.assertEqual(world_map_data.display_regions(self.data),
                         {"WorldMapA": {100000000, 5363}, "WorldMapB": {100000000}})

    def _map(self, map_id: int, name: str, street: str, portals: dict[str, dict[str, object]]) -> None:
        write_img(
            self.data / f"Map/Map/Map{map_id // 100000000}/{map_id:09d}.img",
            {"info": {"returnMap": map_id}, "portal": portals},
        )
        names = self.data / "String/Map.img"
        existing = json.loads(self.names) if self.names else {}
        existing[str(map_id)] = {"mapName": name, "streetName": street}
        write_img(names, existing)
        self.names = json.dumps(existing)

    def _write_resources(self) -> None:
        self.names = ""
        self._map(100000000, "射手村", "金银岛", {
            "0": {"pn": "sp", "pt": 0, "tm": 999999999, "tn": "", "x": 10, "y": 20},
            "1": {"pn": "east00", "pt": 2, "tm": 100000100, "tn": "west00", "x": 1400, "y": 300},
            "2": {"pn": "shop00", "pt": 2, "tm": 100000200, "tn": "out00", "x": -300, "y": 80},
            "3": {"pn": "in00", "pt": 2, "tm": 100000100, "tn": "back00", "x": 900, "y": 80},
            "4": {"pn": "tp00", "pt": 2, "tm": 999999999, "tn": "tp01", "x": 5, "y": 6},
        })
        self._map(100000100, "射手村东部平原", "金银岛", {
            "0": {"pn": "west00", "pt": 1, "tm": 100000000, "tn": "east00", "x": -500, "y": 310},
            "1": {"pn": "east00", "pt": 2, "tm": 100000200, "tn": "west00", "x": 700, "y": 310},
            "2": {"pn": "back00", "pt": 0, "tm": 999999999, "tn": "", "x": 40, "y": 50},
        })
        self._map(100000200, "蘑菇谷", "蘑菇城", {
            "0": {"pn": "out00", "pt": 2, "tm": 100000000, "tn": "shop00", "x": 0, "y": 0},
            "1": {"pn": "west00", "pt": 2, "tm": 100000100, "tn": "east00", "x": 120, "y": 40},
        })
        self._map(200000000, "天空之城", "神秘岛", {
            "0": {"pn": "east00", "pt": 2, "tm": 100000000, "tn": "nowhere", "x": 100, "y": 100},
        })
        for index in range(8):
            self._map(300000000 + index * 100, f"射击场{index}", "射击场", {
                "0": {"pn": "out00", "pt": 2, "tm": 300000000, "tn": "in00", "x": index, "y": 0},
            })

    def test_edges_carry_entry_and_receiver_coordinates(self) -> None:
        edges = {edge.name: edge for edge in world_map_data.edges_of(self.scenes[100000000], self.scenes)}

        self.assertEqual(((1400, 300),), edges["east00"].sources)
        self.assertEqual(((int(-500), 310),), edges["east00"].receivers)
        self.assertEqual("west00", edges["east00"].target_name)
        self.assertEqual(100000200, edges["shop00"].target)
        self.assertEqual(((int(0), int(0)),), edges["shop00"].receivers)
        self.assertEqual("out00", edges["shop00"].target_name)
        self.assertEqual(((int(900), int(80)),), edges["in00"].sources)
        self.assertNotIn("tp00", edges)
        self.assertNotIn("sp", edges)

    def test_receiver_without_matching_portal_remains_unknown(self) -> None:
        edge = world_map_data.edges_of(self.scenes[200000000], self.scenes)[0]

        self.assertEqual((), edge.receivers)
        self.assertEqual("nowhere", edge.target_name)

    def test_regions_group_small_cells_into_large_neighbour(self) -> None:
        regions = {region.entity: region for region in world_map_data.regions_of(self.scenes)}

        self.assertIn(10000, regions)
        self.assertEqual(20000, regions[20000].entity)
        self.assertNotIn(20001, regions)
        self.assertIn(30000, regions)
        self.assertEqual("射手村", regions[10000].name)
        self.assertEqual(8, len(regions[30000].map_ids))

    def test_same_name_different_targets_preserve_receivers(self) -> None:
        base = self.scenes[100000000]
        first = {"index": 1, "name": "same", "type": 2, "target": 100000100,
                 "target_name": "west00", "script": None, "x": 1, "y": 2}
        second = {**first, "target_name": "back00", "x": 3}
        scene = world_map_data.Scene(base.map_id, base.name, base.entity, base.street, (first, second))
        edges = world_map_data.edges_of(scene, self.scenes)
        self.assertEqual([(((1, 2),), ((-500, 310),)), (((3, 2),), ((40, 50),))],
                         [(edge.sources, edge.receivers) for edge in edges])

    def test_touch_portal_is_a_directed_candidate(self) -> None:
        base = self.scenes[100000000]
        touch = {"index": 1, "name": "touch", "type": 3, "target": 200000000,
                 "target_name": "east00", "script": None, "x": 1, "y": 2}
        scene = world_map_data.Scene(base.map_id, base.name, base.entity, base.street, (touch,))
        edges = world_map_data.edges_of(scene, self.scenes)
        self.assertEqual([("touch", 200000000)], [(edge.name, edge.target) for edge in edges])

    def test_map_without_portals_remains_a_node_with_link(self) -> None:
        write_img(self.data / "Map/Map/Map1/100000300.img", {"info": {"link": "100000200"}})
        scene = world_map_data.world_data(self.data)[100000300]
        self.assertEqual(100000200, scene.link)
        self.assertEqual((), scene.portals)

    def test_map002_is_used_when_present(self) -> None:
        (self.data / "Map").rename(self.data / "Map002")
        self.assertIn(100000000, world_map_data.world_data(self.data))


if __name__ == "__main__":
    unittest.main()
