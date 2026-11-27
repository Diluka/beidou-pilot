"""bot_quest 任务目标打怪的离线合同。"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import bot_quest


class BotQuestContract(unittest.TestCase):
    def test_write_conf_contains_objectives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(bot_quest, "REPO_ROOT", root):
                path = bot_quest.write_conf("dev/hero", 1037, [100100, 100101], 10, 2010002, 120)
                text = path.read_text()
        self.assertIn("quest_id = 1037", text)
        self.assertIn("mob_ids = {100100, 100101}", text)
        self.assertIn("count = 10", text)
        self.assertIn("heal_item = 2010002", text)

    def test_progress_reads_started_record(self) -> None:
        response = {
            "ok": True,
            "data": {
                "quests": [
                    {"quest_id": 1037, "state": "started", "progress": "003"},
                    {"quest_id": 1036, "state": "completed", "progress": None},
                ]
            },
        }
        with patch.object(bot_quest, "inspect_quests", return_value=response["data"]["quests"]):
            self.assertEqual("started", bot_quest.quest_progress("dev/hero", 1037)["state"])
            self.assertEqual("003", bot_quest.quest_progress("dev/hero", 1037)["progress"])
            self.assertEqual("not_in_client_records", bot_quest.quest_progress("dev/hero", 1)["state"])

    def test_objectives_reports_errors_per_quest(self) -> None:
        quests = [{"quest_id": 1037, "state": "started", "progress": "002"}]
        with (
            patch.object(bot_quest, "inspect_quests", return_value=quests),
            patch.object(bot_quest, "QuestImages"),
            patch.object(
                bot_quest,
                "quest_definition",
                return_value={
                    "quest_id": 1037,
                    "name": "帮助打猎蜗牛",
                    "objectives": [{"mob_id": 100100, "count": 10}],
                    "npc_ids": [2005, 2103],
                    "exp": 60,
                },
            ),
        ):
            with patch("sys.stdout.write") as write:
                code = bot_quest.main(["--quest-directory", "/tmp", "objectives", "dev/hero"])
        self.assertEqual(0, code)
        printed = "".join(call.args[0] for call in write.call_args_list)
        self.assertIn("100100", printed)
        self.assertIn("2005", printed)

    def test_hunt_rejects_quest_without_objectives(self) -> None:
        with (
            patch.object(bot_quest, "QuestImages"),
            patch.object(bot_quest, "quest_definition", return_value={"quest_id": 1, "objectives": []}),
        ):
            self.assertEqual(1, bot_quest.main(["--quest-directory", "/tmp", "hunt", "dev/hero", "1"]))

    def test_workbench_name_requires_partition(self) -> None:
        with self.assertRaises(bot_quest.QuestToolError):
            bot_quest.role_directory("hero")


if __name__ == "__main__":
    unittest.main()
