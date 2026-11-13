import fcntl
import json
from pathlib import Path
import tempfile
import time
import unittest

from beidou_pilot.errors import ClientError
from beidou_pilot.login_bridge import LoginBridge
from beidou_pilot.profile import CharacterCreation


class LoginBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bridge = LoginBridge(self.directory, "instance", "run")
        self.state = {"protocol": 1, "instance_id": "instance", "run_id": "run", "seq": 1,
                      "observed_at_ms": int(time.time() * 1000), "phase": "character_list", "characters": [],
                      "pending_request_id": None}
        self.write("login-state.json", self.state)
        self.params = CharacterCreation("测试", 0, 1, 2, 8, 3, 4, 5, 6, 7, False)

    def write(self, name, value):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_submit_and_lookup(self):
        self.assertEqual(self.bridge.snapshot()["characters"], [])
        request = self.bridge.submit(self.params)
        command = json.loads((self.directory / "login-command.json").read_text())
        self.assertEqual(command["request_id"], request)
        self.assertEqual(command["operation"], "create_character")
        self.assertEqual(command["params"]["name"], "测试")
        self.assertEqual(command["params"]["hair"], 2)
        self.assertEqual(command["params"]["hair_color"], 8)
        self.assertEqual(self.bridge.result(request)["status"], "unknown")
        self.write("login-results/" + request + ".json", {"protocol": 1, "instance_id": "instance", "run_id": "run",
                   "request_id": request, "operation": "create_character", "status": "completed", "character_id": 42})
        self.assertEqual(self.bridge.result(request)["character_id"], 42)
        self.assertEqual(json.loads((self.directory / "login-command.json").read_text()), command)

    def test_identity_and_staleness_block_submission(self):
        for key, value in (("run_id", "other"), ("instance_id", "other"), ("observed_at_ms", 0)):
            state = dict(self.state, **{key: value})
            self.write("login-state.json", state)
            with self.assertRaises(ClientError):
                self.bridge.submit(self.params)
            self.assertFalse((self.directory / "login-command.json").exists())

    def test_single_slot_and_pending_are_never_overwritten(self):
        request = self.bridge.submit(self.params)
        original = (self.directory / "login-command.json").read_bytes()
        with self.assertRaises(ClientError):
            self.bridge.submit(self.params)
        self.assertEqual((self.directory / "login-command.json").read_bytes(), original)
        (self.directory / "login-command.json").unlink()
        self.write("login-state.json", dict(self.state, pending_request_id=request))
        with self.assertRaises(ClientError):
            self.bridge.submit(self.params)
        missing = dict(self.state)
        del missing["pending_request_id"]
        self.write("login-state.json", missing)
        with self.assertRaises(ClientError):
            self.bridge.submit(self.params)
        self.assertFalse((self.directory / "login-command.json").exists())

    def test_character_list_must_be_known_and_ready(self):
        for state in (dict(self.state, phase="connecting"), dict(self.state, characters=None)):
            self.write("login-state.json", state)
            with self.assertRaises(ClientError):
                self.bridge.submit(self.params)
            self.assertFalse((self.directory / "login-command.json").exists())
        self.assertIsNone(self.bridge.snapshot()["characters"])

    def test_completed_requires_positive_int32_character_id(self):
        request = "b" * 32
        for character_id in (None, True, 0, -1, 2**31):
            self.write("login-results/" + request + ".json", {"protocol": 1, "instance_id": "instance", "run_id": "run",
                       "request_id": request, "operation": "create_character", "status": "completed", "character_id": character_id})
            with self.assertRaises(ClientError):
                self.bridge.result(request)

    def test_result_identity_and_path_validation(self):
        request = "a" * 32
        self.write("login-results/" + request + ".json", {"protocol": 1, "instance_id": "other", "run_id": "run",
                   "request_id": request, "operation": "create_character", "status": "completed"})
        with self.assertRaises(ClientError):
            self.bridge.result(request)
        with self.assertRaises(ClientError):
            self.bridge.result("../bad")

    def test_lock_excludes_other_submitter(self):
        with (self.directory / "login.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(ClientError):
                self.bridge.submit(self.params)
        self.assertFalse((self.directory / "login-command.json").exists())


if __name__ == "__main__":
    unittest.main()
