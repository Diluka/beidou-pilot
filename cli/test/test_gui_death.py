"""GUI 原生死亡三态的离线合同；不替代真实客户端验证。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class GuiDeathContract(unittest.TestCase):
    def test_death_from_validated_current_state(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="gui-death-contract-") as directory:
            executable = Path(directory) / "gui-death-contract"
            subprocess.run(
                [
                    "g++",
                    "-std=c++14",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-pedantic",
                    f"-I{root / 'shared/lua-runtime'}",
                    f"-I{root / 'beidou-ijl15/ezorsia'}",
                    str(root / "cli/test/gui_death_contract.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable)], check=True)
