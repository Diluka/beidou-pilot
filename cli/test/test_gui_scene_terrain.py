"""The real GUI IMG provider runs against local original-format fixtures, not a game substitute."""

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from .img_fixture import write_img


class GuiSceneTerrainContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = TemporaryDirectory(prefix="gui-scene-terrain-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        cls.executable = cls.directory / "scene-terrain"
        root = Path(__file__).resolve().parents[2]
        subprocess.run(
            [
                "g++",
                "-std=c++17",
                "-O2",
                "-I" + str(root / "shared/lua-runtime"),
                "-I" + str(root / "beidou-ijl15/ezorsia"),
                str(root / "cli/test/gui_scene_terrain_contract.cpp"),
                str(root / "beidou-ijl15/ezorsia/NativeSceneTerrain.cpp"),
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(root / "headless/src/ImgResources.cpp"),
                str(root / "headless/src/ImgKeys.cpp"),
                "-o",
                str(cls.executable),
            ],
            check=True,
            cwd=cls.directory,
            timeout=90,
        )

    def setUp(self) -> None:
        self.temporary_data = TemporaryDirectory(dir=self.directory)
        self.addCleanup(self.temporary_data.cleanup)
        self.data = Path(self.temporary_data.name)

    def map_file(self, map_id=102000000, directory="Map002", **extra):
        return write_img(
            self.data / directory / "Map" / f"Map{map_id // 100000000}" / f"{map_id:09d}.img",
            {
                "foothold": {"0": {"0": {"17": {"x1": -125, "x2": 490, "y1": 85, "y2": 90, "prev": 0, "next": 18}}}},
                "ladderRope": {"3": {"x": -24, "y1": 12, "y2": 85, "l": 1}},
                **extra,
            },
        )

    def observe(self, map_id=102000000, *, ready=True, data_root=None):
        result = subprocess.run(
            [
                str(self.executable),
                str(self.data) if data_root is None else data_root,
                str(map_id),
                "ready" if ready else "loading",
            ],
            check=True,
            text=True,
            capture_output=True,
            cwd=self.directory,
            timeout=10,
        )
        return json.loads(result.stdout)

    def test_uses_configured_catalog_and_only_decodes_current_image(self):
        selected = self.map_file()
        selected.with_name("102000001.img").write_bytes(b"PKG4")
        self.map_file(directory="Map", foothold={})
        result = self.observe()
        self.assertEqual("ok", result["status"], result)
        self.assertEqual(str(selected), result["data"]["source"])
        self.assertEqual(102000000, result["data"]["map_id"])
        self.assertEqual(
            {"id": 17, "x1": -125, "x2": 490, "y1": 85, "y2": 90, "prev": 0, "next": 18}, result["data"]["footholds"][0]
        )
        self.assertEqual({"index": 3, "x": -24, "y1": 12, "y2": 85, "l": 1}, result["data"]["ropes"][0])

    def test_map_directory_is_used_only_when_map002_directory_is_absent(self):
        selected = self.map_file(directory="Map")
        result = self.observe()
        self.assertEqual("ok", result["status"], result)
        self.assertEqual(str(selected), result["data"]["source"])
        (self.data / "Map002").mkdir()
        missing = self.observe()
        self.assertEqual("unavailable", missing["status"], missing)
        self.assertNotIn("footholds", missing["data"])
        self.assertNotIn("ropes", missing["data"])

    def test_missing_or_corrupt_current_image_does_not_use_another_map(self):
        selected = self.map_file()
        missing = self.observe(102000001)
        self.assertEqual("unavailable", missing["status"])
        selected.write_bytes(b"PKG4")
        broken = self.observe()
        self.assertEqual("unavailable", broken["status"])
        for result in (missing, broken):
            self.assertNotIn("footholds", result["data"])
            self.assertNotIn("ropes", result["data"])

    def test_no_root_or_loading_does_not_guess_working_directory(self):
        self.map_file()
        for arguments in ({"data_root": ""}, {"ready": False}):
            with self.subTest(arguments=arguments):
                result = self.observe(**arguments)
                self.assertEqual("unavailable", result["status"])
                self.assertNotIn("footholds", result["data"])
                self.assertNotIn("ropes", result["data"])

    def test_link_only_is_explicit_but_own_complete_geometry_stays_supported(self):
        self.map_file(info={"link": "999999999"})
        self.assertEqual("ok", self.observe()["status"])
        self.map_file(info={"link": "999999999"}, foothold={})
        result = self.observe()
        self.assertEqual("unsupported", result["status"])
        self.assertEqual("hunt_terrain_unsupported", result["error"])
        self.assertNotIn("footholds", result["data"])

    def test_zero_map_id_is_known_not_missing_identity(self):
        self.map_file(map_id=0)
        result = self.observe(0)
        self.assertEqual("ok", result["status"], result)
        self.assertEqual(0, result["data"]["map_id"])


if __name__ == "__main__":
    unittest.main()
