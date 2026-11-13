"""GUI 登录页面候选识别合同，不运行游戏。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class NativeLoginPageContract(unittest.TestCase):
    def test_observed_candidates_and_unknown_fallback(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "native-login-page-contract"
            subprocess.run(
                [
                    "g++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I" + str(root / "beidou-ijl15/ezorsia"),
                    str(root / "cli/test/native_login_page_contract.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable)], check=True, timeout=10)
