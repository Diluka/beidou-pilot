"""狩猎只消费明确来源的静态地形，缺失或坏资源不能变成空地图。"""

import json
from pathlib import Path
import struct
import tempfile
import unittest

from beidou_pilot.errors import ClientError
from beidou_pilot.hunt_terrain import load_hunt_terrain


class HuntTerrainContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "config").mkdir()
        (self.root / "config/resources.json").write_text(
            json.dumps(
                {
                    "metadata_root": str(self.root / "xml"),
                    "headless_resources": str(self.root / "nx"),
                }
            )
        )
        (self.root / "nx").mkdir()

    def test_reads_configured_nx_footholds_and_ropes_without_xml(self) -> None:
        # 直接列出外部文件中的节点关系，避免由待测解析器生成夹具。
        entries = [
            ("", 1, 1, 0, 0),
            ("Map", 2, 1, 0, 0),
            ("Map0", 3, 1, 0, 0),
            ("000050000.img", 4, 2, 0, 0),
            ("foothold", 6, 1, 0, 0),
            ("ladderRope", 7, 1, 0, 0),
            ("1", 8, 1, 0, 0),
            ("1", 9, 3, 0, 0),
            ("0", 12, 1, 0, 0),
            ("x", 0, 0, 1, 262),
            ("y1", 0, 0, 1, -23),
            ("y2", 0, 0, 1, 333),
            ("5", 13, 6, 0, 0),
            ("x1", 0, 0, 1, 90),
            ("x2", 0, 0, 1, 180),
            ("y1", 0, 0, 1, 335),
            ("y2", 0, 0, 1, 335),
            ("prev", 0, 0, 1, 4),
            ("next", 0, 0, 1, 8),
        ]
        names = list(dict.fromkeys(entry[0] for entry in entries))
        strings = [name.encode() for name in names]
        table_offset = 52 + len(entries) * 20
        string_offset = table_offset + len(strings) * 8
        blob = bytearray(
            struct.pack("<IIQIQIQIQ", 0x34474B50, len(entries), 52, len(strings), table_offset, 0, 0, 0, 0)
        )
        for name, start, count, kind, value in entries:
            blob.extend(struct.pack("<IIHHQ", names.index(name), start, count, kind, value & 0xFFFFFFFFFFFFFFFF))
        for value in strings:
            blob.extend(struct.pack("<Q", string_offset))
            string_offset += 2 + len(value)
        for value in strings:
            blob.extend(struct.pack("<H", len(value)) + value)
        source = self.root / "nx/Map.nx"
        source.write_bytes(blob)

        terrain = load_hunt_terrain(self.root, 50000)

        self.assertEqual(
            {"id": 5, "x1": 90, "x2": 180, "y1": 335, "y2": 335, "prev": 4, "next": 8}, terrain["footholds"][0]
        )
        self.assertEqual([{"index": 1, "x": 262, "y1": -23, "y2": 333}], terrain["ropes"])
        self.assertEqual(str(source), terrain["source"])

    def test_xml_geometry_takes_precedence_over_unavailable_nx(self) -> None:
        source = self.root / "xml/Map.wz/Map/Map0/000050000.img.xml"
        source.parent.mkdir(parents=True)
        source.write_text("""<imgdir name="000050000.img"><imgdir name="info"/>
          <imgdir name="foothold"><imgdir name="1"><imgdir name="0"><imgdir name="5">
          <int name="x1" value="90"/><int name="x2" value="180"/>
          <int name="y1" value="335"/><int name="y2" value="335"/>
          <int name="prev" value="4"/><int name="next" value="8"/>
          </imgdir></imgdir></imgdir></imgdir></imgdir>""")

        terrain = load_hunt_terrain(self.root, 50000)

        self.assertEqual(str(source), terrain["source"])
        self.assertEqual(5, terrain["footholds"][0]["id"])
        self.assertEqual([], terrain["ropes"])

    def test_missing_or_truncated_resources_are_explicit_failures(self) -> None:
        with self.assertRaises(ClientError) as missing:
            load_hunt_terrain(self.root, 50000)
        self.assertEqual("hunt_terrain_unavailable", missing.exception.code)
        (self.root / "nx/Map.nx").write_bytes(b"PKG4")
        with self.assertRaises(ClientError) as invalid:
            load_hunt_terrain(self.root, 50000)
        self.assertEqual("metadata_unreadable", invalid.exception.code)
