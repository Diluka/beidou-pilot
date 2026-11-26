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

    def test_navigation_uses_foothold_links_for_walls_and_cliff_edges(self) -> None:
        # get_wall follows prev/next (and their neighbours), not arbitrary
        # vertical geometry crossing a floor. A missing link marks a cliff.
        cases = {
            "continuous_floor_with_unlinked_vertical": (
                [(1, 0, 100, 300, 300, 0, 2), (2, 100, 200, 300, 300, 1, 0),
                 (3, 50, 50, 200, 320, 0, 0)],
                [(0, 200, True, True)],
            ),
            "cliff_above_lower_floor": (
                [(1, 0, 100, 300, 300, 0, 0), (2, 110, 250, 400, 400, 0, 0)],
                [(0, 100, True, True), (110, 250, True, True)],
            ),
            "dead_end_wall": (
                [(1, 0, 100, 300, 300, 0, 2), (2, 100, 100, 200, 300, 1, 0)],
                [(0, 100, True, False)],
            ),
        }
        for name, (rows, expected) in cases.items():
            with self.subTest(case=name):
                properties = {"foothold": {"1": {"0": {
                    str(i): {"x1": x1, "x2": x2, "y1": y1, "y2": y2, "prev": prev, "next": next_}
                    for i, x1, x2, y1, y2, prev, next_ in rows
                }}}}
                for result in self.query(properties):
                    platforms = result["data"]["navigation"]["platforms"]
                    self.assertEqual(expected, [
                        (p["left"], p["right"], p["open_left"], p["open_right"])
                        for p in platforms
                    ])
                    if name == "cliff_above_lower_floor":
                        drop = result["data"]["navigation"]["candidates"]["drop"]
                        self.assertIn((1, 2), [(drop[i], drop[i + 1]) for i in range(0, len(drop), 5)])

    def test_map_102000000_linked_wall_steps_have_descending_candidates(self) -> None:
        # Real IMG footholds around the 485 -> 545 -> 605 descent. Vertical
        # links comprise two segments at each ledge, not a free-standing wall.
        rows = [
            (56, 636, 636, 570, 545, 75, 57), (57, 636, 714, 545, 545, 56, 58),
            (58, 714, 726, 545, 545, 57, 60), (60, 726, 726, 545, 510, 58, 63),
            (63, 726, 726, 510, 485, 60, 64), (64, 726, 765, 485, 485, 63, 61),
            (61, 765, 804, 485, 485, 64, 65), (65, 804, 855, 485, 485, 61, 62),
            (73, 405, 495, 605, 605, 72, 76), (76, 495, 585, 605, 605, 73, 74),
            (74, 585, 636, 605, 605, 76, 75), (75, 636, 636, 605, 570, 74, 56),
        ]
        properties = {"foothold": {"1": {"0": {
            str(i): {"x1": x1, "x2": x2, "y1": y1, "y2": y2, "prev": prev, "next": next_}
            for i, x1, x2, y1, y2, prev, next_ in rows
        }}}}
        for result in self.query(properties):
            navigation = result["data"]["navigation"]
            by_height = {p["segments"][2]: p["index"] for p in navigation["platforms"]}
            edges = navigation["candidates"]["drop"]
            pairs = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 5)]
            self.assertIn((by_height[485], by_height[545]), pairs)
            self.assertIn((by_height[545], by_height[605]), pairs)

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
            platforms = navigation["platforms"]
            self.assertEqual(
                [(-200, 200), (240, 400), (402, 560), (250, 350), (230, 320), (100, 200)],
                [(p["left"], p["right"]) for p in platforms],
            )
            self.assertEqual([-200, 0, 300, 300, 0, 200, 300, 300], platforms[0]["segments"])
            self.assertTrue(platforms[0]["open_left"])
            self.assertTrue(platforms[0]["open_right"])
            self.assertEqual(
                [{"index": 2, "x": 140, "y1": 100, "y2": 320, "platforms": [6, 200, 1, 300]}],
                navigation["ropes"],
            )
            self.assertEqual({
                "walk": [2, 3, 392, 416, 0, 3, 2, 410, 386, 0],
                "step": [1, 2, 194, 250, 50, 2, 6, 246, 190, 50],
                "jumpup": [4, 2, 300, 300, 50],
                "drop": [1, 5, 192, 247.5, 100, 2, 1, 248, 187.5, 50,
                         2, 5, 248, 233, 150, 3, 4, 410, 343.5, 50,
                         4, 5, 258, 238, 100, 6, 1, 108, 65.5, 100,
                         6, 2, 192, 252.5, 50, 6, 4, 192, 257.5, 100,
                         6, 5, 192, 247.5, 200],
                "rope": [6, 1, 140, 140, 100, 2, 1, 6, 140, 140, -100, 2],
            }, navigation["candidates"])

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
