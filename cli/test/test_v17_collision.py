"""完整 30ms 位移的本地角色碰撞扫掠合同（真实 FootholdTree 几何）。"""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract, foothold_img


FLAT = [
    {"id": 1, "x1": -1000, "x2": 400, "y1": 1000, "y2": 1000, "prev": 0, "next": 2},
    {"id": 2, "x1": 400, "x2": 400, "y1": 800, "y2": 1000, "prev": 1, "next": 0},
]
SLOPE = [{"id": 1, "x1": 0, "x2": 100, "y1": 1000, "y2": 996, "prev": 0, "next": 0}]
EDGE = [{"id": 1, "x1": -100, "x2": 200, "y1": 1000, "y2": 1000, "prev": 0, "next": 0}]
CHAIN = [
    {"id": 1, "x1": -100, "x2": 200, "y1": 1000, "y2": 1000, "prev": 0, "next": 2},
    {"id": 2, "x1": 200, "x2": 500, "y1": 1000, "y2": 1000, "prev": 1, "next": 0},
]
LANDING = [{"id": 1, "x1": -100, "x2": 100, "y1": 1000, "y2": 1000, "prev": 0, "next": 0}]
EARLIEST = [
    {"id": 1, "x1": -100, "x2": 100, "y1": 1000, "y2": 1000, "prev": 0, "next": 0},
    {"id": 2, "x1": -100, "x2": 100, "y1": 1100, "y2": 1100, "prev": 0, "next": 0},
]
BORDERS = [{"id": 1, "x1": 900, "x2": 1000, "y1": 1000, "y2": 1000, "prev": 0, "next": 0}]
QUERIES = [
    {"id": 1, "x1": -100, "x2": 100, "y1": 1000, "y2": 1000, "prev": 0, "next": 0},
    {"id": 2, "x1": -100, "x2": 100, "y1": 1100, "y2": 1100, "prev": 0, "next": 0},
]


class V17CollisionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="v17-collision-")
        cls.addClassCleanup(temporary.cleanup)
        cls.build = Path(temporary.name)
        cls.executable = build_v17_contract(
            root, cls.build, "v17_collision_contract.cpp", motion=False, parameters=False, terrain=True
        )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=self.build)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def run_scenario(self, scenario: str, footholds: list[dict[str, int]]) -> None:
        foothold_img(self.directory, footholds)
        subprocess.run([str(self.executable), scenario, str(self.directory)], check=True, timeout=10)

    def test_flat_ground_snaps_to_the_surface_within_one_step(self) -> None:
        self.run_scenario("flat", FLAT)

    def test_slope_follows_surface_and_projects_velocity_onto_tangent(self) -> None:
        self.run_scenario("slope", SLOPE)

    def test_wall_limits_the_whole_segment_not_only_the_endpoint(self) -> None:
        self.run_scenario("wall", FLAT)

    def test_walking_off_the_end_leaves_ground_or_stops_for_rush(self) -> None:
        self.run_scenario("edge", EDGE)

    def test_connected_platform_segments_switch_without_leaving_ground(self) -> None:
        self.run_scenario("chain", CHAIN)

    def test_air_landing_is_committed_in_the_same_step(self) -> None:
        self.run_scenario("landing", LANDING)

    def test_earliest_crossed_platform_wins_and_ignore_foothold_skips_it(self) -> None:
        self.run_scenario("earliest", EARLIEST)

    def test_ground_and_jump_down_queries_use_the_map_tree(self) -> None:
        self.run_scenario("queries", QUERIES)

    def test_map_borders_clamp_airborne_motion(self) -> None:
        self.run_scenario("borders", BORDERS)


if __name__ == "__main__":
    unittest.main()
