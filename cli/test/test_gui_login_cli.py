import fcntl
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from beidou_pilot import cli
from beidou_pilot.errors import ClientError


class GuiLoginCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.backend = SimpleNamespace(
            name="beidou",
            root=root,
            instance="default",
            paths=SimpleNamespace(state_directory=root, input_lock=root / "input.lock"),
        )
        self.runtime = SimpleNamespace(running=True, run_id="run")
        self.native = SimpleNamespace(snapshot=lambda: {"run_id": "run", "instance_id": "native"})

    def run_login(self, *args):
        return cli.dispatch(self.backend, cli.parser().parse_args(["login", *args]))

    def test_action_uses_public_lock_and_identity(self):
        with (
            patch("beidou_pilot.first_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.first_character.BridgeClient", return_value=self.native),
            patch("beidou_pilot.profile.load_account_profile", return_value="profile"),
            patch("beidou_pilot.gui_login.execute", return_value={"phase": "character_list"}) as execute,
        ):
            self.assertEqual(
                self.run_login("--accept-terms", "--gender", "female", "--timeout", "20"), {"phase": "character_list"}
            )
            self.assertEqual(
                execute.call_args.kwargs,
                dict(instance_id="native", run_id="run", accept_terms=True, gender="female", timeout=20),
            )
            with self.backend.paths.input_lock.open("a+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(ClientError) as error:
                    self.run_login("--gender", "male", "--timeout", "20")
                self.assertEqual(error.exception.code, "input_busy")
            self.assertEqual(execute.call_count, 1)

    def test_actual_run_lock_is_taken_inside_public_lock(self):
        self.runtime.run_dir = self.backend.root

        def run_locked(*args, **kwargs):
            with (
                self.backend.paths.input_lock.open("a+") as public,
                (self.backend.root / "gui-login.lock").open("a+") as run,
            ):
                for lock in (public, run):
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return {"phase": "character_list"}

        with (
            patch("beidou_pilot.first_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.first_character.BridgeClient", return_value=self.native),
            patch("beidou_pilot.gui_login.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.profile.load_account_profile", return_value="profile"),
            patch("beidou_pilot.gui_login._execute_locked", side_effect=run_locked),
        ):
            self.assertEqual(self.run_login("--gender", "male", "--timeout", "5"), {"phase": "character_list"})

    def test_observation_does_not_acquire_lock_or_input(self):
        stage = {"instance_id": "native", "client": {"run_id": "run"}, "stage": "LOGIN"}
        self.backend.read = lambda domain: stage
        with (
            patch("beidou_pilot.first_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.first_character.BridgeClient", return_value=self.native),
            patch("beidou_pilot.gui_login.execute") as execute,
            self.backend.paths.input_lock.open("a+") as lock,
        ):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_login(), stage)
            execute.assert_not_called()

    def test_headless_dispatch_unchanged(self):
        self.backend.name = "headless"
        with patch("beidou_pilot.first_character.execute", return_value={"phase": "character_list"}) as execute:
            self.assertEqual(self.run_login("--timeout", "5"), {"phase": "character_list"})
            self.assertEqual(execute.call_args.args[1].timeout, 5)
            self.run_login()
            self.assertEqual(execute.call_args.args[1].timeout, 0)
        with self.assertRaises(ClientError):
            self.run_login("--gender", "male")

    def test_action_default_timeout(self):
        with (
            patch("beidou_pilot.first_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.first_character.BridgeClient", return_value=self.native),
            patch("beidou_pilot.profile.load_account_profile", return_value="profile"),
            patch("beidou_pilot.gui_login.execute", return_value={}) as execute,
        ):
            self.run_login("--gender", "female")
            self.assertEqual(execute.call_args.kwargs["timeout"], 30)

    def test_observation_invalid_timeout(self):
        for value in ("-1", "nan"):
            with self.subTest(value=value), self.assertRaises(ClientError) as error:
                self.run_login("--timeout", value)
            self.assertEqual(error.exception.code, "usage")

    def test_observation_waits_for_character_list(self):
        stages = iter(
            [
                {"instance_id": "native", "client": {"run_id": "run"}, "stage": "LOGIN"},
                {
                    "instance_id": "native",
                    "client": {"run_id": "run"},
                    "stage": "CHARACTER_SELECT",
                    "login": {"characters_available": True, "characters": []},
                },
            ]
        )
        self.backend.read = lambda domain: next(stages)
        with (
            patch("beidou_pilot.first_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.first_character.BridgeClient", return_value=self.native),
            patch("beidou_pilot.first_character.time.sleep"),
        ):
            self.assertEqual(self.run_login("--timeout", "5")["login"]["characters"], [])

    def test_observation_timeout_does_not_input(self):
        self.backend.read = lambda domain: {"instance_id": "native", "client": {"run_id": "run"}, "stage": "LOGIN"}
        with (
            patch("beidou_pilot.first_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.first_character.BridgeClient", return_value=self.native),
            patch("beidou_pilot.gui_login.execute") as execute,
            patch("beidou_pilot.first_character.time.monotonic", side_effect=[0, 2]),
        ):
            with self.assertRaises(ClientError) as error:
                self.run_login("--timeout", "1")
            self.assertEqual(error.exception.code, "login_timeout")
            execute.assert_not_called()

    def test_terms_requires_gender(self):
        with self.assertRaises(ClientError):
            self.run_login("--accept-terms", "--timeout", "5")
