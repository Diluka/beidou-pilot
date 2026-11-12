"""狩猎只消费明确来源的静态地形，缺失或坏资源不能变成空地图。"""

import json
from pathlib import Path
import tempfile
import unittest

from beidou_pilot.errors import ClientError
from beidou_pilot.hunt_terrain import load_hunt_terrain
from test.img_fixture import write_img


class HuntTerrainContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "Data"
        (self.root / "config").mkdir()
        (self.root / "config/resources.json").write_text(
            json.dumps({"game_data": str(self.data)})
        )

    def test_reads_configured_img_footholds_and_ropes(self) -> None:
        source = write_img(
            self.data / "Map002/Map/Map0/000050000.img",
            {
                "foothold": {"1": {"0": {"5": {
                    "x1": 90, "x2": 180, "y1": 335, "y2": 335, "prev": 4, "next": 8,
                }}}},
                "ladderRope": {"1": {"x": 262, "y1": -23, "y2": 333}},
            },
        )

        terrain = load_hunt_terrain(self.root, 50000)

        self.assertEqual(
            {"id": 5, "x1": 90, "x2": 180, "y1": 335, "y2": 335, "prev": 4, "next": 8}, terrain["footholds"][0]
        )
        self.assertEqual([{"index": 1, "x": 262, "y1": -23, "y2": 333}], terrain["ropes"])
        self.assertEqual(str(source), terrain["source"])

    def test_xml_does_not_supply_missing_img_geometry(self) -> None:
        source = self.root / "xml/Map.wz/Map/Map0/000050000.img.xml"
        source.parent.mkdir(parents=True)
        source.write_text("""<imgdir name="000050000.img"><imgdir name="info"/>
          <imgdir name="foothold"><imgdir name="1"><imgdir name="0"><imgdir name="5">
          <int name="x1" value="90"/><int name="x2" value="180"/>
          <int name="y1" value="335"/><int name="y2" value="335"/>
          <int name="prev" value="4"/><int name="next" value="8"/>
          </imgdir></imgdir></imgdir></imgdir></imgdir>""")

        with self.assertRaises(ClientError) as missing:
            load_hunt_terrain(self.root, 50000)
        self.assertEqual("hunt_terrain_unavailable", missing.exception.code)
        self.assertTrue(source.is_file())

    def test_missing_or_truncated_resources_are_explicit_failures(self) -> None:
        with self.assertRaises(ClientError) as missing:
            load_hunt_terrain(self.root, 50000)
        self.assertEqual("hunt_terrain_unavailable", missing.exception.code)
        invalid = self.data / "Map002/Map/Map0/000050000.img"
        invalid.parent.mkdir(parents=True)
        invalid.write_bytes(b"PKG4")
        with self.assertRaises(ClientError) as invalid:
            load_hunt_terrain(self.root, 50000)
        self.assertEqual("metadata_unreadable", invalid.exception.code)
