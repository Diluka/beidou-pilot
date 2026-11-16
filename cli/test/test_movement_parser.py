"""Inbound V17 movement path command layout contract."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract


class MovementParserContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="movement-parser-")
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        cls.executable = build_v17_contract(
            root,
            build,
            "movement_parser_contract.cpp",
            motion=False,
            parameters=False,
            terrain=False,
            movement_parser=True,
        )

    def test_documented_command_widths_and_field_identities(self) -> None:
        subprocess.run([str(self.executable)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
