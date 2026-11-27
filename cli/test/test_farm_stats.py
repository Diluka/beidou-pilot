import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import mock_open, patch


SPEC = importlib.util.spec_from_file_location("farm_stats", Path(__file__).resolve().parents[2] / "tools" / "farm_stats.py")
farm_stats = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(farm_stats)


def row(**changes):
    result = {field: 0 for field in farm_stats.NUMBERS}
    result.update(map_id=1, platform=2, mob_template=3, complete=True, dwell_time=3600,
                  kills=10, exp=100, kill_time_sum=20, kill_time_samples=10,
                  drops_seen={"100": 3}, drops_picked={"100": 2})
    result.update(changes)
    return result


class FarmStatsTests(unittest.TestCase):
    def test_group_totals_rates_and_weighted_kill_time(self):
        data = {"schema": 1, "records": [row(), row(dwell_time=1800, exp=50, kills=5,
                 kill_time_sum=10, kill_time_samples=5, drops_picked={"200": 1})]}
        group = farm_stats.aggregate(data)["groups"][0]
        self.assertEqual(group["totals"]["drops_picked"], {"100": 2, "200": 1})
        self.assertAlmostEqual(group["rates_per_minute"]["exp"], 100 / 60)
        self.assertAlmostEqual(group["loot_per_minute"], 2 / 60)
        self.assertEqual(group["average_kill_time"], 2)

    def test_unknown_propagates_and_zero_is_not_unknown(self):
        data = {"schema": 1, "records": [row(exp=None, drops_picked={"100": None}), row()]}
        group = farm_stats.aggregate(data)["groups"][0]
        self.assertIsNone(group["totals"]["exp"])
        self.assertIsNone(group["loot_per_minute"])
        self.assertEqual(group["rates_per_minute"]["deaths"], 0)
        self.assertIsNone(farm_stats.aggregate(data, "exp")["groups"][0]["rates_per_minute"]["exp"])

    def test_zero_and_unknown_denominators(self):
        data = {"schema": 1, "records": [row(dwell_time=0, kill_time_samples=0),
                 row(map_id=None, platform=None, mob_template=None, dwell_time=None)]}
        groups = farm_stats.aggregate(data)["groups"]
        self.assertIsNone(groups[0]["average_kill_time"])
        self.assertIn("insufficient dwell_time", groups[0]["notes"])
        self.assertIn("insufficient kill time samples", groups[0]["notes"])
        self.assertIn("dwell_time unknown", groups[1]["notes"])

    def test_goal_labels_do_not_rank_or_change_groups(self):
        data = {"schema": 1, "records": [row(map_id=1, exp=100, drops_picked={"1": 1}),
                 row(map_id=2, exp=50, drops_picked={"1": 5}),
                 row(map_id=3, exp=None)]}
        results = [farm_stats.aggregate(data, goal) for goal in ("exp", "loot", "balance")]
        for result in results:
            self.assertNotIn("ranking", result)
            self.assertEqual([group["map_id"] for group in result["groups"]], [1, 2, 3])
            self.assertEqual(result["groups"], results[0]["groups"])

    def test_incomplete_windows_and_sample_thresholds(self):
        data = {"schema": 1, "records": [row(), row(complete=False, exp=10000, dwell_time=3600)]}
        group = farm_stats.aggregate(data)["groups"][0]
        self.assertEqual(group["totals"]["exp"], 10100)
        self.assertAlmostEqual(group["rates_per_minute"]["exp"], 100 / 60)
        self.assertEqual(group["sample_windows"], 1)
        self.assertIn("incomplete or unknown windows excluded from rates", group["notes"])
        for changes in ({"kills": 4}, {"dwell_time": 59}, {"complete": None}):
            group = farm_stats.aggregate({"schema": 1, "records": [row(**changes)]})["groups"][0]
            self.assertTrue(group["insufficient"])
            self.assertIsNone(group["rates_per_minute"]["exp"])

    def test_invalid_schema_and_measurements(self):
        for document in ({"schema": True, "records": []}, {"schema": 2, "records": []},
                         {"schema": 1, "records": [row(kills=-1)]},
                         {"schema": 1, "records": [row(exp=float("nan"))]},
                         {"schema": 1, "records": [row(drops_seen=[])]}):
            with self.subTest(document=document), self.assertRaises(ValueError):
                farm_stats.aggregate(document)

    def test_cli_json_and_text(self):
        content = json.dumps({"schema": 1, "records": [row()]})
        for args in (["metrics.json", "--json", "--goal", "exp"], ["metrics.json"]):
            output = io.StringIO()
            with patch("pathlib.Path.open", mock_open(read_data=content)), contextlib.redirect_stdout(output):
                farm_stats.main(args)
            if "--json" in args:
                result = json.loads(output.getvalue())
                self.assertEqual(result["goal"], "exp")
                self.assertEqual(len(result["groups"]), 1)
                self.assertNotIn("ranking", result)
            else:
                self.assertIn("exp/minute: 1.666", output.getvalue())

    def test_role_resolution_and_traversal(self):
        self.assertEqual(farm_stats.input_path("dev/test-role").parts[-5:],
                         ("workbenches", "dev", "test-role", "bot", "metrics.json"))
        for name in ("dev/..", "dev/a/b", "dev/a\\b", "dev/"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                farm_stats.input_path(name)
        self.assertEqual(farm_stats.input_path("metrics.json"), Path("metrics.json"))


if __name__ == "__main__":
    unittest.main()
