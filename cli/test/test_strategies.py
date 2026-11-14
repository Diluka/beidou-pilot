"""tick Lua 脚本的 CLI 声明、上下文和原生执行入口合同。"""

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
from beidou_pilot.strategies import (
    compile_strategy,
    parse_options,
    parse_script_execution,
    parse_strategy,
    read_strategy_file,
)
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
                patch("beidou_pilot.strategy_scene.scene_context", return_value=self.scene),
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
            self.assertNotIn("game.state()", source)
            self.assertTrue(source.endswith("return {main=main,context=__beidou_context}\nend\n"))
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
        self.assertEqual("tick", data["mode"])
        self.assertEqual({"gear": 3, "budget_ms": 100, "overrun": "abort", "abort_commit": True}, data["tick"])
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
        self.assertFalse(data["options"][0]["required"])
        self.assertTrue(data["options"][0]["default"])
        metadata = parse_strategy(self.path.read_text(encoding="utf-8"))
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
                patch("beidou_pilot.strategy_scene.scene_context", return_value=self.scene),
                patch.object(BridgeClient, "run_script", return_value={"status": "completed"}) as run,
            ):
                code, output = self.cli("script", "run", str(self.path), *arguments)
            self.assertEqual(0, code, output)
            self.assertIn(f'["enabled"]={expected}', run.call_args.kwargs["code"])

    def test_boolean_inputs_obey_choices_before_script_dispatch(self) -> None:
        source = "-- @option[type=boolean,choices=true] enabled 启用策略\nlocal function main(context)\nend\n"
        metadata = parse_strategy(source)
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
        self.assertEqual({"enabled": False}, parse_options(metadata, []))
        self.assertEqual({"enabled": True}, parse_options(metadata, ["--enabled"]))
        self.assertEqual({"enabled": False}, parse_options(metadata, ["--no-enabled"]))

    def test_explicit_false_default_can_match_false_only_choices(self) -> None:
        metadata = parse_strategy(
            "-- @option[type=boolean,default=false,choices=false] disabled 默认关闭\n"
            "local function main(context)\nend\n"
        )
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
            patch("beidou_pilot.strategy_scene.scene_context", return_value=self.scene),
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

    def test_raw_chunk_without_main_is_rejected(self) -> None:
        raw_file = self.files.root / "raw.lua"
        raw_file.write_text("game.log('raw file')\n", encoding="utf-8")
        with self.assertRaises(ClientError) as raised:
            read_strategy_file(raw_file)
        self.assertEqual("invalid_strategy_metadata", raised.exception.code)
        for arguments in (("script", "run", str(raw_file)), ("script", "start", str(raw_file))):
            with (
                self.subTest(arguments=arguments),
                patch("beidou_pilot.cli.Backend", wraps=Backend) as backend,
                patch.object(BridgeClient, "run_script") as run,
            ):
                code, output = self.cli(*arguments)
            self.assertEqual(2, code)
            self.assertEqual("invalid_strategy_metadata", json.loads(output)["error"]["code"])
            backend.assert_not_called()
            run.assert_not_called()

    def test_coroutine_mode_and_removed_inputs_are_rejected(self) -> None:
        self.path.write_text("-- @mode coroutine\n" + POLICY, encoding="utf-8")
        with (
            patch("beidou_pilot.cli.Backend") as backend,
            patch.object(BridgeClient, "run_script") as run,
        ):
            code, output = self.cli("script", "run", str(self.path), "--mob-id", "12")
        self.assertEqual(2, code)
        self.assertEqual("invalid_strategy_metadata", json.loads(output)["error"]["code"])
        backend.assert_not_called()
        run.assert_not_called()

        self.path.write_text("-- @mode tick\n" + POLICY, encoding="utf-8")
        for arguments in (
            ("script", "run", "--code", "function main(context) end"),
            ("script", "run", str(self.path), "--library", "travel", "--mob-id", "12"),
        ):
            with (
                self.subTest(arguments=arguments),
                patch("beidou_pilot.cli.Backend", wraps=Backend) as backend,
                patch.object(BridgeClient, "run_script") as run,
            ):
                code, output = self.cli(*arguments)
            self.assertEqual(2, code, output)
            backend.assert_not_called()
            run.assert_not_called()

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
        for arguments in (("--mob-id", "0"), ("--mob-id", "12", "--range-mode", "anywhere")):
            with (
                self.subTest(arguments=arguments),
                patch("beidou_pilot.cli.Backend", wraps=Backend) as backend,
                patch.object(BridgeClient, "run_script") as run,
            ):
                code, output = self.cli("script", "run", str(self.path), *arguments)
            self.assertEqual(2, code)
            self.assertEqual("invalid_strategy_option", json.loads(output)["error"]["code"])
            backend.assert_not_called()
            run.assert_not_called()

    def test_tick_default_and_explicit_metadata_are_visible_without_a_client(self) -> None:
        self.assertEqual(100, parse_script_execution(POLICY).budget_ms)
        self.assertEqual(1, parse_script_execution("-- @tick.gear 1\n" + POLICY).gear)
        execution = parse_script_execution(
            "-- @mode tick\n-- @tick.gear 4 -- 说明\n-- @tick.budget_ms 12.5\n"
            "-- @tick.overrun skip\n-- @tick.abort_commit false\n"
        )
        self.assertEqual(
            (12.5, "skip", False, 4), (execution.budget_ms, execution.overrun, execution.abort_commit, execution.gear)
        )
        for budget, expected in ((".5", 0.5), ("1.", 1), ("0002.5", 2.5)):
            with self.subTest(budget=budget):
                execution = parse_script_execution("-- @mode tick--说明\n-- @tick.budget_ms " + budget + "\n")
                self.assertEqual(expected, execution.budget_ms)

    def test_compile_returns_entry_and_context_without_old_state_or_calling_main(self) -> None:
        header = (
            "-- @mode tick\n-- @tick.gear 2\n-- @tick.budget_ms 12.5\n"
            "-- @tick.overrun skip -- 分片执行\n-- @tick.abort_commit false\n"
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
            (12.5, "skip", False, 2), (execution.budget_ms, execution.overrun, execution.abort_commit, execution.gear)
        )

    def test_execution_config_rejects_invalid_headers_before_backend_or_publication(self) -> None:
        invalid = (
            "-- @mode coroutine",
            "-- @mode unknown",
            "-- @mode Tick",
            "-- @mode",
            "-- @mode tick junk",
            "-- @mode tick\n-- @mode tick",
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
            "-- @mode tick\n-- @tick.gear 1\n-- @tick.gear 1",
        ) + tuple(
            "-- @mode tick\n-- @tick.gear " + value
            for value in (
                "",
                "0",
                "5",
                "01",
                "+1",
                "-1",
                "1.0",
                ".1",
                "1e0",
                "NaN",
                "inf",
                "true",
                "1 2",
                "１",
                "9" * 5000,
            )
        )
        for header in invalid:
            source = header + "\nlocal function main(context)\nend\n"
            self.path.write_text(source, encoding="utf-8")
            with (
                self.subTest(header=header),
                patch("beidou_pilot.cli.Backend") as backend,
                patch.object(BridgeClient, "run_script") as run,
            ):
                code, output = self.cli("script", "start", str(self.path))
            self.assertEqual(2, code, output)
            self.assertEqual("invalid_strategy_metadata", json.loads(output)["error"]["code"])
            backend.assert_not_called()
            run.assert_not_called()

    def test_only_real_leading_line_comments_define_execution_mode(self) -> None:
        for source in (
            "--[[\n-- @mode tick\n]]\nlocal function main(context)\nend\n",
            "--[=[\n-- @mode unknown\n]=]\nlocal function main(context)\nend\n",
            "local text = '-- @mode tick'\n-- @tick.budget_ms invalid\nlocal function main(context)\nend\n",
        ):
            with self.subTest(source=source):
                self.assertEqual(100, parse_script_execution(source).budget_ms)
        source = "-- a literal --[[ inside a line comment\n--- @mode tick\nfunction main(context)\nend\n"
        self.assertEqual(100, parse_script_execution(source).budget_ms)
        source = "--[==[\n-- @mode coroutine\n]==]\n-- @mode tick\nfunction main(context)\nend\n"
        self.assertEqual(100, parse_script_execution(compile_strategy(source, {}, self.scene)).budget_ms)

    def test_scene_context_injects_identity_only(self) -> None:
        available = scene_context(self.files.state)
        self.assertEqual(
            {
                "instance_id": self.files.state["instance_id"],
                "character_id": self.files.state["character"]["id"],
                "map_id": self.files.state["map_id"],
                "scene_generation": self.files.state["scene_generation"],
            },
            available,
        )
        not_ready = {**self.files.state, "ready": False}
        with self.assertRaises(ClientError) as raised:
            scene_context(not_ready)
        self.assertEqual("strategy_scene_unavailable", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
