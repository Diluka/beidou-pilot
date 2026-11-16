"""Ladder object fields and the original segment query 0xA45B03."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract, map_img

LADDERS = [
    {"index": 1, "x": 95, "y1": 50, "y2": 150, "l": 1, "uf": 1},
    {"index": 2, "x": 90, "y1": 200, "y2": 250, "l": 0, "uf": 0},
    {"index": 3, "x": 200, "y1": 50, "y2": 150, "l": 1, "uf": 1},
]


class V17LadderQueryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="v17-ladder-")
        cls.addClassCleanup(temporary.cleanup)
        cls.build = Path(temporary.name)
        cls.executable = build_v17_contract(
            root,
            cls.build,
            "v17_ladder_query_contract.cpp",
            motion=False,
            parameters=False,
            terrain=True,
            mapinfo=True,
        )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=self.build)
        self.addCleanup(temporary.cleanup)
        self.map_directory = Path(temporary.name) / "map"
        map_img(self.map_directory, LADDERS)

    def run_scenario(self, scenario: str) -> None:
        subprocess.run(
            [str(self.executable), scenario, str(self.map_directory)],
            check=True,
            timeout=10,
        )

    def test_first_hit_and_fields(self) -> None:
        self.run_scenario("hit")

    def test_x_range_is_expanded_by_ten(self) -> None:
        self.run_scenario("x_expansion")

    def test_y_interval_must_overlap_top_bottom(self) -> None:
        self.run_scenario("y_overlap")

    def test_ladder_and_top_exit_flags(self) -> None:
        self.run_scenario("flags")


if __name__ == "__main__":
    unittest.main()
