"""双端入口的最小消费合同；不以文件对端代替游戏效果。"""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.bridge import BridgeClient
from beidou_pilot.cli import main
from beidou_pilot.control_scripts import action, move_to_x
from beidou_pilot.errors import ClientError
from beidou_pilot.headless import open_game
from .test_bridge import BridgeFiles


class UnifiedControlContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = BridgeFiles(self.root)
        (self.root / "clientctl.py").touch()

    def test_explicit_backend_before_or_after_command_selects_same_bridge(self) -> None:
        for arguments in (("--backend", "headless", "bridge", "status"),
                          ("bridge", "status", "--backend", "headless")):
            with self.subTest(arguments=arguments), patch.object(BridgeClient, "snapshot", return_value=self.files.state):
                with patch("beidou_pilot.cli.Backend", wraps=Backend) as selected:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(0, main(["--root", str(self.root), "--json", *arguments]))
                    self.assertEqual("headless", selected.call_args.args[1])

    def test_headless_unknown_window_or_raw_input_never_calls_beidou_engine(self) -> None:
        for command in (("key", "Right"), ("ui", "focus")):
            with self.subTest(command=command), patch.object(Backend, "_run") as legacy:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(2, main(["--root", str(self.root), "--backend", "headless", "--json", *command]))
                self.assertEqual("unsupported_capability", json.loads(output.getvalue())["error"]["code"])
                legacy.assert_not_called()

    def test_key_and_skill_cli_dispatch_through_lua_controls(self) -> None:
        cases = [(["key", "Right", "--seconds", "0.2"], "press_keys", ["Right"], {"seconds": .2}),
                 (["skill", "1001005"], "skill", 1001005, {})]
        for command, operation, argument, options in cases:
            with self.subTest(command=command), patch.object(Backend, "_run") as desktop:
                with patch("beidou_pilot.control_scripts." + operation,
                           return_value={"status": "completed"}) as control:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(0, main(["--root", str(self.root), "--json", *command]))
                    backend, actual = control.call_args.args
                    self.assertEqual("beidou", backend.name)
                    self.assertEqual("default", backend.instance)
                    self.assertEqual(argument, actual)
                    self.assertEqual(options, control.call_args.kwargs)
                    desktop.assert_not_called()

    def test_fight_passes_selected_first_job_or_explicit_target_to_lua(self) -> None:
        cases = [
            ("beidou", 0, 7, [], 8, "first_job_checkpoint"),
            ("headless", 0, 7, ["--first-job", "magician"], 8, "advancement"),
            ("beidou", 0, 8, ["--first-job", "warrior"], 10, "advancement"),
            ("headless", 0, 8, ["--until-level", "10"], 10, "until_level"),
            ("beidou", 0, 7, ["--first-job", "magician", "--until-level", "10"], 8, "advancement"),
            ("headless", 100, 29, [], 30, "advancement"),
        ]
        for backend, job, level, options, expected_level, expected_source in cases:
            with self.subTest(backend=backend, job=job, level=level, options=options):
                self.files.state["character"].update(job=job, level=level)
                self.files.state["monsters"] = []
                output = io.StringIO()
                with patch.object(BridgeClient, "snapshot", return_value=self.files.state):
                    with patch("beidou_pilot.control_scripts.run_strategy",
                               return_value={"status": "completed", "last_state": self.files.state}) as run:
                        with redirect_stdout(output):
                            exit_code = main(["--root", str(self.root), "--backend", backend, "--json",
                                              "fight", "100100", "--bounds", "-200", "200", *options])
                report = json.loads(output.getvalue())
                self.assertEqual(0, exit_code, report)
                self.assertEqual("combat/fight", run.call_args.args[1])
                self.assertEqual(expected_level, run.call_args.args[2]["stop_level"])
                self.assertEqual(expected_level, report["data"]["requested_level"])
                self.assertEqual(expected_source, report["data"]["stop_level_source"])

    def test_fight_stops_at_due_or_unselected_advancement_before_loading_lua(self) -> None:
        cases = [(0, 8, [], "advancement_route_required"),
                 (0, 8, ["--first-job", "magician"], "advancement_due"),
                 (0, 10, ["--first-job", "warrior"], "advancement_due"),
                 (100, 30, [], "advancement_due")]
        for job, level, options, expected_error in cases:
            with self.subTest(job=job, level=level, options=options):
                self.files.state["character"].update(job=job, level=level)
                self.files.state["monsters"] = []
                output = io.StringIO()
                with patch.object(BridgeClient, "snapshot", return_value=self.files.state):
                    with patch("beidou_pilot.control_scripts.run_strategy") as run:
                        with redirect_stdout(output):
                            exit_code = main(["--root", str(self.root), "--json", "fight", "100100",
                                              "--bounds", "-200", "200", *options])
                self.assertEqual((2, expected_error), (exit_code, json.loads(output.getvalue())["error"]["code"]))
                run.assert_not_called()

    def test_headless_multiple_items_use_the_common_consumable_workflow(self) -> None:
        with patch("beidou_pilot.items.use", return_value={"used": 2}) as use:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(0, main(["--root", str(self.root), "--backend", "headless", "--json",
                                          "use", "2000003", "--count", "2"]))
            backend, item_id = use.call_args.args
            self.assertEqual("headless", backend.name)
            self.assertEqual(2000003, item_id)
            self.assertEqual({"count": 2, "until_hp": None, "until_mp": None, "seconds": None}, use.call_args.kwargs)

    def test_backend_snapshots_remain_separate_and_native_coordinates_can_be_floats(self) -> None:
        directory = self.root / "runtime/headless/bridge"
        directory.mkdir(parents=True)
        native = {**self.files.state, "instance_id": "headless-1", "run_id": "headless-run",
                  "position": {"x": 10.5, "y": 20.0},
                  "monsters": [{"object_id": 300, "template_id": None, "name": None,
                                "x": 12.5, "y": 20.0, "active": True}]}
        (directory / "state.json").write_text(json.dumps(native))
        (self.root / "state/maple-session-headless.json").write_text('{"run_id":"headless-run"}')
        self.assertEqual("client-1", BridgeClient(self.root).snapshot()["instance_id"])
        observed = BridgeClient(self.root, "headless").snapshot()
        self.assertEqual("headless-1", observed["instance_id"])
        self.assertEqual(10.5, observed["position"]["x"])
        self.assertEqual(12.5, observed["monsters"][0]["x"])

    def test_common_move_emits_identical_lua_and_preserves_native_final_state(self) -> None:
        sources = []
        native_result = {"dispatched": False, "control_released": True, "settled": None,
                         "effect": "unknown", "reason": "native_attack_not_allowed"}

        def run(backend, source, seconds):
            sources.append(source)
            return {"status": "completed", "last_state": {**self.files.state, "position": {"x": 40, "y": 20},
                                                             "action_result": native_result}}

        with patch.object(BridgeClient, "snapshot", return_value=self.files.state):
            with patch("beidou_pilot.control_scripts.run_source", side_effect=run):
                for name in ("beidou", "headless"):
                    report = move_to_x(Backend(self.root, name), 40, seconds=3)
                    self.assertEqual("arrived", report["status"])
                    self.assertEqual("travel/move_to", report["strategy"])
                    self.assertTrue(Path(report["script_file"]).is_file())
                    self.assertEqual(40, report["after"]["position"]["x"])
                attack = action(Backend(self.root, "headless"), "attack")
                self.assertEqual(native_result, attack["action_result"])
                self.assertNotIn("strategy", attack)
        self.assertEqual(sources[0], sources[1])
        self.assertEqual("game.attack()\n", sources[2])
        with patch.object(BridgeClient, "snapshot", return_value=self.files.state):
            with patch("beidou_pilot.control_scripts.run_source", return_value={
                    "status": "cancelled", "reason": "time_limit", "last_state": self.files.state}):
                report = move_to_x(Backend(self.root, "headless"), 40, seconds=3)
        self.assertEqual("cancelled", report["status"])
        self.assertEqual("time_limit", report["reason"])

    def test_cli_can_present_native_bridge_state_with_millisecond_timestamp(self) -> None:
        self.files.state["character"].update(job=0, level=8)
        report = {"backend": "headless", "stage": "IN_GAME", "running": True,
                  "character": self.files.state["character"], "state": self.files.state}
        with patch("beidou_pilot.headless.status", return_value=report):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--root", str(self.root), "--backend", "headless", "status", "--json"]))
            result = json.loads(output.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(self.files.state["observed_at_ms"], result["data"]["state"]["observed_at_ms"])
        self.assertIsNone(result["data"]["advancement"]["level"])
        self.assertEqual(8, result["data"]["advancement"]["candidates"][0]["level"])

    def test_headless_reuse_rejects_a_different_explicit_target_or_actor(self) -> None:
        target = self.root / "target.json"
        target.write_text('{"project":"different-validation"}')
        profile = self.root / "profile.json"
        profile.write_text('{"username":"fixture","password":"fixture","character_id":7}')
        profile.chmod(0o600)
        saved = {"target_config": {"project": "original-validation"}, "character_id": 6,
                 "channel": 1, "world": 0}
        existing = {"State": {"Running": True}}
        with patch("beidou_pilot.headless.current_container", return_value=existing):
            with patch("beidou_pilot.headless.registration", return_value=saved):
                with patch("beidou_pilot.headless.status") as observation:
                    with self.assertRaises(ClientError) as target_error:
                        open_game(self.root, target=target, profile=None)
                    self.assertEqual("headless_target_mismatch", target_error.exception.code)
                    with self.assertRaises(ClientError) as actor_error:
                        open_game(self.root, target=None, profile=profile)
                    self.assertEqual("headless_character_mismatch", actor_error.exception.code)
                    observation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
