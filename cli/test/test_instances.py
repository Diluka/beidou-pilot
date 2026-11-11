"""本容器的实例身份与输入隔离；不以文件桥替身代替真实游戏效果。"""

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
from beidou_pilot.cli import control, main
from beidou_pilot.control_scripts import action
from beidou_pilot.errors import ClientError
from beidou_pilot.instances import InstancePaths
from beidou_pilot.observations import NativeObserver
from .test_bridge import BridgeFiles


class InstanceContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = self.instance("alpha")
        self.enterContext(patch.dict(os.environ, self.files.environment))

    def instance(self, name: str) -> BridgeFiles:
        files = BridgeFiles(self.root / name, "headless", name)
        files.environment.update(RUN_ID="run-" + name, HOSTNAME="container-" + name)
        files.register("headless", name)
        files.state.update(instance_id="native-" + name, run_id=files.environment["RUN_ID"])
        files.publish()
        return files

    def cli(self, *arguments: str):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(
                ["--root", str(self.files.root), "--backend", "headless", "--instance", "alpha", "--json", *arguments]
            )
        return code, json.loads(output.getvalue())

    def test_cli_keeps_its_container_identity_and_rejects_cross_instance_batch(self) -> None:
        code, report = self.cli("bridge", "status")
        self.assertEqual((0, "alpha", "native-alpha"), (code, report["instance"], report["data"]["instance_id"]))
        code, report = self.cli("--instance", "beta", "bridge", "status")
        self.assertEqual((2, "container_identity_changed"), (code, report["error"]["code"]))
        code, report = self.cli("--instance", "../peer", "status")
        self.assertEqual((2, "invalid_instance"), (code, report["error"]["code"]))
        batch = self.files.root / "batch.json"
        batch.write_text(json.dumps([["--instance", "beta", "walk", "right"]]))
        code, report = self.cli("batch", "--file", str(batch))
        self.assertEqual((2, "usage"), (code, report["error"]["code"]))

    def test_containers_share_lua_actions_with_separate_input_locks_and_bridges(self) -> None:
        peer = self.instance("beta")
        alpha = Backend(self.files.root, "headless", "alpha")
        with patch.dict(os.environ, peer.environment):
            beta = Backend(peer.root, "headless", "beta")
        with control(alpha, "walk"), control(beta, "face"):
            with self.assertRaises(ClientError) as busy:
                with control(alpha, "attack"):
                    self.fail("同一实例不能同时接受两个输入控制者")
        self.assertEqual("input_busy", busy.exception.code)
        calls = []

        def execute(bridge, source, *, seconds):
            calls.append((bridge.directory, source.read_text()))
            return {"last_state": self.files.state if bridge.root == self.files.root else peer.state}

        with patch.object(BridgeClient, "run_script", autospec=True, side_effect=execute):
            action(alpha, "move", direction="right", seconds=0.2)
            with patch.dict(os.environ, peer.environment):
                action(beta, "face", direction="left")
        self.assertEqual([self.files.directory, peer.directory], [directory for directory, _ in calls])
        self.assertNotEqual(alpha.paths.input_lock, beta.paths.input_lock)

    def test_container_close_directs_to_host_lifecycle_even_while_lua_owns_input(self) -> None:
        backend = Backend(self.files.root, "headless", "alpha")
        with control(backend, "script"):
            code, report = self.cli("close")
        self.assertEqual((2, "host_lifecycle_required"), (code, report["error"]["code"]))

    def test_observation_engine_uses_this_containers_named_bridge(self) -> None:
        with patch("beidou_pilot.backend.subprocess.run") as run:
            run.return_value.stdout = '{"quests": []}'
            self.assertEqual({"quests": []}, Backend(self.files.root, "headless", "alpha").read("quests"))
        self.assertEqual("alpha", run.call_args.kwargs["env"]["MAPLE_INSTANCE"])
        observer = NativeObserver(self.files.root, "headless", "alpha")
        self.assertEqual("native-alpha", observer.snapshot()["instance_id"])
        self.assertEqual(InstancePaths(self.files.root, "headless", "alpha").bridge, observer.directory)

    def test_open_rejects_retired_process_lifetime_before_login(self) -> None:
        account = self.files.root / "account.json"
        account.write_text(
            json.dumps({"username": "fixture", "password": "fixture", "character_id": 4, "max_seconds": 0})
        )
        account.chmod(0o600)
        with patch("beidou_pilot.headless.open_game") as open_client:
            code, report = self.cli("open", "--account", str(account))
        self.assertEqual((2, "profile_invalid"), (code, report["error"]["code"]))
        open_client.assert_not_called()

    def test_capabilities_preserve_unknown_until_native_state_is_published(self) -> None:
        (self.files.directory / "state.json").unlink()
        code, report = self.cli("capabilities")
        self.assertEqual(0, code)
        self.assertFalse(report["data"]["connected"])
        self.assertIsNone(report["data"]["native_actions"])
        self.files.state["capabilities"] = {"move": True, "raw_keys": False, "skill": False}
        self.files.publish()
        code, report = self.cli("capabilities")
        self.assertEqual(0, code)
        self.assertTrue(report["data"]["connected"])
        self.assertEqual(self.files.state["capabilities"], report["data"]["native_actions"])
        self.assertEqual(
            ["character", "interaction", "inventory", "quests", "scene", "stage"], report["data"]["observation_domains"]
        )


if __name__ == "__main__":
    unittest.main()
