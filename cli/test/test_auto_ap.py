"""离线核对无头自动 AP 计划，不替代开发服封包与效果验收。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class AutoApContract(unittest.TestCase):
    def test_original_client_allocation_rules(self) -> None:
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(prefix="auto-ap-contract-") as temporary:
            executable = Path(temporary) / "auto-ap-contract"
            subprocess.run(
                [
                    "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    f"-I{root / 'headless/src'}",
                    str(root / "cli/test/auto_ap_contract.cpp"), "-o", str(executable),
                ],
                check=True,
            )
            subprocess.run([str(executable)], check=True, timeout=10)
