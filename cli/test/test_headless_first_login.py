"""无头首次登录和建角协议：离线夹具不代表实际游戏验收。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class HeadlessFirstLoginContract(unittest.TestCase):
    def test_protocol_and_bridge(self) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        src = root / "headless/src"
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "login-protocol-contract"
            subprocess.run([
                "g++", "-std=c++20", "-DHEADLESS", "-D_DEBUG", "-DGLFW_INCLUDE_NONE",
                "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                "-include", str(src / "PlatformIncludes.h"), f"-I{src}", f"-I{engine}",
                f"-I{engine / 'includes/NoLifeNx'}",
                f"-I{engine / 'includes/glfw-3.3.2.bin.WIN64/include/GLFW'}",
                f"-I{root / 'third_party/json/single_include'}",
                str(root / "cli/test/headless_login_protocol.cpp"),
                str(src / "LoginBridge.cpp"), str(src / "LoginState.cpp"), str(src / "HeadlessState.cpp"),
                str(engine / "Net/Handlers/LoginHandlers.cpp"),
                str(engine / "Net/Handlers/Helpers/LoginParser.cpp"),
                str(engine / "Net/InPacket.cpp"), str(engine / "Net/Encoding.cpp"),
                str(engine / "Configuration.cpp"), "-o", str(executable),
            ], check=True, cwd=directory)
            subprocess.run([str(executable)], check=True, cwd=directory, timeout=10)

    def test_login_state_reset(self) -> None:
        root = Path(__file__).resolve().parents[2]
        src = root / "headless/src"
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "login-state-contract"
            subprocess.run([
                "g++", "-std=c++20", "-include", str(src / "PlatformIncludes.h"),
                f"-I{src}", f"-I{root / 'third_party/maplestory-client'}",
                str(root / "cli/test/headless_login_state.cpp"), str(src / "LoginState.cpp"),
                "-o", str(executable),
            ], check=True, cwd=directory)
            subprocess.run([str(executable)], check=True, cwd=directory, timeout=10)
