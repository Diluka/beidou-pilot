"""编译真实 Physics.cpp，以独立递推和离散积分核对普通运动参考模型。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class MotionReferenceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        cls.executable = build / "motion-reference-contract"
        subprocess.run(
            [
                "g++",
                "-std=c++20",
                "-O0",
                "-Wall",
                "-Wextra",
                "-DHEADLESS",
                "-ffunction-sections",
                "-fdata-sections",
                "-include",
                str(root / "headless/src/PlatformIncludes.h"),
                f"-I{engine}",
                f"-I{engine / 'includes/NoLifeNx'}",
                str(engine / "Gameplay/Physics/Physics.cpp"),
                str(root / "cli/test/motion_reference_contract.cpp"),
                "-Wl,--gc-sections",
                "-o",
                str(cls.executable),
            ],
            cwd=build,
            check=True,
        )

    def test_flat_walk_reference_matches_discrete_acceleration(self) -> None:
        subprocess.run([str(self.executable), "walk"], check=True, timeout=10)

    def test_jump_reference_matches_discrete_apex_and_grounded_launch_step(self) -> None:
        subprocess.run([str(self.executable), "jump"], check=True, timeout=10)
