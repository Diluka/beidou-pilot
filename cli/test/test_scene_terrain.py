"""One terrain contract over real hot nl::nodes and restricted IMG C API nodes."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from test.img_fixture import Uol, write_img


FOOTHOLDS = [
    {"id": 5, "x1": -90, "x2": 180, "y1": 335, "y2": 335, "prev": 0, "next": 7},
    {"id": 7, "x1": 180, "x2": 250, "y1": 335, "y2": 290, "prev": 5, "next": 9},
    {"id": 9, "x1": 250, "x2": 250, "y1": 290, "y2": 120, "prev": 7, "next": 0},
]
ROPE = {"index": 1, "x": 262, "y1": -23, "y2": 333, "l": 0, "uf": 1}


def map_properties() -> dict:
    return {
        "info": {},
        "foothold": {
            "1": {"0": {str(row["id"]): {key: value for key, value in row.items() if key != "id"} for row in FOOTHOLDS}}
        },
        "ladderRope": {"1": {key: value for key, value in ROPE.items() if key != "index"}},
    }


class SceneTerrainContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="scene-terrain-contract-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        root = Path(__file__).resolve().parents[2]
        native = root / "headless/src"
        shared = root / "shared/lua-runtime"
        nlnx = root / "third_party/maplestory-client/includes/NoLifeNx/nlnx"
        library = cls.directory / "libbeidou-img.so"
        subprocess.run(
            [
                "g++",
                "-std=c++17",
                "-O2",
                "-fPIC",
                "-shared",
                str(native / "ImgResources.cpp"),
                str(native / "ImgKeys.cpp"),
                "-o",
                str(library),
            ],
            check=True,
            cwd=cls.directory,
            timeout=90,
        )
        common = [
            "-Wall",
            "-Wextra",
            "-Werror",
            "-ffunction-sections",
            "-fdata-sections",
            "-Wl,--gc-sections",
            f"-I{native}",
            f"-I{shared}",
            str(root / "cli/test/scene_terrain_contract.cpp"),
            str(shared / "Observation.cpp"),
        ]
        linking = [f"-L{cls.directory}", "-Wl,-rpath,$ORIGIN", "-lbeidou-img"]
        cls.executables = {
            "single_img_cpp14": cls.directory / "terrain-cpp14",
            "headless_hot_tree": cls.directory / "terrain-hot-tree",
        }
        subprocess.run(
            ["g++", "-std=c++14", *common, *linking, "-o", str(cls.executables["single_img_cpp14"])],
            check=True,
            cwd=cls.directory,
            timeout=90,
        )
        subprocess.run(
            [
                "g++",
                "-std=c++20",
                "-DTERRAIN_HOT_TREE",
                f"-I{nlnx.parent}",
                *common,
                str(native / "ImgResourceFile.cpp"),
                str(nlnx / "file.cpp"),
                str(nlnx / "node.cpp"),
                *linking,
                "-o",
                str(cls.executables["headless_hot_tree"]),
            ],
            check=True,
            cwd=cls.directory,
            timeout=90,
        )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=self.directory)
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)

    def query(self, properties: dict, map_id: int = 50000) -> list[dict]:
        source = write_img(self.data / f"{map_id:09d}.img", properties)
        results = []
        for backend, executable in self.executables.items():
            with self.subTest(backend=backend):
                completed = subprocess.run(
                    [str(executable), str(self.data), source.name, str(map_id)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                result = json.loads(completed.stdout)
                self.assertEqual(map_id, result["data"]["map_id"])
                self.assertEqual(str(source), result["data"]["source"])
                results.append(result)
        self.assertEqual(results[0], results[1])
        return results

    def assert_failure(self, properties: dict, status: str, error: str) -> None:
        for result in self.query(properties):
            self.assertEqual(status, result["status"])
            self.assertEqual(error, result["error"])
            self.assertNotIn("footholds", result["data"])
            self.assertNotIn("ropes", result["data"])

    def test_flat_sloped_wall_and_rope_coordinates_keep_original_connections(self) -> None:
        for result in self.query(map_properties(), 123456789):
            self.assertEqual("ok", result["status"])
            self.assertIsNone(result["error"])
            self.assertEqual(FOOTHOLDS, result["data"]["footholds"])
            self.assertEqual([ROPE], result["data"]["ropes"])
            self.assertNotIn("terrain", result["data"])

    def test_empty_rope_is_available_and_minimal_rope_fields_are_sufficient(self) -> None:
        properties = map_properties()
        del properties["ladderRope"]
        for result in self.query(properties):
            self.assertEqual("ok", result["status"])
            self.assertEqual([], result["data"]["ropes"])
        properties["ladderRope"] = {"1": {"x": 262, "y1": -23, "y2": 333}}
        for result in self.query(properties):
            self.assertEqual("ok", result["status"])
            self.assertEqual([{"index": 1, "x": 262, "y1": -23, "y2": 333}], result["data"]["ropes"])

    def test_link_does_not_override_or_reject_complete_own_geometry(self) -> None:
        properties = map_properties()
        properties["info"] = {"link": "50001"}
        write_img(self.data / "000050001.img", {"foothold": {"1": {"0": {"1": {"x1": 9999}}}}})
        for result in self.query(properties):
            self.assertEqual("ok", result["status"])
            self.assertEqual(FOOTHOLDS, result["data"]["footholds"])

    def test_empty_own_footholds_is_unavailable_or_link_unsupported_without_fallback(self) -> None:
        self.assert_failure({}, "unavailable", "hunt_terrain_unavailable")
        self.assert_failure({"foothold": {}}, "unavailable", "hunt_terrain_unavailable")
        # Even a present target with valid geometry cannot fill this map.
        write_img(self.data / "000050001.img", map_properties())
        self.assert_failure({"info": {"link": 50001}}, "unsupported", "hunt_terrain_unsupported")

    def test_every_missing_foothold_field_and_noninteger_coordinate_is_invalid(self) -> None:
        for field in ("x1", "x2", "y1", "y2", "prev", "next"):
            with self.subTest(field=field):
                properties = map_properties()
                del properties["foothold"]["1"]["0"]["5"][field]
                self.assert_failure(properties, "unavailable", "hunt_terrain_invalid")
        properties = map_properties()
        properties["foothold"]["1"]["0"]["5"]["x1"] = "-90"
        self.assert_failure(properties, "unavailable", "hunt_terrain_invalid")

    def test_invalid_foothold_id_and_rope_index_are_not_coerced_to_zero(self) -> None:
        properties = map_properties()
        rows = properties["foothold"]["1"]["0"]
        rows["not-an-id"] = rows.pop("5")
        self.assert_failure(properties, "unavailable", "hunt_terrain_invalid")
        properties = map_properties()
        properties["ladderRope"]["not-an-index"] = properties["ladderRope"].pop("1")
        self.assert_failure(properties, "unavailable", "hunt_terrain_invalid")

    def test_incomplete_or_noninteger_rope_cannot_publish_partial_footholds(self) -> None:
        for field in ("x", "y1", "y2"):
            with self.subTest(field=field):
                properties = map_properties()
                del properties["ladderRope"]["1"][field]
                self.assert_failure(properties, "unavailable", "hunt_terrain_invalid")
        properties = map_properties()
        properties["ladderRope"]["1"]["y1"] = "-23"
        self.assert_failure(properties, "unavailable", "hunt_terrain_invalid")

    def test_unresolved_required_geometry_uol_is_not_a_zero_coordinate(self) -> None:
        properties = deepcopy(map_properties())
        properties["foothold"]["1"]["0"]["5"]["x1"] = Uol("missing")
        self.assert_failure(properties, "unavailable", "hunt_terrain_invalid")


if __name__ == "__main__":
    unittest.main()
