"""safe_platforms 的安全判定与保守移动模型离线合同。"""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from tools import safe_platforms


def foothold(
    foothold_id: int, x1: int, x2: int, y1: int, y2: int | None = None, previous: int = 0, next_id: int = 0
) -> dict[str, int]:
    return {
        "id": foothold_id,
        "x1": x1,
        "x2": x2,
        "y1": y1,
        "y2": y1 if y2 is None else y2,
        "prev": previous,
        "next": next_id,
    }


def monster(monster_id: int, x: int, y: int, foothold_id: int) -> dict[str, object]:
    return {"id": monster_id, "name": "测试怪", "x": x, "y": y, "fh": foothold_id, "type": "m"}


def map_data(
    *footholds: dict[str, int],
    monsters: list[dict[str, object]] | None = None,
    ropes: list[dict[str, int]] | None = None,
) -> dict[str, object]:
    return {
        "id": 10000,
        "name": "测试地图",
        "footholds": list(footholds),
        "monsters": monsters or [],
        "ropes": ropes or [],
    }


def scene(x: int, y: int, monsters: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {"map_id": 10000, "player": {"x": x, "y": y}, "monsters": monsters or []}


def analyze(
    data: dict[str, object],
    character: dict[str, object],
    model: safe_platforms.Model | None = None,
    monsters: list[dict[str, object]] | None = None,
):
    return safe_platforms.analyze(
        scene(character["x"], character["y"], monsters), data, model or safe_platforms.Model()
    )


def platforms_by_id(result: dict[str, object]) -> dict[int, dict[str, object]]:
    return {item["platform"]: item for item in result["platforms"]}


def excluded_by_id(result: dict[str, object]) -> dict[int, dict[str, object]]:
    return {item["platform"]: item for item in result["excluded_platforms"]}


class SafePlatformAnalysisContract(unittest.TestCase):
    def test_spawn_platform_is_unsafe(self) -> None:
        data = map_data(
            foothold(1, 0, 100, 100),
            foothold(2, 300, 400, 100),
            monsters=[monster(100, 50, 70, 1)],
        )
        result = analyze(data, {"x": 350, "y": 100})
        excluded = excluded_by_id(result)
        self.assertIn("spawn", excluded[1]["reasons"])
        self.assertEqual([2], [item["platform"] for item in result["safe_platforms"]])
        self.assertEqual(50, excluded[1]["spawn_monsters"][0]["x"])

    def test_monster_drop_marks_lower_platform_unsafe(self) -> None:
        data = map_data(
            foothold(1, 0, 100, 100),
            foothold(2, 0, 100, 200),
            foothold(3, 200, 300, 200),
            monsters=[monster(100, 50, 70, 1)],
        )
        result = analyze(data, {"x": 250, "y": 200})
        excluded = excluded_by_id(result)
        self.assertIn("monster_reachable", excluded[2]["reasons"])
        self.assertEqual([1], excluded[2]["monster_sources"])
        self.assertIn("spawn", excluded[1]["reasons"])
        self.assertEqual([3], [item["platform"] for item in result["safe_platforms"]])

    def test_current_scene_monster_makes_platform_unsafe(self) -> None:
        data = map_data(
            foothold(1, 0, 100, 100),
            foothold(2, 300, 400, 100),
        )
        result = analyze(data, {"x": 350, "y": 100}, monsters=[{"id": 100, "name": "当前怪", "x": 50, "y": 70}])
        self.assertIn("spawn", excluded_by_id(result)[1]["reasons"])
        self.assertEqual("scene", excluded_by_id(result)[1]["spawn_monsters"][0]["source"])

    def test_monster_drops_off_narrow_overlap(self) -> None:
        data = map_data(
            foothold(1, 0, 100, 100),
            foothold(2, 95, 200, 200),
            monsters=[monster(100, 50, 70, 1)],
        )
        result = analyze(data, {"x": 150, "y": 200})
        self.assertIn("monster_reachable", excluded_by_id(result)[2]["reasons"])
        self.assertEqual([], result["safe_platforms"])

    def test_safe_platform_has_no_spawn_and_monster_cannot_reach(self) -> None:
        data = map_data(
            foothold(1, 0, 100, 100),
            foothold(2, 200, 300, 100),
            monsters=[monster(100, 50, 70, 1)],
        )
        result = analyze(data, {"x": 250, "y": 100})
        self.assertEqual([2], [item["platform"] for item in result["safe_platforms"]])
        self.assertEqual(2, result["recommended_platform"])
        self.assertEqual(0, result["safe_platforms"][0]["path"]["length"])

    def test_player_unreachable_platform_is_excluded(self) -> None:
        data = map_data(
            foothold(1, 0, 100, 100),
            foothold(2, 0, 100, 200),
            foothold(3, 1000, 1100, 200),
            monsters=[monster(100, 50, 70, 1)],
        )
        result = analyze(data, {"x": 50, "y": 200})
        excluded = excluded_by_id(result)
        self.assertEqual(["player_unreachable"], excluded[3]["reasons"])
        self.assertFalse(excluded[3]["player_reachable"])
        self.assertEqual([], result["safe_platforms"])

    def test_player_jumpup_reaches_higher_platform_that_monsters_cannot(self) -> None:
        data = map_data(
            foothold(1, 0, 200, 300),
            foothold(2, 250, 350, 250),
            monsters=[monster(100, 100, 270, 1)],
        )
        result = analyze(data, {"x": 100, "y": 300})
        self.assertEqual([2], [item["platform"] for item in result["safe_platforms"]])
        edges = result["safe_platforms"][0]["path"]["edges"]
        self.assertEqual(["jumpup"], [edge["kind"] for edge in edges])
        self.assertEqual(1, edges[0]["from"])
        self.assertEqual(2, edges[0]["to"])

    def test_rope_is_usable_by_player_but_not_monsters(self) -> None:
        data = map_data(
            foothold(1, 0, 200, 300),
            foothold(2, 0, 200, 100),
            monsters=[monster(100, 100, 270, 1)],
            ropes=[{"index": 1, "x": 100, "y1": 100, "y2": 300}],
        )
        result = analyze(data, {"x": 50, "y": 300})
        self.assertEqual([2], [item["platform"] for item in result["safe_platforms"]])
        edges = result["safe_platforms"][0]["path"]["edges"]
        self.assertEqual(["rope"], [edge["kind"] for edge in edges])
        self.assertEqual(-200, edges[0]["rise"])

    def test_sloped_foothold_chain_is_one_platform(self) -> None:
        data = map_data(
            foothold(5, 0, 100, 300, 250, next_id=7),
            foothold(7, 100, 200, 250, 200, previous=5),
        )
        result = analyze(data, {"x": 100, "y": 250})
        platforms = platforms_by_id(result)
        self.assertEqual(1, len(platforms))
        platform = platforms[1]
        self.assertEqual(0, platform["left"])
        self.assertEqual(200, platform["right"])
        self.assertEqual(250, platform["y"])

    def test_spawn_without_platform_falls_to_platform_below(self) -> None:
        data = map_data(
            foothold(1, 0, 100, 200),
            monsters=[monster(100, 50, 100, 999)],
        )
        result = analyze(data, {"x": 50, "y": 200})
        excluded = excluded_by_id(result)
        self.assertEqual(100, excluded[1]["spawn_monsters"][0]["monster_id"])
        self.assertEqual("below", result["monster_spawns"][0]["located_by"])

    def test_unlocated_spawn_fails_safe(self) -> None:
        data = map_data(
            foothold(1, 0, 100, 200),
            monsters=[{"id": 100, "name": "无坐标", "type": "m"}],
        )
        result = analyze(data, {"x": 50, "y": 200})
        self.assertEqual([], result["safe_platforms"])
        self.assertIn("monster_unlocated", excluded_by_id(result)[1]["reasons"])

    def test_character_platform_unknown_is_rejected(self) -> None:
        data = map_data(foothold(1, 0, 100, 200))
        with self.assertRaises(safe_platforms.SafePlatformError):
            analyze(data, {"x": 50, "y": -500})

    def test_cli_reads_scene_and_map_and_emits_json(self) -> None:
        data = map_data(
            foothold(1, 0, 100, 100),
            foothold(2, 200, 300, 100),
            monsters=[monster(100, 50, 70, 1)],
        )
        scene_response = {"ok": True, "data": {"map_id": 10000, "player": {"x": 250, "y": 100}}}
        map_response = {"ok": True, "data": data}
        calls: list[list[str]] = []

        def fake_run(command, **_kwargs):
            calls.append(command)
            response = scene_response if command[-1] == "scene" else map_response
            return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

        output = io.StringIO()
        with patch.object(safe_platforms.subprocess, "run", side_effect=fake_run):
            with redirect_stdout(output):
                exit_code = safe_platforms.main(["dev/hero", "--json"])
        self.assertEqual(0, exit_code)
        payload = json.loads(output.getvalue())
        self.assertEqual(10000, payload["map_id"])
        self.assertEqual(2, len(calls))
        self.assertTrue(calls[0][-1] == "scene")
        self.assertEqual(["inspect", "map", "10000"], calls[1][-3:])

    def test_workbench_failure_is_reported(self) -> None:
        response = {"ok": False, "error": {"code": "client_not_running", "message": "没有运行中的客户端"}}
        with patch.object(
            safe_platforms.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""),
        ):
            with self.assertRaises(safe_platforms.SafePlatformError):
                safe_platforms.read_scene(Path("/repo"), "dev/hero")

    def test_workbench_argument_requires_partition(self) -> None:
        with self.assertRaises(SystemExit):
            safe_platforms.main(["hero"])


if __name__ == "__main__":
    unittest.main()
