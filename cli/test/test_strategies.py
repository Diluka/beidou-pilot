"""Lua 策略的 CLI 声明、上下文和原生执行入口合同。"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.bridge import BridgeClient
from beidou_pilot.cli import main
from beidou_pilot.errors import ClientError
from beidou_pilot.strategies import parse_options, parse_strategy
from beidou_pilot.strategy_scene import scene_context
from .test_bridge import BridgeFiles


POLICY = """--- 示例策略入口。
-- @option[type=int,min=1,max=100] mob_id 目标怪物模板 ID
-- @option[type=int,opt,default=1001005] skill_id 可选技能 ID
-- @option[type=number,opt,default=0.5,min=0,max=1] health_ratio 停止阈值
-- @option[type=string,opt,choices=near|far] range_mode 目标范围
-- @option[type=boolean,opt,default=false] cautious 仅观察模式
local function main(context)
    game.log(tostring(context.options.mob_id))
end
"""


class LuaStrategyContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = BridgeFiles(Path(temporary.name))
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.path = self.files.root / "strategy.lua"
        self.path.write_text(POLICY, encoding="utf-8")
        self.scene = {
            "map_id": self.files.state["map_id"],
            "scene_generation": self.files.state["scene_generation"],
            "terrain": {
                "status": "available",
                "source": "/client/Map.wz/Map/Map0/000000100.img.xml",
                "footholds": [{"id": 1, "x1": 0, "x2": 10, "y1": 20, "y2": 20, "prev": 0, "next": 0}],
                "ropes": [{"index": 0, "x": 5, "y1": 0, "y2": 20}],
            },
        }

    def cli(self, *arguments: str) -> tuple[int, str]:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--json", "--root", str(self.files.root), *arguments])
        return result, output.getvalue()

    def test_run_and_start_parse_distinct_dynamic_options_into_main_context(self) -> None:
        cases = (
            (
                "run",
                ["--mob-id", "12", "--skill-id", "200", "--health-ratio", "0.75", "--range-mode", "near", "--cautious"],
                (
                    '["mob_id"]=12',
                    '["skill_id"]=200',
                    '["health_ratio"]=0.75',
                    '["range_mode"]="near"',
                    '["cautious"]=true',
                ),
                False,
            ),
            (
                "start",
                ["--mob-id=34"],
                ('["mob_id"]=34', '["skill_id"]=1001005', '["health_ratio"]=0.5', '["cautious"]=false'),
                True,
            ),
        )
        for action, options, expected, asynchronous in cases:
            with (
                self.subTest(action=action),
                patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                patch(
                    "beidou_pilot.strategy_scene.load_hunt_terrain",
                    return_value={
                        **self.scene["terrain"],
                        "map_id": 100,
                    },
                ),
                patch.object(BridgeClient, "run_script", return_value={"status": "accepted"}) as run,
            ):
                code, output = self.cli("script", action, str(self.path), *options)
            self.assertEqual(0, code, output)
            source = run.call_args.kwargs["code"]
            for option in expected:
                self.assertIn(option, source)
            if action == "start":
                self.assertNotIn('["range_mode"]', source)
            self.assertIn('["scene_generation"]=1', source)
            self.assertIn("strategy_scene_context_stale", source)
            self.assertTrue(source.endswith("return main(__beidou_context)\nend\n"))
            self.assertEqual(asynchronous, run.call_args.kwargs["wait_for_start"])
            report = json.loads(output)["data"]
            self.assertEqual(str(self.path), report["script_file"])
            self.assertEqual("main(context)", report["policy_entry"])

    def test_describe_generates_option_help_from_lua_comments(self) -> None:
        with patch("beidou_pilot.cli.Backend") as backend:
            code, output = self.cli("script", "describe", str(self.path))
        self.assertEqual(0, code, output)
        backend.assert_not_called()
        data = json.loads(output)["data"]
        self.assertEqual("main(context)", data["entry"])
        self.assertIn("--mob-id <int>", data["usage"])
        self.assertTrue(data["options"][0]["required"])
        self.assertEqual(1001005, data["options"][1]["default"])
        self.assertEqual(["near", "far"], data["options"][3]["choices"])
        self.assertIn("[--cautious|--no-cautious]", data["usage"])

    def test_boolean_negation_is_a_valueless_false_flag(self) -> None:
        metadata = parse_strategy(
            "-- @option[type=boolean,opt,default=true] enabled 启用策略\nlocal function main(context)\nend\n"
        )
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual({"enabled": False}, parse_options(metadata, ["--no-enabled"]))
        for arguments in (("--no-enabled=false",), ("--no-enabled", "false")):
            with self.subTest(arguments=arguments), self.assertRaises(ClientError) as raised:
                parse_options(metadata, list(arguments))
            self.assertEqual("invalid_strategy_option", raised.exception.code)

    def test_required_boolean_help_matches_supported_flag_forms(self) -> None:
        self.path.write_text(
            "-- @option[type=boolean] enabled 启用策略\nlocal function main(context)\nend\n", encoding="utf-8"
        )
        code, output = self.cli("script", "describe", str(self.path))
        self.assertEqual(0, code, output)
        data = json.loads(output)["data"]
        self.assertIn("--enabled|--no-enabled", data["usage"])
        metadata = parse_strategy(self.path.read_text(encoding="utf-8"))
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual({"enabled": True}, parse_options(metadata, ["--enabled"]))
        self.assertEqual({"enabled": False}, parse_options(metadata, ["--no-enabled"]))

    def test_policy_flag_is_not_abbreviated_as_a_cli_control_flag(self) -> None:
        self.path.write_text(
            "-- @option[type=boolean,opt,default=false] continuity 持续状态\nlocal function main(context)\nend\n",
            encoding="utf-8",
        )
        with (
            patch.object(BridgeClient, "snapshot", return_value=self.files.state),
            patch(
                "beidou_pilot.strategy_scene.load_hunt_terrain",
                return_value={**self.scene["terrain"], "map_id": 100},
            ),
            patch.object(BridgeClient, "run_script", return_value={"status": "completed"}) as run,
        ):
            code, output = self.cli("script", "run", str(self.path), "--continuity")
        self.assertEqual(0, code, output)
        self.assertEqual(30, run.call_args.kwargs["seconds"])
        self.assertIn('["continuity"]=true', run.call_args.kwargs["code"])

    def test_cli_reserved_flags_are_rejected_in_metadata(self) -> None:
        with self.assertRaises(ClientError) as raised:
            parse_strategy("-- @option[type=string] help 覆盖帮助参数\nlocal function main(context)\nend\n")
        self.assertEqual("invalid_strategy_metadata", raised.exception.code)

    def test_multiple_main_entries_are_rejected_as_ambiguous_metadata(self) -> None:
        with self.assertRaises(ClientError) as raised:
            parse_strategy("local function main(context)\nend\nlocal function main(context)\nend\n")
        self.assertEqual("invalid_strategy_metadata", raised.exception.code)

    def test_invalid_metadata_or_option_is_rejected_before_runtime_or_script_dispatch(self) -> None:
        self.path.write_text(
            "-- @option[unknown=x] mob_id invalid\nlocal function main(context)\nend\n", encoding="utf-8"
        )
        for arguments, expected in (
            (("--mob-id", "12"), "invalid_strategy_metadata"),
            (("--unknown", "12"), "invalid_strategy_metadata"),
        ):
            with (
                self.subTest(arguments=arguments),
                patch("beidou_pilot.cli.Backend", wraps=Backend) as backend,
                patch.object(BridgeClient, "run_script") as run,
            ):
                code, output = self.cli("script", "start", str(self.path), *arguments)
            self.assertEqual(2, code)
            self.assertEqual(expected, json.loads(output)["error"]["code"])
            backend.assert_not_called()
            run.assert_not_called()

        self.path.write_text(POLICY, encoding="utf-8")
        with (
            patch("beidou_pilot.cli.Backend", wraps=Backend) as backend,
            patch.object(BridgeClient, "run_script") as run,
        ):
            code, output = self.cli("script", "run", str(self.path), "--mob-id", "0")
        self.assertEqual(2, code)
        self.assertEqual("invalid_strategy_option", json.loads(output)["error"]["code"])
        backend.assert_not_called()
        run.assert_not_called()

        with (
            patch("beidou_pilot.cli.Backend", wraps=Backend) as backend,
            patch.object(BridgeClient, "run_script") as run,
        ):
            code, output = self.cli("script", "run", str(self.path), "--mob-id", "12", "--range-mode", "anywhere")
        self.assertEqual(2, code)
        self.assertEqual("invalid_strategy_option", json.loads(output)["error"]["code"])
        backend.assert_not_called()
        run.assert_not_called()

    def test_raw_file_and_code_are_not_wrapped_as_strategies(self) -> None:
        raw_file = self.files.root / "raw.lua"
        raw_source = "game.log('raw file')\r\n"
        raw_file.write_bytes(raw_source.encode("utf-8"))
        raw_code = "-- @option[type=int] x raw\nlocal function main(context) game.log('raw code') end"
        for source_args, expected, script_file in (
            ((str(raw_file),), raw_source, str(raw_file)),
            (("--code", raw_code), raw_code, None),
        ):
            with (
                self.subTest(source_args=source_args),
                patch.object(BridgeClient, "run_script", return_value={"status": "completed"}) as run,
            ):
                code, output = self.cli("script", "run", *source_args)
            self.assertEqual(0, code, output)
            self.assertEqual(expected, run.call_args.kwargs["code"])
            self.assertNotIn("main(__beidou_context)", run.call_args.kwargs["code"])
            self.assertEqual(script_file, json.loads(output)["data"].get("script_file"))

    def test_scene_context_keeps_catalog_source_and_reports_missing_terrain(self) -> None:
        terrain = self.scene["terrain"]
        catalog_result = terrain | {"map_id": 100}
        with patch("beidou_pilot.strategy_scene.load_hunt_terrain", return_value=catalog_result):
            available = scene_context(self.files.root, self.files.state)
        self.assertEqual(1, available["scene_generation"])
        self.assertEqual(terrain["source"], available["terrain"]["source"])
        self.assertEqual(1, len(available["terrain"]["footholds"]))
        self.assertEqual(1, len(available["terrain"]["ropes"]))

        for code, status in (("hunt_terrain_unavailable", "unavailable"), ("hunt_terrain_unsupported", "unsupported")):
            with (
                self.subTest(code=code),
                patch(
                    "beidou_pilot.strategy_scene.load_hunt_terrain",
                    side_effect=ClientError(code, "当前地图没有可用的地形。", {"map_id": 100}),
                ),
            ):
                unavailable = scene_context(self.files.root, self.files.state)
            terrain_context = unavailable["terrain"]
            self.assertEqual(status, terrain_context["status"])
            self.assertEqual(code, terrain_context["error"])
            self.assertNotIn("footholds", terrain_context)
            self.assertNotIn("ropes", terrain_context)


if __name__ == "__main__":
    unittest.main()
