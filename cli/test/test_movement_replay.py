"""V17 inbound movement path playback contract."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.v17_fixtures import build_v17_contract


class MovementReplayContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="movement-replay-")
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        cls.executable = build_v17_contract(
            root,
            build,
            "movement_replay_contract.cpp",
            motion=False,
            parameters=False,
            terrain=False,
            replay=True,
        )

    def test_absolute_relative_catch_up_and_zero_duration_paths(self) -> None:
        subprocess.run([str(self.executable)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
