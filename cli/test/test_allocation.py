"""共享逐点养成确认合同，不连接客户端或消耗点数。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class AllocationContract(unittest.TestCase):
    def test_partial_facts_context_caps_cancellation_and_no_uncertain_replay(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "allocation-contract"
            subprocess.run(
                [
                    "g++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I" + str(root / "shared/lua-runtime"),
                    str(root / "shared/lua-runtime/Observation.cpp"),
                    str(root / "cli/test/allocation_contract.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable)], check=True, timeout=10)
