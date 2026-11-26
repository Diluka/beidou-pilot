"""bot_route 生成跨图航点表的离线合同。"""

import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools import bot_route


class BotRouteContract(unittest.TestCase):
    def test_route_legs_become_waypoints(self) -> None:
        response = {
            "ok": True,
            "data": {
                "status": "ok",
                "legs": [
                    {"from": 10000, "portal": "out00", "portal_at": [[1077, 480]], "to": 20000},
                    {"from": 20000, "portal": "out00", "portal_at": [[630, 210]], "to": 30000},
                ],
            },
        }
        with patch.object(
            bot_route.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")
        ):
            waypoints = bot_route.build_route(Path("/repo"), "dev/hero", 10000, 30000)
        self.assertEqual(
            [
                {"map": 10000, "portal": "out00", "x": 1077, "y": 480},
                {"map": 20000, "portal": "out00", "x": 630, "y": 210},
            ],
            waypoints,
        )

    def test_no_route_fails(self) -> None:
        response = {"ok": True, "data": {"status": "no_route", "error": "no_route", "legs": []}}
        with patch.object(
            bot_route.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(response), "")
        ):
            with self.assertRaises(bot_route.RouteError):
                bot_route.build_route(Path("/repo"), "dev/hero", 50000, 104040000)

    def test_invalid_json_fails(self) -> None:
        with patch.object(bot_route.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "not json", "")):
            with self.assertRaises(bot_route.RouteError):
                bot_route.build_route(Path("/repo"), "dev/hero", 1, 2)

    def test_workbench_must_have_partition(self) -> None:
        with self.assertRaises(SystemExit):
            bot_route.main(["hero", "1", "2"])


if __name__ == "__main__":
    unittest.main()
