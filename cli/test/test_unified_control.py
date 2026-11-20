"""双端入口的最小消费合同；不以文件对端代替游戏效果。"""

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
from beidou_pilot.headless import open_game
from beidou_pilot.profile import LoginProfile
from .test_bridge import BridgeFiles


TICK_SOURCE = "local function main(context)\n    game.log('tick')\nend\n"

REMOVED_COMMANDS = (
    ("move", "100"),
    ("climb", "100", "--to-y", "20"),
    ("portal", "out"),
    ("navigate", "200"),
    ("hunt",),
    ("task", "add", "work"),
    ("skill", "1001005"),
    ("key", "Right"),
    ("press", "item", "2000000"),
    ("walk", "right"),
    ("face", "left"),
    ("jump",),
    ("attack",),
    ("pickup",),
    ("use_item", "2000000"),
    ("use", "2000000"),
    ("stats", "str", "1"),
    ("skills", "1001005"),
    ("unequip", "--slot", "-5", "--to-slot", "7"),
)

GUI_ONLY_COMMANDS = (
    ("click", "@ref"),
    ("talk", "npc"),
    ("dialog", "select", "1"),
    ("ui", "read"),
    ("equip", "1002001"),
    ("bind", "item", "2000000", "shift"),
    ("shop", "read"),
    ("notifications", "read"),
)


class UnifiedControlContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = BridgeFiles(self.root)
        self.native = BridgeFiles(self.root / "headless", "headless")
        self.native.environment["HOSTNAME"] = "headless-container"
        self.native.register("headless")
        self.native.state["instance_id"] = "headless-1"
        self.native.publish()
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.script = self.files.root / "tick.lua"
        self.script.write_text(TICK_SOURCE, encoding="utf-8")

    def cli(self, backend: str, *arguments: str) -> tuple[int, dict]:
        files = self.files if backend == "beidou" else self.native
        output = io.StringIO()
        with patch.dict(os.environ, files.environment), redirect_stdout(output):
            code = main(["--root", str(files.root), "--backend", backend, "--json", *arguments])
        return code, json.loads(output.getvalue())

    def test_explicit_backend_before_or_after_command_selects_same_bridge(self) -> None:
        for arguments in (("--backend", "headless", "bridge", "status"), ("bridge", "status", "--backend", "headless")):
            with (
                self.subTest(arguments=arguments),
                patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                patch("beidou_pilot.cli.Backend", wraps=Backend) as selected,
                redirect_stdout(io.StringIO()),
                patch.dict(os.environ, self.native.environment),
            ):
                self.assertEqual(0, main(["--root", str(self.native.root), "--json", *arguments]))
            self.assertEqual("headless", selected.call_args.args[1])

    def test_tick_script_uses_one_native_request_for_both_backends(self) -> None:
        for backend in ("beidou", "headless"):
            for operation in ("run", "start"):
                with (
                    self.subTest(backend=backend, operation=operation),
                    patch.object(BridgeClient, "snapshot", return_value=self.files.state),
                    patch("beidou_pilot.strategy_scene.scene_context", return_value={"instance_id": "client-1"}),
                    patch.object(BridgeClient, "run_script", return_value={"status": "completed"}) as run,
                ):
                    code, report = self.cli(backend, "script", operation, str(self.script))
                self.assertEqual(0, code, report)
                self.assertIsNone(run.call_args.args[0])
                self.assertIn("return {main=main,context=__beidou_context}", run.call_args.kwargs["code"])
                self.assertEqual(operation == "start", run.call_args.kwargs["wait_for_start"])
                self.assertEqual(str(self.script), report["data"]["script_file"])

    def test_removed_coroutine_commands_are_rejected_on_both_backends(self) -> None:
        for command in REMOVED_COMMANDS:
            for backend in ("beidou", "headless"):
                with (
                    self.subTest(command=command, backend=backend),
                    patch.object(Backend, "_run") as legacy,
                    patch.object(BridgeClient, "run_script") as run,
                ):
                    code, report = self.cli(backend, *command)
                self.assertEqual(2, code, report)
                self.assertEqual("usage", report["error"]["code"])
                legacy.assert_not_called()
                run.assert_not_called()

    def test_headless_revive_submits_one_tick_request_and_confirms_same_character(self) -> None:
        before = {
            "character": {"id": 42, "hp": 0},
            "native_values_valid": True,
            "position": None,
            "map_id": 100000000,
        }
        after = {
            "character": {"id": 42, "hp": 50},
            "native_values_valid": True,
            "position": {"x": 2581, "y": 567},
            "map_id": 100000000,
        }
        with (
            patch.object(Backend, "read", side_effect=[before, after]),
            patch.object(BridgeClient, "snapshot", return_value={"scripts": []}),
            patch(
                "beidou_pilot.strategy_scene.scene_context",
                return_value={
                    "character_id": 42,
                    "map_id": 100000000,
                    "instance_id": "headless-1",
                    "scene_generation": 1,
                },
            ),
            patch.object(BridgeClient, "run_script", return_value={"status": "completed"}) as run,
        ):
            code, report = self.cli("headless", "revive")
        self.assertEqual(0, code, report)
        self.assertEqual("revived", report["data"]["status"])
        self.assertEqual(1, run.call_count)
        self.assertIn("context.game.player.revive()", run.call_args.kwargs["code"])
        self.assertIn('return "done"', run.call_args.kwargs["code"])
        self.assertIn("return {main=main,context=__beidou_context}", run.call_args.kwargs["code"])
        self.assertEqual(6, run.call_args.kwargs["seconds"])

    def test_headless_revive_timeout_reports_once_without_replay(self) -> None:
        dead = {
            "character": {"id": 42, "hp": 0},
            "native_values_valid": True,
            "position": None,
            "map_id": 100000000,
        }
        with (
            patch.object(Backend, "read", side_effect=[dead, dead]),
            patch.object(BridgeClient, "snapshot", return_value={"scripts": []}),
            patch(
                "beidou_pilot.strategy_scene.scene_context",
                return_value={
                    "character_id": 42,
                    "map_id": 100000000,
                    "instance_id": "headless-1",
                    "scene_generation": 1,
                },
            ),
            patch.object(BridgeClient, "run_script", return_value={"status": "completed"}) as run,
            patch("beidou_pilot.recovery.time.monotonic", side_effect=[0, 0, 7]),
            patch("beidou_pilot.recovery.time.sleep"),
        ):
            code, report = self.cli("headless", "revive")
        self.assertEqual(2, code, report)
        self.assertEqual("revive_not_confirmed", report["error"]["code"])
        self.assertEqual(1, run.call_count)

    def test_gui_revive_rejects_a_running_tick_script_before_observation(self) -> None:
        with (
            patch.object(BridgeClient, "snapshot", return_value={"scripts": [{"id": "owner", "status": "running"}]}),
            patch.object(Backend, "read") as read,
        ):
            code, report = self.cli("beidou", "revive")
        self.assertEqual(2, code, report)
        self.assertEqual("input_busy", report["error"]["code"])
        read.assert_not_called()

    def test_revive_does_not_dispatch_when_alive_or_another_script_controls_headless(self) -> None:
        alive = {
            "character": {"id": 42, "hp": 10},
            "native_values_valid": True,
            "position": {"x": 1, "y": 2},
            "map_id": 100000000,
        }
        with (
            patch.object(Backend, "read", return_value=alive),
            patch.object(BridgeClient, "run_script") as run,
        ):
            code, report = self.cli("headless", "revive")
        self.assertEqual(0, code, report)
        self.assertEqual("already_alive", report["data"]["status"])
        run.assert_not_called()

        dead = {"character": {"id": 42, "hp": 0}, "native_values_valid": True, "position": None, "map_id": 100000000}
        with (
            patch.object(Backend, "read", return_value=dead),
            patch.object(BridgeClient, "snapshot", return_value={"scripts": [{"id": "busy", "status": "running"}]}),
            patch.object(BridgeClient, "run_script") as run,
        ):
            code, report = self.cli("headless", "revive")
        self.assertEqual(2, code, report)
        self.assertEqual("input_busy", report["error"]["code"])
        run.assert_not_called()

    def test_gui_only_commands_are_unsupported_on_headless(self) -> None:
        for command in GUI_ONLY_COMMANDS:
            with (
                self.subTest(command=command),
                patch.object(Backend, "_run") as desktop,
                patch.object(BridgeClient, "snapshot") as snapshot,
            ):
                code, report = self.cli("headless", *command)
            self.assertEqual(2, code, report)
            self.assertEqual("unsupported_capability", report["error"]["code"])
            desktop.assert_not_called()
            snapshot.assert_not_called()

    def test_backend_snapshots_remain_separate_and_native_coordinates_can_be_floats(self) -> None:
        self.native.state.update(
            position={"x": 10.5, "y": 20.0},
            monsters=[{"object_id": 300, "template_id": None, "name": None, "x": 12.5, "y": 20.0, "active": True}],
        )
        self.native.publish()
        self.assertEqual("client-1", BridgeClient(self.root).snapshot()["instance_id"])
        with patch.dict(os.environ, self.native.environment):
            observed = BridgeClient(self.native.root, "headless").snapshot()
        self.assertEqual("headless-1", observed["instance_id"])
        self.assertEqual(10.5, observed["position"]["x"])
        self.assertEqual(12.5, observed["monsters"][0]["x"])

    def test_cli_can_present_native_bridge_state_with_millisecond_timestamp(self) -> None:
        report = {
            "backend": "headless",
            "stage": "IN_GAME",
            "running": True,
            "character": self.native.state["character"],
            "state": self.native.state,
        }
        with patch("beidou_pilot.headless.status", return_value=report):
            code, result = self.cli("headless", "status")
        self.assertEqual(0, code, result)
        self.assertTrue(result["ok"])
        self.assertEqual(self.native.state["observed_at_ms"], result["data"]["state"]["observed_at_ms"])

    def test_world_map_route_is_readonly_and_returns_route_status(self) -> None:
        route = {
            "source": "native_world_map",
            "status": "no_route",
            "error": "no_route",
            "start": 100000000,
            "goal": 200000000,
            "legs": [],
        }
        with (
            patch("beidou_pilot.observations.NativeObserver") as observer,
            patch("beidou_pilot.cli.control") as control,
        ):
            observer.return_value.route.return_value = route
            code, report = self.cli("beidou", "world-map", "route", "100000000", "200000000")
        self.assertEqual(0, code, report)
        self.assertEqual(("world-map", "beidou", "default"), (report["command"], report["backend"], report["instance"]))
        self.assertEqual("no_route", report["data"]["status"])
        self.assertEqual(route, report["data"])
        observer.assert_called_once_with(self.files.root.resolve(), "beidou", "default")
        observer.return_value.route.assert_called_once_with(100000000, 200000000)
        control.assert_not_called()

    def test_world_map_route_allows_headless_native_channel(self) -> None:
        with (
            patch("beidou_pilot.observations.NativeObserver") as observer,
            patch("beidou_pilot.cli.control") as control,
        ):
            observer.return_value.route.return_value = {"status": "ok", "legs": []}
            code, report = self.cli("headless", "world-map", "route", "100000000", "100000200")
        self.assertEqual(0, code, report)
        self.assertEqual("ok", report["data"]["status"])
        observer.return_value.route.assert_called_once_with(100000000, 100000200)
        control.assert_not_called()

    def test_world_map_route_rejects_invalid_or_missing_map_numbers(self) -> None:
        cases = (
            ("world-map", "route"),
            ("world-map", "route", "100000000"),
            ("world-map", "route", "0", "100000200"),
            ("world-map", "route", "-1", "100000200"),
            ("world-map", "route", "abc", "100000200"),
            ("world-map", "route", "100000000", "1e3"),
        )
        for arguments in cases:
            with (
                self.subTest(arguments=arguments),
                patch("beidou_pilot.observations.NativeObserver") as observer,
                patch("beidou_pilot.cli.control") as control,
            ):
                code, report = self.cli("beidou", *arguments)
            self.assertEqual(2, code, report)
            self.assertEqual("usage", report["error"]["code"])
            observer.assert_not_called()
            control.assert_not_called()

    def test_headless_reuse_rejects_a_different_explicit_server(self) -> None:
        server = self.native.root / "server.json"
        server.write_text(json.dumps({**self.native.runtime["target"], "project": "different-validation"}))
        profile = LoginProfile("fixture", "fixture", 4)
        with patch.dict(os.environ, self.native.environment), patch("beidou_pilot.headless.status") as observation:
            with self.assertRaises(ClientError) as server_error:
                open_game(self.native.root, server=server, profile=profile)
            self.assertEqual("server_mismatch", server_error.exception.code)
            observation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
