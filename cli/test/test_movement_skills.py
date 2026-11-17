"""V17 movement-skill impulse contract (#254)."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract


class MovementSkillsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="movement-skills-")
        cls.addClassCleanup(temporary.cleanup)
        cls.executable = build_v17_contract(
            root,
            Path(temporary.name),
            "movement_skills_contract.cpp",
            motion=False,
            parameters=False,
            terrain=False,
        )

    def test_flash_jump_impulse_formula(self) -> None:
        subprocess.run([str(self.executable)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
