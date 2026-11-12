"""真实本地任务页、资源和控件合同；请求边界替身不代替实际接交。"""

from pathlib import Path
import subprocess
import tempfile
import unittest

from test.img_fixture import write_img


QUEST_RESOURCE = {
    "QuestInfo.img": {
        "4321": {"name": "Resource quest", "0": "Before start", "1": "Current task log", "2": "Completed log"},
        "4322": {"name": "Unknown conditions", "0": "Known readable text", "1": "Known readable started text"},
        "4323": {"name": "Different job", "0": "Known text for another job"},
        "4324": {"name": "Missing body"},
        "4325": {"name": "Completion pages", "1": "Fallback progress", "2": "Finished"},
    },
    "Say.img": {
        "4321": {
            "0": {"0": "Start first", "1": "Start second", "yes": {"0": "Accepted text"}, "no": {"0": "Declined text"}}
        },
        "4325": {"1": {"0": "Finish first", "1": "Finish second"}},
    },
    "Check.img": {
        "4321": {
            "0": {"npc": 777, "job": {"0": 0}, "lvmin": 1, "lvmax": 10, "quest": {"0": {"id": 1230, "state": 2}}},
            "1": {"npc": 777, "item": {"0": {"id": 4000003, "count": 3}}, "mob": {"0": {"id": 130100, "count": 5}}},
        },
        "4322": {
            "0": {"npc": 777, "quest": {"0": {"id": 1230, "state": 2, "unsupported": 1}}},
            "1": {"npc": 777, "quest": {"0": {"id": 1230, "state": 2, "unsupported": 1}}},
        },
        "4323": {"0": {"npc": 777, "job": {"0": 100}}, "1": {"npc": 777}},
        "4324": {"0": {"npc": 777}, "1": {"npc": 777}},
        "4325": {"0": {"npc": 777}, "1": {"npc": 777, "item": {"0": {"id": 4000003, "count": 4}}}},
    },
    "Act.img": {
        "4321": {"0": {}, "1": {"exp": 150, "item": {"0": {"id": 4000003, "count": -3}}, "nextQuest": 4322}},
        "4322": {"0": {}, "1": {}},
        "4323": {"0": {}, "1": {}},
        "4324": {"0": {}, "1": {}},
        "4325": {"0": {}, "1": {}},
    },
}


class QuestInteractionContract(unittest.TestCase):
    def test_resource_pages_and_explicit_controls_wait_for_observed_task_state(self) -> None:
        root = Path(__file__).resolve().parents[2]
        engine = root / "third_party/maplestory-client"
        nx = engine / "includes/NoLifeNx/nlnx"
        with tempfile.TemporaryDirectory() as directory:
            parser_library = Path(directory) / "libbeidou-img.so"
            data = Path(directory) / "Data"
            for category in ("Character", "Effect", "Etc", "Item", "Map", "Mob", "Npc", "Reactor", "Skill", "String"):
                (data / category).mkdir(parents=True)
            for filename, properties in QUEST_RESOURCE.items():
                write_img(data / "Quest" / filename, properties)
            subprocess.run(
                [
                    "g++",
                    "-std=c++17",
                    "-O2",
                    "-fPIC",
                    "-shared",
                    str(root / "headless/src/ImgResources.cpp"),
                    str(root / "third_party/nolifewztonx/Keys.cpp"),
                    "-o",
                    str(parser_library),
                ],
                check=True,
                cwd=directory,
            )
            executable = Path(directory) / "quest-interaction-contract"
            subprocess.run(
                [
                    "g++",
                    "-std=c++20",
                    "-DHEADLESS",
                    "-DUSE_NX",
                    "-D_DEBUG",
                    "-DGLFW_INCLUDE_NONE",
                    "-ffunction-sections",
                    "-fdata-sections",
                    "-Wl,--gc-sections",
                    "-include",
                    str(root / "headless/src/PlatformIncludes.h"),
                    f"-I{engine}",
                    f"-I{engine / 'includes/NoLifeNx'}",
                    f"-I{root / 'headless/src'}",
                    f"-I{root / 'shared/lua-runtime'}",
                    str(root / "headless/src/ImgResourceFile.cpp"),
                    str(root / "headless/src/QuestInteraction.cpp"),
                    str(root / "headless/src/Interaction.cpp"),
                    str(engine / "Util/NxFiles.cpp"),
                    str(engine / "Character/QuestLog.cpp"),
                    str(engine / "includes/NoLifeNx/nlnx/nx.cpp"),
                    str(nx / "file.cpp"),
                    str(nx / "node.cpp"),
                    str(root / "cli/test/quest_interaction_contract.cpp"),
                    "-L",
                    directory,
                    "-Wl,-rpath,$ORIGIN",
                    "-lbeidou-img",
                    "-o",
                    str(executable),
                ],
                check=True,
                cwd=directory,
            )
            subprocess.run([str(executable), str(data)], check=True, cwd=directory, timeout=10)


if __name__ == "__main__":
    unittest.main()
