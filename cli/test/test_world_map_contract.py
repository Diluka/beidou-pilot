"""World-map portal model, versioned cache and directed route contract."""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from test.img_fixture import write_img


MAPS = {
    101000000: {
        "in00": {"pn": "in00", "x": 10, "y": 20, "pt": 2, "tm": 102000000, "tn": "out00"},
        "sp": {"x": 0, "y": 0, "pt": 0},
    },
    102000000: {
        "out00": {"pn": "out00", "x": -5, "y": 6, "pt": 2, "tm": 101000000, "tn": "in00"},
        "in00": {"pn": "in00", "x": 30, "y": 40, "pt": 2, "tm": 103000000, "tn": "out00"},
    },
    103000000: {
        "out00": {"pn": "out00", "x": 50, "y": 60, "pt": 2, "tm": 102000000, "tn": "in00"},
    },
}


def write_maps(root: Path, maps: dict[int, dict[str, dict[str, int | str]]]) -> None:
    for map_id, portals in maps.items():
        path = root / "Map" / "Map" / f"Map{map_id // 100000000}" / f"{map_id:09d}.img"
        write_img(path, {"portal": {str(index): portal for index, portal in enumerate(portals.values())}})


class WorldMapContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="world-map-contract-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        root = Path(__file__).resolve().parents[2]
        native = root / "headless/src"
        shared = root / "shared/lua-runtime"
        library = cls.directory / "libbeidou-img.so"
        subprocess.run(
            ["g++", "-std=c++17", "-O2", "-fPIC", "-shared", str(native / "ImgResources.cpp"),
             str(native / "ImgKeys.cpp"), "-o", str(library)],
            check=True, cwd=cls.directory, timeout=90)
        cls.executable = cls.directory / "world-map-contract"
        subprocess.run(
            [
                "g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                f"-I{native}", f"-I{shared}", str(root / "cli/test/world_map_contract.cpp"),
                str(native / "WorldMapImage.cpp"), f"-L{cls.directory}", "-Wl,-rpath,$ORIGIN",
                "-lbeidou-img", "-o", str(cls.executable),
            ],
            check=True, cwd=cls.directory, timeout=90)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=self.directory)
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name) / "data"
        self.cache = Path(temporary.name) / "cache"
        write_maps(self.data, MAPS)

    def run_contract(self, *arguments: str) -> dict:
        result = subprocess.run([str(self.executable), *arguments], check=True, text=True,
                                capture_output=True, timeout=90)
        return json.loads(result.stdout)

    def test_pure_model_covers_filter_merge_route_escaping_and_fingerprint(self) -> None:
        result = self.run_contract("model")
        self.assertEqual("ok", result["model"])
        self.assertEqual(2, result["legs"])
        self.assertTrue(result["roundtrip"])

    def test_cache_builds_versioned_path_then_hits(self) -> None:
        built = self.run_contract("cache", str(self.data), str(self.cache))
        self.assertEqual("built", built["cache"])
        self.assertEqual(3, built["maps"])
        self.assertEqual(4, built["edges"])
        self.assertEqual("ok", built["route"])
        self.assertEqual(2, built["legs"])
        path = self.cache / "world-map" / "1" / f"{built['fingerprint']}.wmap"
        self.assertTrue(path.is_file(), path)
        cached = self.run_contract("cache", str(self.data), str(self.cache))
        self.assertEqual("hit", cached["cache"])
        self.assertEqual(built["fingerprint"], cached["fingerprint"])
        self.assertEqual(2, cached["legs"])

    def test_corrupt_cache_rebuilds_and_source_change_keeps_old_file(self) -> None:
        built = self.run_contract("cache", str(self.data), str(self.cache))
        old_path = self.cache / "world-map" / "1" / f"{built['fingerprint']}.wmap"
        old_path.write_text("broken cache\n")
        rebuilt = self.run_contract("cache", str(self.data), str(self.cache))
        self.assertEqual("built", rebuilt["cache"])
        self.assertEqual(built["fingerprint"], rebuilt["fingerprint"])
        portal = self.data / "Map" / "Map" / "Map1" / "101000000.img"
        write_img(portal, {"portal": {"0": {"pn": "in00", "x": 11, "y": 20, "pt": 2,
                                             "tm": 102000000, "tn": "out00"}}})
        changed = self.run_contract("cache", str(self.data), str(self.cache))
        self.assertEqual("built", changed["cache"])
        self.assertNotEqual(built["fingerprint"], changed["fingerprint"])
        self.assertTrue((self.cache / "world-map" / "1" / f"{changed['fingerprint']}.wmap").is_file())
        self.assertTrue(old_path.is_file(), "runtime must not delete old versioned caches")

    def test_missing_cache_root_builds_in_memory_only(self) -> None:
        result = self.run_contract("cache", str(self.data), "")
        self.assertEqual("memory", result["cache"])
        self.assertEqual("ok", result["route"])


if __name__ == "__main__":
    unittest.main()
