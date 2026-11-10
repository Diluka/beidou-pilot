"""真实本地任务页、资源和控件合同；请求边界替身不代替实际接交。"""

from pathlib import Path
import struct
import subprocess
import tempfile
import unittest


def _write_nx(path, tree):
    nodes = [("", tree)]
    entries = []
    strings = []
    ids = {}

    def string(value):
        if value not in ids:
            ids[value] = len(strings)
            strings.append(value)
        return ids[value]

    for name, value in nodes:
        name_id = string(name)
        child = len(nodes)
        if isinstance(value, dict):
            nodes.extend(sorted(value.items()))
            entries.append((name_id, child, len(value), 0, 0))
        elif isinstance(value, str):
            entries.append((name_id, child, 0, 3, string(value)))
        else:
            entries.append((name_id, child, 0, 1, value))
    node_table = b"".join(struct.pack("<IIHHq", *entry) for entry in entries)
    offsets = []
    content = bytearray()
    content_offset = 64 + len(node_table) + 8 * len(strings)
    for value in strings:
        encoded = value.encode()
        offsets.append(content_offset + len(content))
        content.extend(struct.pack("<H", len(encoded)) + encoded)
    end = content_offset + len(content)
    header = struct.pack("<IIQIQIQIQ", 0x34474B50, len(nodes), 64, len(strings), 64 + len(node_table), 0, end, 0, end)
    path.write_bytes(header.ljust(64, b"\0") + node_table + b"".join(struct.pack("<Q", n) for n in offsets) + content)


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
            resource = Path(directory) / "Quest.nx"
            _write_nx(resource, QUEST_RESOURCE)
            executable = Path(directory) / "quest-interaction-contract"
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
                    f"-I{root / 'headless/src'}",
                    f"-I{root / 'shared/lua-runtime'}",
                    str(root / "headless/src/QuestInteraction.cpp"),
                    str(root / "headless/src/Interaction.cpp"),
                    str(engine / "Character/QuestLog.cpp"),
                    str(nx / "file.cpp"),
                    str(nx / "node.cpp"),
                    str(root / "cli/test/quest_interaction_contract.cpp"),
                    "-o",
                    str(executable),
                ],
                check=True,
                cwd=directory,
            )
            subprocess.run([str(executable), str(resource)], check=True, cwd=directory, timeout=10)


if __name__ == "__main__":
    unittest.main()
