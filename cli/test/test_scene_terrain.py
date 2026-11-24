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


# Richer static geometry for the navigation topology contract: a wall splits a
# merged floor, and the fixtures cover walk/step/jumpup/drop/rope candidates.
NAVIGATION_FOOTHOLDS = [
    {"id": 1, "x1": -200, "x2": 0, "y1": 300, "y2": 300, "prev": 0, "next": 2},
    {"id": 2, "x1": 0, "x2": 200, "y1": 300, "y2": 300, "prev": 1, "next": 0},
    {"id": 3, "x1": 240, "x2": 400, "y1": 250, "y2": 250, "prev": 0, "next": 0},
    {"id": 4, "x1": 402, "x2": 560, "y1": 250, "y2": 250, "prev": 0, "next": 0},
    {"id": 5, "x1": 250, "x2": 350, "y1": 300, "y2": 300, "prev": 0, "next": 0},
    {"id": 6, "x1": 230, "x2": 320, "y1": 400, "y2": 400, "prev": 0, "next": 0},
    {"id": 7, "x1": 100, "x2": 200, "y1": 200, "y2": 200, "prev": 0, "next": 0},
    {"id": 8, "x1": 100, "x2": 100, "y1": 250, "y2": 320, "prev": 0, "next": 0},
]
NAVIGATION_ROPE = {"index": 2, "x": 140, "y1": 100, "y2": 320}


def map_properties() -> dict:
    return {
        "info": {},
        "foothold": {
            "1": {"0": {str(row["id"]): {key: value for key, value in row.items() if key != "id"} for row in FOOTHOLDS}}
        },
        "ladderRope": {"1": {key: value for key, value in ROPE.items() if key != "index"}},
    }


def navigation_properties() -> dict:
    return {
        "info": {},
        "foothold": {
            "1": {
                "0": {
                    str(row["id"]): {key: value for key, value in row.items() if key != "id"}
                    for row in NAVIGATION_FOOTHOLDS
                }
            }
        },
        "ladderRope": {
            str(NAVIGATION_ROPE["index"]): {key: value for key, value in NAVIGATION_ROPE.items() if key != "index"}
        },
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
            self.assertNotIn("navigation", result["data"])

    def test_flat_sloped_wall_and_rope_coordinates_keep_original_connections(self) -> None:
        for result in self.query(map_properties(), 123456789):
            self.assertEqual("ok", result["status"])
            self.assertIsNone(result["error"])
            self.assertEqual(FOOTHOLDS, result["data"]["footholds"])
            self.assertEqual([ROPE], result["data"]["ropes"])
            self.assertNotIn("terrain", result["data"])

    def test_wall_adjacent_upward_jumps(self) -> None:
        # Observed map 10000 wall and floor endpoints, simplified to merged segments.
        rows = [
            (1, 225, 366, 485, 485),
            (2, 366, 456, 425, 425),
            (3, 456, 495, 365, 365),
            (4, 366, 366, 425, 485),
            (5, 456, 456, 365, 425),
        ]
        properties = {
            "info": {},
            "foothold": {
                "1": {
                    "0": {
                        str(i): {"x1": x1, "x2": x2, "y1": y1, "y2": y2, "prev": 0, "next": 0}
                        for i, x1, x2, y1, y2 in rows
                    }
                }
            },
        }
        for backend, result in zip(self.executables, self.query(properties)):
            with self.subTest(backend=backend):
                edges = result["data"]["navigation"]["candidates"]["jumpup"]
                tuples = [edges[i : i + 5] for i in range(0, len(edges), 5)]
                self.assertIn([1, 2, 360, 376, 60], tuples)
                self.assertIn([2, 3, 450, 466, 60], tuples)

    def test_wall_jump_rejects_unsafe_geometry(self) -> None:
        base = [(1, 225, 366, 485, 485), (2, 366, 456, 425, 425), (3, 366, 366, 425, 485)]
        cases = {
            "wall_too_high": [base[0], base[1], (3, 366, 366, 420, 485)],
            "rise_too_high": [base[0], (2, 366, 456, 409, 409), (3, 366, 366, 409, 485)],
            "no_landing": [base[0], (2, 366, 366, 425, 425), base[2]],
            "not_standable": [*base, (4, 366, 456, 375, 375)],
            "narrow_target": [base[0], (2, 366, 374, 425, 425), base[2]],
            "landing_blocked": [*base, (4, 376, 376, 400, 450)],
            "middle_wall": [*base, (4, 370, 370, 395, 410)],
            "middle_ceiling": [*base, (4, 360, 368, 390, 390)],
        }
        for name, rows in cases.items():
            with self.subTest(case=name):
                properties = {
                    "info": {},
                    "foothold": {
                        "1": {
                            "0": {
                                str(i): {"x1": x1, "x2": x2, "y1": y1, "y2": y2, "prev": 0, "next": 0}
                                for i, x1, x2, y1, y2 in rows
                            }
                        }
                    },
                }
                for result in self.query(properties):
                    edges = result["data"]["navigation"]["candidates"]["jumpup"]
                    self.assertNotIn((1, 2), [(edges[i], edges[i + 1]) for i in range(0, len(edges), 5)])

    def test_static_navigation_topology_exposes_platforms_walls_ropes_and_candidates(self) -> None:
        for result in self.query(navigation_properties(), 123456789):
            self.assertEqual("ok", result["status"], result)
            navigation = result["data"]["navigation"]
            self.assertEqual(
                {
                    "stand_height": 70,
                    "wall_margin": 12,
                    "min_platform_width": 16,
                    "jump_rise": 75,
                    "drop_min": 4,
                    "drop_max": 65,
                    "rope_grab": 76,
                },
                navigation["model"],
            )
            self.assertEqual([-200, 560], [navigation["terrain_left"], navigation["terrain_right"]])
            self.assertEqual([100, 250, 320], navigation["walls"])
            self.assertEqual(
                [
                    {"index": 1, "left": -200, "right": 88, "open_left": True, "open_right": False},
                    {"index": 2, "left": 112, "right": 200, "open_left": False, "open_right": True},
                    {"index": 3, "left": 240, "right": 400, "open_left": True, "open_right": True},
                    {"index": 4, "left": 402, "right": 560, "open_left": True, "open_right": True},
                    {"index": 5, "left": 250, "right": 350, "open_left": True, "open_right": True},
                    {"index": 6, "left": 230, "right": 320, "open_left": True, "open_right": True},
                    {"index": 7, "left": 100, "right": 200, "open_left": True, "open_right": True},
                ],
                [
                    {key: platform[key] for key in ("index", "left", "right", "open_left", "open_right")}
                    for platform in navigation["platforms"]
                ],
            )
            self.assertEqual([-200, 0, 300, 300, 0, 88, 300, 300], navigation["platforms"][0]["segments"])
            self.assertEqual([112, 200, 300, 300], navigation["platforms"][1]["segments"])
            self.assertEqual([100, 200, 200, 200], navigation["platforms"][6]["segments"])
            self.assertEqual(
                [{"index": 2, "x": 140, "y1": 100, "y2": 320, "platforms": [7, 200, 2, 300]}],
                navigation["ropes"],
            )
            candidates = navigation["candidates"]
            self.assertEqual([3, 4, 392, 416, 0, 4, 3, 410, 386, 0], candidates["walk"])
            self.assertEqual([2, 3, 194, 250, 50, 3, 7, 246, 190, 50], candidates["step"])
            self.assertEqual([5, 3, 300, 300, 50], candidates["jumpup"])
            self.assertEqual(
                [
                    2,
                    6,
                    192,
                    247.5,
                    100,
                    3,
                    2,
                    248,
                    187.5,
                    50,
                    3,
                    6,
                    248,
                    233,
                    150,
                    4,
                    5,
                    410,
                    343.5,
                    50,
                    5,
                    6,
                    258,
                    238,
                    100,
                    7,
                    1,
                    108,
                    61.5,
                    100,
                    7,
                    3,
                    192,
                    252.5,
                    50,
                    7,
                    5,
                    192,
                    257.5,
                    100,
                    7,
                    6,
                    192,
                    247.5,
                    200,
                ],
                candidates["drop"],
            )
            self.assertEqual([7, 2, 140, 140, 100, 2, 2, 7, 140, 140, -100, 2], candidates["rope"])

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
