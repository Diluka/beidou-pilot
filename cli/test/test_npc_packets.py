"""真实 NPC 接收及正常请求包合同；传输替身不证明任务游戏效果。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class NpcPacketsContract(unittest.TestCase):
    def test_received_pages_and_explicit_npc_quest_requests_keep_protocol_meaning(self) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "npc-packets-contract"
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
                    f"-I{root / 'shared/lua-runtime'}",
                    f"-I{engine / 'includes/NoLifeNx'}",
                    f"-I{engine / 'includes/glfw-3.3.2.bin.WIN64/include/GLFW'}",
                    str(engine / "Net/Handlers/NpcInteractionHandlers.cpp"),
                    str(engine / "Net/InPacket.cpp"),
                    str(engine / "Net/Encoding.cpp"),
                    str(engine / "Net/OutPacket.cpp"),
                    str(engine / "Configuration.cpp"),
                    str(engine / "IO/Keyboard.cpp"),
                    str(root / "headless/src/HeadlessState.cpp"),
                    str(root / "headless/src/Interaction.cpp"),
                    str(root / "headless/src/LoginState.cpp"),
                    str(root / "cli/test/npc_packets_contract.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
                cwd=directory,
            )
            subprocess.run([str(executable)], check=True, cwd=directory, timeout=10)


if __name__ == "__main__":
    unittest.main()
