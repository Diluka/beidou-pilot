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
        for arguments in (("--backend", "headless", "bridge", "status"), ("bridge", "status", "--backend", "headless")):
            with (
                self.subTest(arguments=arguments),
                patch.object(BridgeClient, "snapshot", return_value=self.files.state),
            ):
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
        cases = [
            (["key", "Right", "--seconds", "0.2"], "press_keys", ["Right"], {"seconds": 0.2}),
            (["skill", "1001005"], "skill", 1001005, {}),
        ]
        for command, operation, argument, options in cases:
            with self.subTest(command=command), patch.object(Backend, "_run") as desktop:
                with patch(
                    "beidou_pilot.control_scripts." + operation, return_value={"status": "completed"}
                ) as control:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(0, main(["--root", str(self.root), "--json", *command]))
                    backend, actual = control.call_args.args
                    self.assertEqual("beidou", backend.name)
                    self.assertEqual("default", backend.instance)
                    self.assertEqual(argument, actual)
                    self.assertEqual(options, control.call_args.kwargs)
                    desktop.assert_not_called()

    def test_headless_multiple_items_use_the_common_consumable_workflow(self) -> None:
        with patch("beidou_pilot.items.use", return_value={"used": 2}) as use:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    0,
                    main(
                        ["--root", str(self.root), "--backend", "headless", "--json", "use", "2000003", "--count", "2"]
                    ),
                )
            backend, item_id = use.call_args.args
            self.assertEqual("headless", backend.name)
            self.assertEqual(2000003, item_id)
            self.assertEqual({"count": 2, "until_hp": None, "until_mp": None, "seconds": None}, use.call_args.kwargs)

    def test_headless_revive_uses_one_lua_request_and_requires_confirmation(self) -> None:
        for reason, effect, dispatched, code in (
            ("already_alive", "confirmed", False, 0),
            ("revive_confirmed", "confirmed", True, 0),
            ("revive_not_confirmed", "unknown", True, 2),
        ):
            with self.subTest(reason=reason):
                report = {
                    "status": "completed",
                    "last_state": {
                        "action_result": {
                            "dispatched": dispatched,
                            "control_released": True,
                            "effect": effect,
                            "reason": reason,
                        }
                    },
                }
                with patch("beidou_pilot.control_scripts.run_source", return_value=report) as run:
                    with patch.object(Backend, "_run") as desktop:
                        output = io.StringIO()
                        with redirect_stdout(output):
                            self.assertEqual(
                                code, main(["--root", str(self.root), "--backend", "headless", "--json", "revive"])
                            )
                self.assertEqual(1, run.call_count)
                self.assertEqual(("game.revive()\n", 8), run.call_args.args[1:])
                desktop.assert_not_called()
                result = json.loads(output.getvalue())
                if code == 0:
                    self.assertEqual("revived" if dispatched else "already_alive", result["data"]["status"])
                    self.assertEqual(dispatched, result["data"]["changed"])
                else:
                    self.assertEqual("revive_not_confirmed", result["error"]["code"])

    def test_headless_equipment_loads_one_lua_request_and_requires_native_confirmation(self) -> None:
        equipped = ["equip", "1002001", "--slot", "2", "--to-slot", "-5", "--seconds", "1.25"]
        removed = ["unequip", "--slot", "-5", "--to-slot", "7"]
        cases = [
            (equipped, "completed", "confirmed", 0),
            (removed, "completed", "confirmed", 0),
            (equipped, "completed", "unknown", 2),
            (equipped, "cancelled", "confirmed", 0),
        ]
        for command, status, effect, code in cases:
            with self.subTest(command=command, status=status, effect=effect):
                native_result = {
                    "dispatched": True,
                    "control_released": True,
                    "settled": None,
                    "effect": effect,
                    "reason": "equipment_changed" if effect == "confirmed" else "equipment_confirmation_timeout",
                }
                report = {"status": status, "last_state": {"action_result": native_result}}
                with patch("beidou_pilot.control_scripts.run_source", return_value=report) as run:
                    with patch.object(Backend, "_run") as desktop:
                        output = io.StringIO()
                        with redirect_stdout(output):
                            self.assertEqual(
                                code, main(["--root", str(self.root), "--backend", "headless", "--json", *command])
                            )
                        run.assert_called_once()
                        backend, source, _ = run.call_args.args
                        self.assertEqual("headless", backend.name)
                        if command[0] == "equip":
                            self.assertIn('game.observe("inventory")', source)
                            self.assertIn("selected.item_id == 1002001", source)
                            self.assertIn("item.slot == 2", source)
                            self.assertIn("game.equip(2, -5, 1.25)", source)
                        else:
                            self.assertEqual("game.unequip(-5, 7, 3)\n", source)
                        actual = json.loads(output.getvalue())
                        if code:
                            self.assertEqual("equipment_change_unconfirmed", actual["error"]["code"])
                            self.assertFalse(actual["error"]["details"]["confirmed"])
                        else:
                            self.assertEqual(status == "completed", actual["data"]["confirmed"])
                            self.assertEqual(native_result, actual["data"]["action_result"])
                        desktop.assert_not_called()

    def test_gui_equipment_rejects_headless_slot_arguments_without_dispatch(self) -> None:
        for command in (
            ["equip", "1002001", "--slot", "2", "--to-slot", "-5"],
            ["unequip", "--slot", "-5", "--to-slot", "7"],
        ):
            with self.subTest(command=command), patch("beidou_pilot.control_scripts.run_source") as run:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(2, main(["--root", str(self.root), "--backend", "beidou", "--json", *command]))
                self.assertEqual("unsupported_capability", json.loads(output.getvalue())["error"]["code"])
                run.assert_not_called()

    def test_backend_snapshots_remain_separate_and_native_coordinates_can_be_floats(self) -> None:
        directory = self.root / "runtime/headless/bridge"
        directory.mkdir(parents=True)
        native = {
            **self.files.state,
            "instance_id": "headless-1",
            "run_id": "headless-run",
            "position": {"x": 10.5, "y": 20.0},
            "monsters": [{"object_id": 300, "template_id": None, "name": None, "x": 12.5, "y": 20.0, "active": True}],
        }
        (directory / "state.json").write_text(json.dumps(native))
        (self.root / "state/maple-session-headless.json").write_text('{"run_id":"headless-run"}')
        self.assertEqual("client-1", BridgeClient(self.root).snapshot()["instance_id"])
        observed = BridgeClient(self.root, "headless").snapshot()
        self.assertEqual("headless-1", observed["instance_id"])
        self.assertEqual(10.5, observed["position"]["x"])
        self.assertEqual(12.5, observed["monsters"][0]["x"])

    def test_common_move_emits_identical_lua_and_preserves_native_final_state(self) -> None:
        sources = []
        native_result = {
            "dispatched": False,
            "control_released": True,
            "settled": None,
            "effect": "unknown",
            "reason": "native_attack_not_allowed",
        }

        def run(backend, source, seconds):
            sources.append(source)
            return {
                "status": "completed",
                "last_state": {**self.files.state, "position": {"x": 40, "y": 20}, "action_result": native_result},
            }

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
            with patch(
                "beidou_pilot.control_scripts.run_source",
                return_value={"status": "cancelled", "reason": "time_limit", "last_state": self.files.state},
            ):
                report = move_to_x(Backend(self.root, "headless"), 40, seconds=3)
        self.assertEqual("cancelled", report["status"])
        self.assertEqual("time_limit", report["reason"])

    def test_cli_can_present_native_bridge_state_with_millisecond_timestamp(self) -> None:
        report = {
            "backend": "headless",
            "stage": "IN_GAME",
            "running": True,
            "character": self.files.state["character"],
            "state": self.files.state,
        }
        with patch("beidou_pilot.headless.status", return_value=report):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--root", str(self.root), "--backend", "headless", "status", "--json"]))
            result = json.loads(output.getvalue())
        self.assertTrue(result["ok"])
        self.assertEqual(self.files.state["observed_at_ms"], result["data"]["state"]["observed_at_ms"])

    def test_headless_reuse_rejects_a_different_explicit_target_or_actor(self) -> None:
        target = self.root / "target.json"
        target.write_text('{"project":"different-validation"}')
        profile = self.root / "profile.json"
        profile.write_text('{"username":"fixture","password":"fixture","character_id":7}')
        profile.chmod(0o600)
        saved = {"target_config": {"project": "original-validation"}, "character_id": 6, "channel": 1, "world": 0}
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
