"""原生观察消费合同；文件对端只验证 IPC，不代表游戏效果。"""

from contextlib import contextmanager
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.engines.observe import read_observation
from beidou_pilot.engines.stage import read_stage
from beidou_pilot.errors import ClientError
from beidou_pilot.observations import NativeObserver, Session, active_session


class NativeObservationContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "clientctl.py").touch()
        self.directory = self.root / "runtime/bridge"
        self.directory.mkdir(parents=True)
        self.session = Session("container", "run", self.root / "runtime/runs/run", "beidou", "sha256:image")
        self.state = {"protocol": 1, "run_id": "run", "instance_id": "native-1", "seq": 1,
                      "scene_generation": 1, "observed_at_ms": int(time.time() * 1000),
                      "ready": True, "map_id": 100, "character": {"id": 6},
                      "position": {"x": 10, "y": 20}, "held_keys": [], "command": {"status": "running"}}
        (self.directory / "state.json").write_text(json.dumps(self.state))

    @contextmanager
    def responder(self, data, *, status="ok", override=None):
        stop = threading.Event()

        def respond():
            request = self.directory / "observation-request.txt"
            while not stop.wait(.001):
                if request.is_file():
                    _, instance, request_id, domain = request.read_text().split()
                    response = {**self.state, "instance_id": instance, "request_id": request_id,
                                "domain": domain, "status": status, "data": data, "error": None,
                                **(override or {})}
                    temporary = self.directory / "response.tmp"
                    temporary.write_text(json.dumps(response))
                    temporary.replace(self.directory / "observation.json")
                    return

        thread = threading.Thread(target=respond)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join()

    def test_read_lane_preserves_running_control_and_normalizes_real_validation(self) -> None:
        command = self.directory / "command.txt"
        command.write_text("running Lua command\n")
        domain = {"items": [], "checksums_valid": True, "unavailable": []}
        with patch("beidou_pilot.observations.active_session", return_value=self.session):
            observer = NativeObserver(self.root)
            with self.responder(domain):
                result = observer.observe("inventory", timeout=.2)
        self.assertTrue(result["native_values_valid"])
        self.assertTrue(result["checksums_valid"])
        self.assertEqual("client-native-api", result["source"])
        self.assertEqual("running Lua command\n", command.read_text())
        self.assertEqual("running", json.loads((self.directory / "state.json").read_text())["command"]["status"])

    def test_headless_preserves_unknown_checksum_and_snapshot_data_source(self) -> None:
        with patch("beidou_pilot.observations.active_session", return_value=self.session):
            observer = NativeObserver(self.root, "headless")
            observer.directory = self.directory
            domain = {"items": [], "checksums_valid": None, "native_values_valid": True,
                      "source": "character_data_snapshot", "live_updates": False}
            with self.responder(domain):
                result = observer.observe("inventory", timeout=.2)
            sampled = read_observation(observer)
        self.assertTrue(result["native_values_valid"])
        self.assertIsNone(result["checksums_valid"])
        self.assertEqual("character_data_snapshot", result["data_source"])
        self.assertFalse(result["live_updates"])
        self.assertTrue(sampled["native_values_valid"])
        self.assertIsNone(sampled["map_checksum_valid"])
        self.assertIsNone(sampled["character_checksum_valid"])

    def test_response_must_belong_to_current_instance_run_and_domain(self) -> None:
        with patch("beidou_pilot.observations.active_session", return_value=self.session):
            observer = NativeObserver(self.root)
            for override in ({"instance_id": "other"}, {"run_id": "other"}, {"domain": "quests"}):
                with self.subTest(override=override):
                    (self.directory / "observation-request.txt").unlink(missing_ok=True)
                    with self.responder({}, override=override), self.assertRaises(ClientError) as failure:
                        observer.observe("scene", timeout=.2)
                    self.assertEqual("native_observation_invalid", failure.exception.code)

    def test_unsupported_and_no_response_are_explicit_and_bounded(self) -> None:
        with patch("beidou_pilot.observations.active_session", return_value=self.session):
            observer = NativeObserver(self.root)
            with self.responder({}, status="unsupported"), self.assertRaises(ClientError) as failure:
                observer.observe("ui", timeout=.2)
            self.assertEqual("unsupported_capability", failure.exception.code)
            with self.assertRaises(ClientError) as failure:
                observer.observe("scene", timeout=.03)
            self.assertEqual("native_observation_timeout", failure.exception.code)

    def test_login_bootstrap_does_not_require_a_registered_maple_session(self) -> None:
        container = {"Id": "container", "Image": "sha256:image",
                     "HostConfig": {"Privileged": False, "PortBindings": {}, "NetworkMode": "isolated"},
                     "Config": {"Env": ["RUN_ID=first-launch"]}}
        with patch("beidou_pilot.observations._docker", side_effect=["container\n", json.dumps([container])]):
            with patch("beidou_pilot.observations.verify_binaries", return_value=True):
                session = active_session(self.root, "beidou")
        self.assertEqual("first-launch", session.run_id)
        session.run_dir.mkdir(parents=True)
        (session.run_dir / "renderer.log").write_text(
            "OpenGL renderer string: Mesa Intel(R) Graphics (ADL GT2)\n")
        with patch("beidou_pilot.observations.active_session", return_value=None):
            self.assertEqual("STOPPED", read_stage(self.root)["stage"])
        with patch("beidou_pilot.observations.active_session", return_value=session):
            with patch.object(NativeObserver, "observe", side_effect=ClientError("native_observation_not_ready", "starting")):
                with patch("beidou_pilot.engines.stage.project_geometry", side_effect=lambda report: report):
                    stage = read_stage(self.root)
        self.assertEqual("STARTING", stage["stage"])
        self.assertTrue(stage["running"])
        self.assertEqual("intel", stage["renderer"])

    def test_backend_forwards_selected_backend_to_observation_engine(self) -> None:
        with patch("beidou_pilot.backend.subprocess.run") as run:
            run.return_value.stdout = '{"quests": []}'
            self.assertEqual({"quests": []}, Backend(self.root, "headless").read("quests"))
        self.assertEqual("headless", run.call_args.kwargs["env"]["MAPLE_BACKEND"])


if __name__ == "__main__":
    unittest.main()
