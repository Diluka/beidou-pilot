"""V17 floating drop display contract (#258)."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract


class DropDisplayContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="drop-display-")
        cls.addClassCleanup(temporary.cleanup)
        cls.executable = build_v17_contract(
            root,
            Path(temporary.name),
            "drop_display_contract.cpp",
            motion=False,
            parameters=False,
            terrain=False,
        )

    def test_floating_phase_rate_and_offsets(self) -> None:
        subprocess.run([str(self.executable)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
