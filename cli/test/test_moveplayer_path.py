"""V17 MOVE_PLAYER path recorder contract (#259)."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract


class MovePlayerPathContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="moveplayer-path-")
        cls.addClassCleanup(temporary.cleanup)
        cls.executable = build_v17_contract(
            root,
            Path(temporary.name),
            "moveplayer_path_contract.cpp",
            motion=False,
            parameters=False,
            terrain=False,
        )

    def test_merge_gate_directions_and_bounds(self) -> None:
        subprocess.run([str(self.executable)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
