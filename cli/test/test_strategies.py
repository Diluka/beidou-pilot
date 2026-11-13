"""Lua 策略的 CLI 声明、上下文和原生执行入口合同。"""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from beidou_pilot.backend import Backend
from beidou_pilot.bridge import BridgeClient
from beidou_pilot.cli import main
from beidou_pilot.control_scripts import run_strategy
from beidou_pilot.errors import ClientError
from beidou_pilot.strategies import (
    compile_strategy,
    parse_options,
    parse_script_execution,
    parse_strategy,
    read_strategy_file,
)
from beidou_pilot.script_libraries import with_library
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
            "instance_id": self.files.state["instance_id"],
            "character_id": self.files.state["character"]["id"],
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
        self.assertFalse(data["options"][4]["default"])
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

    def test_boolean_without_explicit_default_is_optional_true(self) -> None:
        self.path.write_text(
            "-- @option[type=boolean] enabled 启用策略\nlocal function main(context)\nend\n", encoding="utf-8"
        )
        code, output = self.cli("script", "describe", str(self.path))
        self.assertEqual(0, code, output)
        data = json.loads(output)["data"]
        self.assertIn("[--enabled|--no-enabled]", data["usage"])
        self.assertEqual(False, data["options"][0]["required"])
        self.assertTrue(data["options"][0]["default"])
        metadata = parse_strategy(self.path.read_text(encoding="utf-8"))
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual({"enabled": True}, parse_options(metadata, []))
        self.assertEqual({"enabled": True}, parse_options(metadata, ["--enabled"]))
        self.assertEqual({"enabled": False}, parse_options(metadata, ["--no-enabled"]))

    def test_boolean_without_explicit_default_is_passed_to_entry(self) -> None:
        self.path.write_text(
            "-- @option[type=boolean] enabled 启用策略\nlocal function main(context)\nend\n", encoding="utf-8"
        )
        for arguments, expected in (((), "true"), (("--enabled",), "true"), (("--no-enabled",), "false")):
            with (
                self.subTest(arguments=arguments),
                patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                patch(
                    "beidou_pilot.strategy_scene.load_hunt_terrain",
                    return_value={**self.scene["terrain"], "map_id": 100},
                ),
                patch.object(BridgeClient, "run_script", return_value={"status": "completed"}) as run,
            ):
                code, output = self.cli("script", "run", str(self.path), *arguments)
            self.assertEqual(0, code, output)
            self.assertIn(f'["enabled"]={expected}', run.call_args.kwargs["code"])

    def test_boolean_inputs_obey_choices_before_script_dispatch(self) -> None:
        source = "-- @option[type=boolean,choices=true] enabled 启用策略\nlocal function main(context)\nend\n"
        metadata = parse_strategy(source)
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual({"enabled": True}, parse_options(metadata, ["--enabled"]))
        self.assertEqual({"enabled": False}, parse_options(metadata, ["--no-enabled"]))
        with self.assertRaises(ClientError) as raised:
            parse_options(metadata, ["--enabled", "false"])
        self.assertEqual("invalid_strategy_option", raised.exception.code)
        with self.assertRaises(ClientError) as raised:
            parse_strategy(
                "-- @option[type=boolean,choices=false] enabled 仅允许关闭\nlocal function main(context)\nend\n"
            )
        self.assertEqual("invalid_strategy_metadata", raised.exception.code)

        self.path.write_text(source, encoding="utf-8")
        with (
            patch("beidou_pilot.cli.Backend", wraps=Backend) as backend,
            patch.object(BridgeClient, "run_script") as run,
        ):
            code, output = self.cli("script", "run", str(self.path), "--enabled", "false")
        self.assertEqual(2, code)
        self.assertEqual("invalid_strategy_option", json.loads(output)["error"]["code"])
        backend.assert_not_called()
        run.assert_not_called()

    def test_explicit_false_boolean_default_is_preserved(self) -> None:
        metadata = parse_strategy(
            "-- @option[type=boolean,default=false] enabled 启用策略\nlocal function main(context)\nend\n"
        )
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual({"enabled": False}, parse_options(metadata, []))
        self.assertEqual({"enabled": True}, parse_options(metadata, ["--enabled"]))
        self.assertEqual({"enabled": False}, parse_options(metadata, ["--no-enabled"]))

    def test_explicit_false_default_can_match_false_only_choices(self) -> None:
        metadata = parse_strategy(
            "-- @option[type=boolean,default=false,choices=false] disabled 默认关闭\n"
            "local function main(context)\nend\n"
        )
        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual({"disabled": False}, parse_options(metadata, []))
        self.assertEqual({"disabled": False}, parse_options(metadata, ["--no-disabled"]))
        with self.assertRaises(ClientError) as raised:
            parse_options(metadata, ["--disabled"])
        self.assertEqual("invalid_strategy_option", raised.exception.code)

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

    def test_python_strategy_adapter_uses_declared_options_and_rejects_unknown_fields(self) -> None:
        backend = Mock(spec=Backend)
        backend.root, backend.name, backend.instance = self.files.root, "headless", "default"
        with (
            patch("beidou_pilot.control_scripts.scene_context", return_value=self.scene),
            patch("beidou_pilot.control_scripts.run_source", return_value={"status": "completed"}) as run,
        ):
            run_strategy(backend, "travel/move_to", {"x": 10}, 21, context_state=self.files.state)
        source = run.call_args.args[1]
        self.assertIn('["x"]=10', source)
        self.assertIn("return main(__beidou_context)", source)
        self.assertEqual(21, run.call_args.args[2])

        with patch("beidou_pilot.control_scripts.run_source") as unpublished:
            with self.assertRaises(ClientError) as raised:
                run_strategy(
                    backend, "travel/move_to", {"x": 10, "not_declared": True}, 21, context_state=self.files.state
                )
        self.assertEqual("invalid_strategy_option", raised.exception.code)
        unpublished.assert_not_called()

        with (
            patch("beidou_pilot.control_scripts.scene_context") as scene,
            patch("beidou_pilot.control_scripts.run_source") as unpublished,
        ):
            with self.assertRaises(ClientError) as raised:
                run_strategy(
                    backend,
                    "travel/climb_to",
                    {"x": 10, "y": 20, "direction": 1},
                    21,
                    context_state=self.files.state,
                )
        self.assertEqual("invalid_strategy_option", raised.exception.code)
        scene.assert_not_called()
        unpublished.assert_not_called()

    def test_builtin_policies_declare_main_and_travel_helpers_are_loaded(self) -> None:
        scripts = Path(__file__).resolve().parents[2] / "shared/scripts"
        for relative in (
            "travel/move_to.lua",
            "travel/climb_to.lua",
            "travel/enter_portal.lua",
            "combat/hunt.lua",
            "recovery/recover.lua",
        ):
            with self.subTest(script=relative):
                source, metadata = read_strategy_file(scripts / relative)
                self.assertIsNotNone(metadata)
                self.assertIn("local function main(context)", source)
        travel_source, travel_metadata = read_strategy_file(scripts / "travel/move_to.lua")
        self.assertIsNotNone(travel_metadata)
        self.assertIn("local function travel_initial(context, min_hp_ratio, fail)", travel_source)
        self.assertEqual(
            {"budget_seconds": 20.0, "tolerance": 8, "y_tolerance": 45, "min_hp_ratio": 0.0, "x": 10},
            parse_options(travel_metadata, ["--x", "10"]),
        )
        _, recovery_metadata = read_strategy_file(scripts / "recovery/recover.lua")
        assert recovery_metadata is not None
        recovery_options = parse_options(recovery_metadata, ["--item-id", "2000000", "--budget-seconds", "5"])
        self.assertEqual(
            {"heals_hp": False, "heals_mp": False, "healing_known": False, "consume_only": False},
            {name: recovery_options[name] for name in ("heals_hp", "heals_mp", "healing_known", "consume_only")},
        )

    def test_tick_metadata_defaults_and_description_are_visible_without_a_client(self) -> None:
        self.path.write_text("-- @mode tick\n" + POLICY, encoding="utf-8")
        with patch("beidou_pilot.cli.Backend") as backend:
            code, output = self.cli("script", "describe", str(self.path))
        self.assertEqual(0, code, output)
        backend.assert_not_called()
        data = json.loads(output)["data"]
        self.assertEqual("tick", data["mode"])
        self.assertEqual({"budget_ms": 100, "overrun": "abort", "abort_commit": True}, data["tick"])
        self.assertEqual("coroutine", parse_script_execution(POLICY).mode)
        self.assertEqual("coroutine", parse_script_execution("-- @mode coroutine\n" + POLICY).mode)
        for budget, expected in ((".5", 0.5), ("1.", 1), ("0002.5", 2.5)):
            with self.subTest(budget=budget):
                execution = parse_script_execution("-- @mode tick--说明\n-- @tick.budget_ms " + budget + "\n")
                self.assertEqual(("tick", expected), (execution.mode, execution.budget_ms))

    def test_tick_compile_returns_entry_and_context_without_old_state_or_calling_main(self) -> None:
        header = (
            "-- @mode tick\n-- @tick.budget_ms 12.5\n-- @tick.overrun skip -- 分片执行\n-- @tick.abort_commit false\n"
        )
        source = header + POLICY
        compiled = compile_strategy(source, {"mob_id": 12}, self.scene, {"route": [{"map_id": 200}]})
        self.assertTrue(compiled.startswith(header))
        self.assertEqual(1, compiled.count("@mode tick"))
        self.assertIn('["mob_id"]=12', compiled)
        self.assertIn('["scene_generation"]=1', compiled)
        self.assertIn('["route"]={{["map_id"]=200}}', compiled)
        self.assertNotIn("game.state()", compiled)
        self.assertNotIn("main(__beidou_context)", compiled)
        self.assertTrue(compiled.endswith("return {main=main,context=__beidou_context}\nend\n"))
        execution = parse_script_execution(compiled)
        self.assertEqual(
            ("tick", 12.5, "skip", False),
            (execution.mode, execution.budget_ms, execution.overrun, execution.abort_commit),
        )
        legacy = compile_strategy(POLICY, {"mob_id": 12}, self.scene)
        self.assertIn("game.state()", legacy)
        self.assertIn("strategy_scene_context_stale", legacy)
        self.assertTrue(legacy.endswith("return main(__beidou_context)\nend\n"))

    def test_tick_run_and_start_use_existing_options_and_scene_rules(self) -> None:
        self.path.write_text("-- @mode tick\n" + POLICY, encoding="utf-8")
        for action in ("run", "start"):
            with (
                self.subTest(action=action),
                patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                patch("beidou_pilot.strategy_scene.scene_context", return_value=self.scene) as context,
                patch.object(BridgeClient, "run_script", return_value={"status": "running"}) as run,
            ):
                code, output = self.cli("script", action, str(self.path), "--mob-id", "12")
            self.assertEqual(0, code, output)
            context.assert_called_once_with(self.files.root, self.files.state)
            self.assertIn('["mob_id"]=12', run.call_args.kwargs["code"])
            self.assertTrue(run.call_args.kwargs["code"].startswith("-- @mode tick\n"))
            self.assertEqual(action == "start", run.call_args.kwargs["wait_for_start"])
            self.assertNotIn("game.state()", run.call_args.kwargs["code"])

    def test_execution_config_rejects_invalid_headers_before_backend_or_publication(self) -> None:
        invalid = (
            "-- @mode unknown",
            "-- @mode Tick",
            "-- @mode",
            "-- @mode tick junk",
            "-- @mode tick\n-- @mode tick",
            "-- @tick.budget_ms 10",
            "-- @mode coroutine\n-- @tick.overrun skip",
            "-- @mode tick\n-- @tick.unknown true",
            "-- @mode tick\n-- @tick.budget_ms 10\n-- @tick.budget_ms 10",
            "-- @mode tick\n-- @tick.budget_ms 0",
            "-- @mode tick\n-- @tick.budget_ms -1",
            "-- @mode tick\n-- @tick.budget_ms +1",
            "-- @mode tick\n-- @tick.budget_ms 1e2",
            "-- @mode tick\n-- @tick.budget_ms NaN",
            "-- @mode tick\n-- @tick.budget_ms inf",
            "-- @mode tick\n-- @tick.overrun restart",
            "-- @mode tick\n-- @tick.abort_commit True",
            "-- @mode tick\n-- @tick.abort_commit 1",
            "-- @mode tick\n-- @tick budget_ms 10",
        )
        for header in invalid:
            source = header + "\nlocal function main(context)\nend\n"
            self.path.write_text(source, encoding="utf-8")
            for arguments in ((str(self.path),), ("--code=" + source,)):
                with (
                    self.subTest(header=header, arguments=arguments),
                    patch("beidou_pilot.cli.Backend") as backend,
                    patch.object(BridgeClient, "run_script") as run,
                ):
                    code, output = self.cli("script", "start", *arguments)
                self.assertEqual(2, code, output)
                self.assertEqual("invalid_strategy_metadata", json.loads(output)["error"]["code"])
                backend.assert_not_called()
                run.assert_not_called()

    def test_only_real_leading_line_comments_define_execution_mode(self) -> None:
        for source in (
            "--[[\n-- @mode tick\n]]\nlocal x = 1\n-- @mode tick\n",
            "--[=[\n-- @mode unknown\n]=]\n-- @mode coroutine\nlocal x = 1\n",
            "local text = '-- @mode tick'\n-- @tick.budget_ms invalid\n",
        ):
            with self.subTest(source=source):
                self.assertEqual("coroutine", parse_script_execution(source).mode)
        source = "-- a literal --[[ inside a line comment\n--- @mode tick\nfunction main(context)\nend\n"
        self.assertEqual("tick", parse_script_execution(source).mode)
        self.assertEqual("tick", parse_script_execution(with_library("travel", None, source)).mode)
        source = "--[==[\n-- @mode coroutine\n]==]\n-- @mode tick\nfunction main(context)\nend\n"
        self.assertEqual("tick", parse_script_execution(compile_strategy(source, {}, self.scene)).mode)

    def test_raw_tick_code_keeps_native_global_main_entry(self) -> None:
        source = "-- @mode tick\nfunction main(context) return 'done' end\n"
        with patch.object(BridgeClient, "run_script", return_value={"status": "completed"}) as run:
            code, output = self.cli("script", "start", "--code=" + source)
        self.assertEqual(0, code, output)
        self.assertEqual(source, run.call_args.kwargs["code"])

    def test_scene_context_keeps_catalog_source_and_reports_missing_terrain(self) -> None:
        terrain = self.scene["terrain"]
        catalog_result = terrain | {"map_id": 100}
        with patch("beidou_pilot.strategy_scene.load_hunt_terrain", return_value=catalog_result):
            available = scene_context(self.files.root, self.files.state)
        self.assertEqual(self.files.state["instance_id"], available["instance_id"])
        self.assertEqual(self.files.state["character"]["id"], available["character_id"])
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
