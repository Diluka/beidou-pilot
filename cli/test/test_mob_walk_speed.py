"""Ground-monster walk force mapping contract (#253)."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract


class MobWalkSpeedContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="mob-walk-speed-")
        cls.addClassCleanup(temporary.cleanup)
        cls.executable = build_v17_contract(
            root,
            Path(temporary.name),
            "mob_walk_speed_contract.cpp",
            motion=False,
            parameters=False,
            terrain=False,
        )

    def test_doubled_legacy_walk_force_mapping(self) -> None:
        subprocess.run([str(self.executable)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
