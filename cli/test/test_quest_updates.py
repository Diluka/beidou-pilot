"""真实任务包解析与当前任务记录合同；不代替游戏内接交结果。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class QuestUpdatesContract(unittest.TestCase):
    def test_full_snapshot_and_live_status_changes_keep_current_quest_records(self) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "quest-updates-contract"
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
                    f"-I{engine / 'includes/NoLifeNx'}",
                    f"-I{engine / 'includes/glfw-3.3.2.bin.WIN64/include/GLFW'}",
                    str(engine / "Net/Handlers/Helpers/CharacterParser.cpp"),
                    str(engine / "Net/InPacket.cpp"),
                    str(engine / "Net/Encoding.cpp"),
                    str(engine / "Character/QuestLog.cpp"),
                    str(root / "cli/test/quest_updates_contract.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
                cwd=directory,
            )
            subprocess.run([str(executable)], check=True, cwd=directory, timeout=10)


if __name__ == "__main__":
    unittest.main()
