"""真实频道公告解析合同；连接替身不代表实际登录成功。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class HeadlessChannelContract(unittest.TestCase):
    def test_loopback_uses_verified_target_and_preserves_announced_port(self) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "headless-login-contract"
            subprocess.run([
                "g++", "-std=c++20", "-DHEADLESS", "-D_DEBUG", "-DGLFW_INCLUDE_NONE",
                "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                "-include", str(root / "headless/src/PlatformIncludes.h"),
                f"-I{engine}", f"-I{engine / 'includes/NoLifeNx'}",
                f"-I{engine / 'includes/glfw-3.3.2.bin.WIN64/include/GLFW'}",
                str(engine / "Net/Handlers/Helpers/LoginParser.cpp"),
                str(engine / "Net/InPacket.cpp"), str(engine / "Configuration.cpp"),
                str(root / "cli/test/headless_login_contract.cpp"), "-o", str(executable),
            ], check=True, cwd=directory)
            subprocess.run([str(executable)], check=True, cwd=directory, timeout=10)


if __name__ == "__main__":
    unittest.main()
