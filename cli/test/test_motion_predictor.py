"""#243 pure C++ ordinary-motion predictor contract on real V17 rules."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract, foothold_img, physics_img


FLAT = [{"id": 1, "x1": -1000, "x2": 1000, "y1": 1000, "y2": 1000, "prev": 0, "next": 0}]
WALL = [
    {"id": 1, "x1": -1000, "x2": 400, "y1": 1000, "y2": 1000, "prev": 0, "next": 2},
    {"id": 2, "x1": 400, "x2": 400, "y1": 800, "y2": 1000, "prev": 1, "next": 0},
]
FIXTURES = {"flat": FLAT, "wall": WALL}


class MotionPredictorContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="motion-predictor-")
        cls.addClassCleanup(temporary.cleanup)
        cls.build = Path(temporary.name)
        cls.executable = build_v17_contract(
            root,
            cls.build,
            "motion_predictor_contract.cpp",
            motion=True,
            parameters=True,
            terrain=True,
            extra_sources=[root / "headless/src/MotionPredictor.cpp"],
        )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=self.build)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def run_scenario(self, scenario: str, fixture: str) -> None:
        physics = self.directory / "physics"
        physics.mkdir()
        physics_img(physics)
        map_directory = self.directory / "map"
        foothold_img(map_directory, FIXTURES[fixture])
        subprocess.run(
            [str(self.executable), scenario, str(physics), str(map_directory)],
            check=True, timeout=10)

    def test_explicit_state_ground_brake_bounded_advance_and_copy_branches(self) -> None:
        self.run_scenario("ground", "flat")

    def test_jump_edge_gravity_and_air_landing_collision(self) -> None:
        self.run_scenario("jump-landing", "flat")

    def test_wall_collision_and_unsupported_states_are_explicit(self) -> None:
        self.run_scenario("wall-unsupported", "wall")


if __name__ == "__main__":
    unittest.main()
