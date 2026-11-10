"""真实近距门户信息与正常请求包合同；传输替身不代替实际转场。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class ScriptedPortalContract(unittest.TestCase):
    def test_scripted_portal_keeps_unknown_destination_and_sends_special_request(self) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "scripted-portal-contract"
            subprocess.run(
                [
                    "g++",
                    "-std=c++20",
                    "-DHEADLESS",
                    "-D_DEBUG",
                    "-DGLFW_INCLUDE_NONE",
                    "-ffunction-sections",
                    "-fdata-sections",
                    "-Wl,--gc-sections",
                    "-include",
                    str(root / "headless/src/PlatformIncludes.h"),
                    f"-I{engine}",
                    f"-I{root / 'headless/src'}",
                    f"-I{engine / 'includes/NoLifeNx'}",
                    f"-I{engine / 'includes/glfw-3.3.2.bin.WIN64/include/GLFW'}",
                    str(engine / "Gameplay/MapleMap/Portal.cpp"),
                    str(engine / "Net/OutPacket.cpp"),
                    str(engine / "Net/Encoding.cpp"),
                    str(engine / "Configuration.cpp"),
                    str(root / "headless/src/LoginState.cpp"),
                    str(root / "cli/test/scripted_portal_contract.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
                cwd=directory,
            )
            subprocess.run([str(executable)], check=True, cwd=directory, timeout=10)


if __name__ == "__main__":
    unittest.main()
