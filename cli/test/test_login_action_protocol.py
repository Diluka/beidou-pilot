"""原生登录/建角动作请求格式的离线合同，不运行游戏。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class LoginActionProtocolContract(unittest.TestCase):
    def test_request_line_base64_and_bounds(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "login-action-contract"
            subprocess.run(
                [
                    "g++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I" + str(root / "beidou-ijl15/ezorsia"),
                    str(root / "cli/test/login_action_contract.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable)], check=True, timeout=10)
