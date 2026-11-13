import fcntl
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from beidou_pilot import cli
from beidou_pilot.errors import ClientError


class GuiCharacterCliTest(unittest.TestCase):
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
        self.runtime = SimpleNamespace(running=True, run_id="run", run_dir=root / "run")
        self.native = SimpleNamespace(
            directory=root / "bridge", snapshot=lambda: {"run_id": "run", "instance_id": "native"}
        )
        self.patches = [
            patch("beidou_pilot.first_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.first_character.BridgeClient", return_value=self.native),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def dispatch(self, *args):
        return cli.dispatch(self.backend, cli.parser().parse_args(["character", *args]))

    def create_args(self):
        return [
            "create",
            "--name",
            "Hero",
            "--gender",
            "female",
            "--timeout",
            "5",
            *sum(
                (
                    ["--" + key, "1"]
                    for key in ("job", "face", "hair", "hair-color", "skin", "top", "bottom", "shoes", "weapon")
                ),
                [],
            ),
        ]

    def test_create_holds_public_lock_and_uses_runtime_identity(self):
        def create(backend, params, **kwargs):
            with self.backend.paths.input_lock.open("a+") as lock:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertTrue(params.female)
            self.assertEqual(
                kwargs, {"directory": self.runtime.run_dir, "instance_id": "native", "run_id": "run", "timeout": 5}
            )
            return {"status": "unknown", "request_id": "a" * 32}

        with patch("beidou_pilot.gui_character.create_once", side_effect=create):
            self.assertEqual(self.dispatch(*self.create_args())["status"], "unknown")

    def test_real_character_lock_is_inside_public_lock(self):
        self.runtime.run_dir.mkdir()

        def inner(*args, **kwargs):
            for path in (self.backend.paths.input_lock, self.runtime.run_dir / "gui-character.lock"):
                with path.open("a+") as lock:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return {"status": "unknown"}

        with (
            patch("beidou_pilot.gui_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.gui_character._create_once_locked", side_effect=inner),
        ):
            self.assertEqual(self.dispatch(*self.create_args())["status"], "unknown")

    def test_gui_create_default_timeout_and_explicit_override(self):
        args = self.create_args()
        with patch("beidou_pilot.gui_character.create_once", return_value={"status": "unknown"}) as create:
            self.dispatch(*(args[:5] + args[7:]))
            self.assertEqual(create.call_args.kwargs["timeout"], 90)
            self.dispatch(*args)
            self.assertEqual(create.call_args.kwargs["timeout"], 5)

    def test_exited_run_recovers_attempt_identity_without_input(self):
        self.runtime.running = False
        self.runtime.run_dir.mkdir()
        record = {
            "protocol": 1,
            "operation": "create_character",
            "request_id": "a" * 32,
            "instance_id": "native",
            "run_id": "run",
        }
        (self.runtime.run_dir / "gui-character-attempt.json").write_text(json.dumps(record))
        with patch("beidou_pilot.gui_character.create_once") as create:
            with self.assertRaises(ClientError) as error:
                self.dispatch(*self.create_args())
            self.assertEqual(error.exception.code, "gui_character_already_attempted")
            self.assertEqual(
                error.exception.details, {key: record[key] for key in ("request_id", "instance_id", "run_id")}
            )
            create.assert_not_called()

    def test_exited_run_missing_or_mismatched_attempt_is_not_trusted(self):
        self.runtime.running = False
        self.runtime.run_dir.mkdir()
        path = self.runtime.run_dir / "gui-character-attempt.json"
        with patch("beidou_pilot.gui_character.create_once") as create:
            for record in (
                None,
                {
                    "protocol": 1,
                    "operation": "create_character",
                    "request_id": "a" * 32,
                    "instance_id": "native",
                    "run_id": "other",
                },
            ):
                if record is not None:
                    path.write_text(json.dumps(record))
                with self.assertRaises(ClientError) as error:
                    self.dispatch(*self.create_args())
                self.assertEqual(error.exception.code, "bridge_session_unavailable")
                self.assertEqual(error.exception.details, {})
            create.assert_not_called()

    def test_busy_create_does_not_submit(self):
        with (
            self.backend.paths.input_lock.open("a+") as lock,
            patch("beidou_pilot.gui_character.create_once") as create,
        ):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ClientError) as error:
                self.dispatch(*self.create_args())
            self.assertEqual(error.exception.code, "input_busy")
            create.assert_not_called()

    def test_result_is_read_only_and_uses_original_request(self):
        identity = {"request_id": "a" * 32, "instance_id": "native", "run_id": "run"}
        unknown = {**identity, "status": "unknown"}
        with (
            self.backend.paths.input_lock.open("a+") as lock,
            patch("beidou_pilot.gui_character.query_result", return_value=unknown) as query,
            patch("beidou_pilot.gui_character.observe_result", return_value=unknown) as observe,
            patch("beidou_pilot.gui_character.create_once") as create,
        ):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(
                self.dispatch("result", identity["request_id"], "--instance-id", "native", "--run-id", "run"), unknown
            )
            query.assert_called_once_with(self.native.directory, **identity)
            observe.assert_called_once_with(
                self.backend,
                directory=self.runtime.run_dir,
                bridge_directory=self.native.directory,
                timeout=1,
                **identity,
            )
            create.assert_not_called()

    def test_result_real_observer_can_complete_after_two_samples(self):
        identity = {"request_id": "a" * 32, "instance_id": "native", "run_id": "run"}
        unknown = {**identity, "status": "unknown"}
        completed = {**identity, "status": "completed", "character_id": 42}
        stage = {"instance_id": "native", "client": {"run_id": "run"}, "stage": "CHARACTER_SELECT", "login": {}}
        self.backend.read = lambda domain: stage
        with (
            patch("beidou_pilot.gui_character.query_result", return_value=unknown),
            patch("beidou_pilot.gui_character.load_runtime", return_value=self.runtime),
            patch("beidou_pilot.gui_character.BridgeClient", return_value=self.native),
            patch("beidou_pilot.gui_character.persist_result", return_value=completed) as persist,
            patch("beidou_pilot.gui_character.time.sleep"),
            patch("beidou_pilot.gui_character.time.monotonic", return_value=0),
        ):
            self.assertEqual(
                self.dispatch("result", identity["request_id"], "--instance-id", "native", "--run-id", "run"), completed
            )
            persist.assert_called_once_with(
                self.runtime.run_dir, bridge_directory=self.native.directory, state=stage, **identity
            )

    def test_old_run_result_never_observes_current_run(self):
        unknown = {"status": "unknown", "request_id": "a" * 32, "instance_id": "native", "run_id": "old"}
        with (
            patch("beidou_pilot.gui_character.query_result", return_value=unknown),
            patch("beidou_pilot.gui_character.observe_result") as observe,
        ):
            self.assertEqual(
                self.dispatch("result", "a" * 32, "--instance-id", "native", "--run-id", "old"),
                {**unknown, "last_observed_status": "unknown"},
            )
            observe.assert_not_called()

    def test_accepted_old_or_unavailable_run_is_unknown(self):
        identity = {"request_id": "a" * 32, "instance_id": "native", "run_id": "old"}
        with (
            patch("beidou_pilot.gui_character.query_result", return_value={**identity, "status": "accepted"}),
            patch("beidou_pilot.gui_character.observe_result") as observe,
        ):
            args = ("result", identity["request_id"], "--instance-id", "native", "--run-id", "old")
            expected = {**identity, "status": "unknown", "last_observed_status": "accepted"}
            self.assertEqual(self.dispatch(*args), expected)
            with patch(
                "beidou_pilot.first_character.load_runtime",
                side_effect=ClientError("container_runtime_unavailable", "offline"),
            ):
                self.assertEqual(self.dispatch(*args), expected)
            observe.assert_not_called()

    def test_accepted_when_bridge_unavailable_is_unknown(self):
        identity = {"request_id": "a" * 32, "instance_id": "native", "run_id": "run"}
        self.native.snapshot = lambda: (_ for _ in ()).throw(ClientError("bridge_unavailable", "offline"))
        with (
            patch("beidou_pilot.gui_character.query_result", return_value={**identity, "status": "accepted"}),
            patch("beidou_pilot.gui_character.observe_result") as observe,
        ):
            result = self.dispatch("result", identity["request_id"], "--instance-id", "native", "--run-id", "run")
            self.assertEqual(result, {**identity, "status": "unknown", "last_observed_status": "accepted"})
            observe.assert_not_called()
