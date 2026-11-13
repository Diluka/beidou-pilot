"""真实 MovingObject/MapObjects/Drop/Bullet 完整原生步采样合同，不证明线上命中或服务器速度。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class HeadlessMotionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        cls.executable = build / "headless-motion-contract"
        sources = [
            "Gameplay/Physics/Physics.cpp",
            "Gameplay/Physics/Foothold.cpp",
            "Gameplay/Physics/FootholdTree.cpp",
            "Gameplay/MapleMap/MapObject.cpp",
            "Gameplay/MapleMap/MapObjects.cpp",
            "Gameplay/MapleMap/Drop.cpp",
            "Gameplay/Combat/Bullet.cpp",
            "Graphics/Animation.cpp",
        ]
        subprocess.run(
            [
                "g++",
                "-std=c++20",
                "-O0",
                "-DHEADLESS",
                "-ffunction-sections",
                "-fdata-sections",
                "-Wl,--gc-sections",
                "-include",
                str(root / "headless/src/PlatformIncludes.h"),
                f"-I{engine}",
                f"-I{engine / 'includes/NoLifeNx'}",
                f"-I{root / 'shared/lua-runtime'}",
                *[str(engine / source) for source in sources],
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(root / "cli/test/headless_motion_contract.cpp"),
                "-o",
                str(cls.executable),
            ],
            cwd=build,
            check=True,
        )

    def test_fractional_complete_update_and_known_zero_vs_unknown(self) -> None:
        subprocess.run([str(self.executable), "primitive"], check=True, timeout=10)

    def test_real_map_collection_wrapper_resets_reposition_and_native_lifetime(self) -> None:
        subprocess.run([str(self.executable), "wrapper"], check=True, timeout=10)

    def test_actual_drop_hover_and_stationary_pickup_fade(self) -> None:
        subprocess.run([str(self.executable), "drop"], check=True, timeout=10)

    def test_actual_mode2_pickup_samples_before_next_step_speed_is_written(self) -> None:
        subprocess.run([str(self.executable), "pickup-phase"], check=True, timeout=10)

    def test_actual_bullet_motion_samples_its_own_native_update(self) -> None:
        subprocess.run([str(self.executable), "bullet"], check=True, timeout=10)

    def test_shared_movable_contract_labels_interval_mean_not_server_velocity(self) -> None:
        subprocess.run([str(self.executable), "contract"], check=True, timeout=10)
