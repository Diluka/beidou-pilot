"""普通 30ms 运动核心合同：字面锚点来自 #237 表与 GUI 真机基线。"""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract, foothold_img, physics_img


FLAT = [{"id": 1, "x1": -1000, "x2": 1000, "y1": 1000, "y2": 1000, "prev": 0, "next": 0}]
SLOPE = [{"id": 1, "x1": 0, "x2": 100, "y1": 1000, "y2": 996, "prev": 0, "next": 0}]
AIR = [
    {"id": 1, "x1": -100, "x2": 100, "y1": 1000, "y2": 1000, "prev": 0, "next": 0},
    {"id": 2, "x1": -100, "x2": 100, "y1": -1000, "y2": -1000, "prev": 0, "next": 0},
]
DROP = [
    {"id": 1, "x1": -100, "x2": 100, "y1": 1000, "y2": 1000, "prev": 0, "next": 0},
    {"id": 2, "x1": -100, "x2": 100, "y1": 1100, "y2": 1100, "prev": 0, "next": 0},
]
FIXTURES = {"flat": FLAT, "slope": SLOPE, "air": AIR, "drop": DROP}


class V17NormalMotionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="v17-motion-")
        cls.addClassCleanup(temporary.cleanup)
        cls.build = Path(temporary.name)
        cls.executable = build_v17_contract(
            root, cls.build, "v17_normal_motion_contract.cpp", motion=True, parameters=True, terrain=True
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
        subprocess.run([str(self.executable), scenario, str(physics), str(map_directory)], check=True, timeout=10)

    def test_ground_acceleration_brake_reverse_and_speed_ratios(self) -> None:
        self.run_scenario("ground", "flat")

    def test_slope_speed_is_projected_onto_the_platform_tangent(self) -> None:
        self.run_scenario("slope", "slope")

    def test_fly_air_uses_dynamic_calibrated_sequences(self) -> None:
        self.run_scenario("fly-air", "flat")

    def test_swim_air_uses_dynamic_calibrated_sequences(self) -> None:
        self.run_scenario("swim-air", "flat")

    def test_field_multipliers_scale_force_and_brake_but_not_speed_limit(self) -> None:
        self.run_scenario("field-multipliers", "flat")

    def test_jump_impulse_boost_clamp_and_jump_ratio(self) -> None:
        self.run_scenario("jump", "flat")

    def test_air_gravity_terminal_speed_trapezoid_and_horizontal_rules(self) -> None:
        self.run_scenario("air", "air")

    def test_down_jump_uses_native_impulse_and_drops_through(self) -> None:
        self.run_scenario("jumpdown", "drop")

    def test_external_impulse_write_is_a_sample_and_integrates_next_step(self) -> None:
        self.run_scenario("impulse-write", "air")

    def test_hurt_impulse_queue_detach_merge_truncate_then_air(self) -> None:
        self.run_scenario("hurt-impulse", "flat")

    def test_withdrawn_jump_is_not_consumed_by_a_later_step(self) -> None:
        self.run_scenario("no-late-jump", "flat")

    def test_reference_model_uses_v17_parameters_not_the_old_journey_model(self) -> None:
        self.run_scenario("reference", "flat")


if __name__ == "__main__":
    unittest.main()
