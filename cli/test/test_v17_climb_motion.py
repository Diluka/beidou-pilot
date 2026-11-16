"""Attached climb 30ms contract: literal original branch values from #250 §2."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract, physics_img


class V17ClimbMotionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="v17-climb-")
        cls.addClassCleanup(temporary.cleanup)
        cls.build = Path(temporary.name)
        cls.executable = build_v17_contract(
            root,
            cls.build,
            "v17_climb_contract.cpp",
            motion=False,
            parameters=True,
            terrain=True,
            climb=True,
        )

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=self.build)
        self.addCleanup(temporary.cleanup)
        self.physics = Path(temporary.name) / "physics"
        self.physics.mkdir()
        physics_img(self.physics)

    def run_scenario(self, scenario: str) -> None:
        subprocess.run(
            [str(self.executable), scenario, str(self.physics)],
            check=True,
            timeout=10,
        )

    def test_vertical_steps_are_three_pixels_per_30ms(self) -> None:
        self.run_scenario("up")
        self.run_scenario("down")
        self.run_scenario("stop")

    def test_top_exit_and_top_clamp_are_asymmetric(self) -> None:
        self.run_scenario("top-exit")
        self.run_scenario("top-clamp")

    def test_bottom_exit_lands_at_bottom_plus_one(self) -> None:
        self.run_scenario("down")

    def test_jump_off_uses_original_written_velocities_or_drops_without_direction(self) -> None:
        self.run_scenario("jump")
        self.run_scenario("jump-no-direction")


if __name__ == "__main__":
    unittest.main()
