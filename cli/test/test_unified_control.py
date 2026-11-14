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


TICK_SOURCE = "-- @mode tick\nlocal function main(context)\n    game.log('tick')\nend\n"

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
    ("revive",),
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

    def test_headless_reuse_rejects_a_different_explicit_server_or_actor(self) -> None:
        server = self.native.root / "server.json"
        server.write_text(json.dumps({**self.native.runtime["target"], "project": "different-validation"}))
        profile = LoginProfile("fixture", "fixture", 4)
        with patch.dict(os.environ, self.native.environment), patch("beidou_pilot.headless.status") as observation:
            with self.assertRaises(ClientError) as server_error:
                open_game(self.native.root, server=server, profile=profile)
            self.assertEqual("server_mismatch", server_error.exception.code)
            with self.assertRaises(ClientError) as actor_error:
                open_game(self.native.root, profile=LoginProfile("fixture", "fixture", 7))
            self.assertEqual("character_mismatch", actor_error.exception.code)
            observation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
