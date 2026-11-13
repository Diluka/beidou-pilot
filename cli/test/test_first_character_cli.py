import argparse
import unittest
from unittest.mock import MagicMock, patch

from beidou_pilot.cli import parser
from beidou_pilot.errors import ClientError
from beidou_pilot.first_character import execute


class FirstCharacterTest(unittest.TestCase):
    def setUp(self):
        self.backend = MagicMock(name="backend")
        self.backend.name = "headless"
        self.runtime = MagicMock(run_id="run", running=True)
        self.native = MagicMock()
        self.native.snapshot.return_value = {"instance_id": "native"}
        self.bridge = MagicMock()
        self.bridge.snapshot.return_value = {
            "phase": "character_list",
            "characters": [],
            "pending_request_id": None,
            "instance_id": "native",
            "run_id": "run",
        }
        self.bridge.submit.return_value = "a" * 32
        self.patches = [
            patch("beidou_pilot.first_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.first_character.BridgeClient", return_value=self.native),
            patch("beidou_pilot.first_character.LoginBridge", return_value=self.bridge),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def create_args(self):
        return parser().parse_args(
            [
                "character",
                "create",
                "--name",
                "Hero",
                "--gender",
                "male",
                "--timeout",
                "0",
                *sum(
                    (
                        ["--" + key, "1"]
                        for key in ("job", "face", "hair", "hair-color", "skin", "top", "bottom", "shoes", "weapon")
                    ),
                    [],
                ),
            ]
        )

    def test_login_only_observes(self):
        result = execute(self.backend, parser().parse_args(["login"]))
        self.assertEqual(result["phase"], "character_list")
        self.bridge.submit.assert_not_called()

    def test_create_returns_real_cid(self):
        self.bridge.result.return_value = {"status": "completed", "character_id": 123}
        self.assertEqual(execute(self.backend, self.create_args())["character_id"], 123)
        self.bridge.submit.assert_called_once()
        self.assertEqual(self.bridge.submit.call_args.args[0].hair_color, 1)

    def test_headless_create_default_timeout_is_three_seconds(self):
        self.bridge.result.return_value = {"status": "accepted"}
        args = self.create_args()
        args.timeout = None
        with (
            patch("beidou_pilot.first_character.time.monotonic", side_effect=[10, 13]),
            patch("beidou_pilot.first_character.time.sleep") as sleep,
        ):
            self.assertEqual(execute(self.backend, args)["status"], "accepted")
            sleep.assert_not_called()

    def test_accepted_is_returned_while_live(self):
        self.bridge.result.return_value = {"status": "accepted"}
        result = execute(self.backend, self.create_args())
        self.assertEqual(result["status"], "accepted")
        self.bridge.submit.assert_called_once()

    def test_accepted_becomes_unknown_after_identity_change(self):
        self.bridge.result.return_value = {"status": "accepted"}
        self.native.snapshot.side_effect = [{"instance_id": "native"}, {"instance_id": "other"}]
        result = execute(self.backend, self.create_args())
        self.assertEqual((result["status"], result["last_observed_status"]), ("unknown", "accepted"))
        self.bridge.submit.assert_called_once()

    def test_gui_login_missing_options_observes_without_input(self):
        self.backend.name = "beidou"
        self.native.snapshot.return_value = {"instance_id": "native", "run_id": "run"}
        stage = {"instance_id": "native", "client": {"run_id": "run"}, "stage": "LOGIN"}
        self.backend.read.return_value = stage
        with patch("beidou_pilot.gui_login.execute") as gui_execute:
            self.assertEqual(execute(self.backend, argparse.Namespace(command="login")), stage)
            gui_execute.assert_not_called()
        self.bridge.submit.assert_not_called()

    def test_gui_direct_action_missing_gender_rejected(self):
        self.backend.name = "beidou"
        self.native.snapshot.return_value = {"instance_id": "native", "run_id": "run"}
        with self.assertRaises(ClientError) as caught:
            execute(self.backend, argparse.Namespace(command="login", accept_terms=True))
        self.assertEqual(caught.exception.code, "usage")

    def test_result_never_submits(self):
        self.bridge.result.return_value = {"status": "unknown"}
        execute(
            self.backend,
            parser().parse_args(["character", "result", "a" * 32, "--run-id", "run", "--instance-id", "native"]),
        )
        self.bridge.submit.assert_not_called()

    def test_result_after_exit_retains_terminal_outcome(self):
        self.runtime.running = False
        self.bridge.result.return_value = {"status": "completed", "character_id": 23}
        args = parser().parse_args(["character", "result", "a" * 32, "--run-id", "run", "--instance-id", "native"])
        self.assertEqual(execute(self.backend, args)["character_id"], 23)
        self.native.snapshot.assert_not_called()

    def test_result_after_exit_projects_accepted_unknown(self):
        self.runtime.running = False
        self.bridge.result.return_value = {"status": "accepted"}
        args = parser().parse_args(["character", "result", "a" * 32, "--run-id", "run", "--instance-id", "native"])
        result = execute(self.backend, args)
        self.assertEqual((result["status"], result["last_observed_status"]), ("unknown", "accepted"))

    def test_login_waits_for_cold_bridge(self):
        self.native.snapshot.side_effect = [ClientError("bridge_unavailable", "not yet"), {"instance_id": "native"}]
        result = execute(self.backend, parser().parse_args(["login", "--timeout", "1"]))
        self.assertEqual(result["phase"], "character_list")
        self.assertEqual(self.native.snapshot.call_count, 2)
        self.bridge.submit.assert_not_called()

    def test_login_exited_process_points_to_logs_without_inventing_reason(self):
        self.runtime.running = False
        with self.assertRaises(ClientError) as caught:
            execute(self.backend, parser().parse_args(["login"]))
        self.assertEqual(caught.exception.code, "bridge_session_unavailable")
        self.assertIn("运行日志", caught.exception.message)
        self.assertEqual(caught.exception.details, {})
        self.native.snapshot.assert_not_called()

    def test_login_failure_is_reported_without_waiting(self):
        self.bridge.snapshot.return_value.update({"phase": "failed", "error": "authentication_failed"})
        with self.assertRaises(ClientError) as caught:
            execute(self.backend, parser().parse_args(["login", "--timeout", "60"]))
        self.assertEqual(caught.exception.code, "login_failed")
        self.assertEqual(caught.exception.details["reason"], "authentication_failed")
        self.bridge.submit.assert_not_called()

    def test_login_unready_is_timeout(self):
        self.bridge.snapshot.return_value["phase"] = "login"
        with self.assertRaises(ClientError) as caught:
            execute(self.backend, parser().parse_args(["login"]))
        self.assertEqual(caught.exception.code, "login_timeout")
