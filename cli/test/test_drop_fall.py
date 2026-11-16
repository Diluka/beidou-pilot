"""V17 drop falling display contract (#258)."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract


class DropFallContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="drop-fall-")
        cls.addClassCleanup(temporary.cleanup)
        cls.executable = build_v17_contract(
            root,
            Path(temporary.name),
            "drop_fall_contract.cpp",
            motion=False,
            parameters=False,
            terrain=False,
        )

    def test_fall_descent_and_landing_formulas(self) -> None:
        subprocess.run([str(self.executable)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
