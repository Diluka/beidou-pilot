"""世界地图 graph：区域归组、门户边与线路查找的离线合同。"""

import json
from pathlib import Path
import tempfile
import unittest

from beidou_pilot.world_map import edges_of, regions_of, route_text, world_data
from test.img_fixture import write_img


class WorldMapGraph(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "Data"
        self._write_resources()
        (self.root / "config").mkdir()
        (self.root / "config/resources.json").write_text(json.dumps({"game_data": str(self.data)}))
        self.scenes = world_data(self.root)

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
        edges = {edge.name: edge for edge in edges_of(self.scenes[100000000], self.scenes)}

        self.assertEqual(((1400, 300),), edges["east00"].sources)
        self.assertEqual(((int(-500), 310),), edges["east00"].receivers)
        self.assertEqual("west00", edges["east00"].target_name)
        self.assertEqual(100000200, edges["shop00"].target)
        self.assertEqual(((int(0), int(0)),), edges["shop00"].receivers)
        self.assertEqual("out00", edges["shop00"].target_name)
        self.assertEqual(((int(900), int(80)),), edges["in00"].sources)
        self.assertNotIn("tp00", edges)
        self.assertNotIn("sp", edges)

    def test_receiver_without_matching_portal_uses_zero_portal(self) -> None:
        edge = edges_of(self.scenes[200000000], self.scenes)[0]

        self.assertEqual(((int(10), int(20)),), edge.receivers)
        self.assertEqual("sp", edge.target_name)

    def test_regions_group_small_cells_into_large_neighbour(self) -> None:
        regions = {region.entity: region for region in regions_of(self.scenes)}

        self.assertIn(10000, regions)
        self.assertEqual(20000, regions[20000].entity)
        self.assertNotIn(20001, regions)
        self.assertIn(30000, regions)
        self.assertEqual("射手村", regions[10000].name)
        self.assertEqual(8, len(regions[30000].map_ids))

    def test_route_prefers_fewer_scene_changes(self) -> None:
        report = route_text(self.scenes, 100000000, 100000200)

        self.assertEqual("100000000 射手村 → 100000200 蘑菇谷，换 1 次场景：\n"
                         "1. 100000000 射手村：走 `shop00` -300,80 → 100000200 蘑菇谷，落点 0,0", report)

    def test_route_reports_each_portals_coordinates(self) -> None:
        report = route_text(self.scenes, 100000100, 100000200)

        self.assertIn("走 `east00` 700,310 → 100000200 蘑菇谷，落点 120,40", report)

    def test_route_explains_ports_and_scripts_outside_graph(self) -> None:
        report = route_text(self.scenes, 100000000, 200000000)

        self.assertIn("没有只用门户的线路", report)

    def test_route_handles_same_map_and_unknown_map(self) -> None:
        self.assertIn("无需换场景", route_text(self.scenes, 100000000, 100000000))
        self.assertIn("不在世界地图 graph 里", route_text(self.scenes, 100000000, 123456789))


if __name__ == "__main__":
    unittest.main()
