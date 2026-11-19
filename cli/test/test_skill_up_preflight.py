import pathlib
import subprocess
import tempfile
import unittest


class SkillUpPreflightTest(unittest.TestCase):
    def test_native_preflight(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / "skill-up-test"
            subprocess.run(["c++", "-std=c++17", "-I", str(root / "headless/src"),
                            str(root / "cli/test/skill_up_preflight_contract.cpp"),
                            "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
