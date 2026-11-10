"""命名实例的公共消费合同；文件桥和容器替身不代表真实游戏效果。"""

from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from beidou_pilot.backend import Backend
from beidou_pilot.bridge import BridgeClient
from beidou_pilot.cli import control, main
from beidou_pilot.control_scripts import action
from beidou_pilot.errors import ClientError
from beidou_pilot.headless import close_game, open_game, status
from beidou_pilot.instances import InstancePaths
from beidou_pilot.observations import NativeObserver
from beidou_pilot.resources import ResourcePaths
from .test_bridge import BridgeFiles


class InstanceContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = BridgeFiles(self.root)
        (self.root / "clientctl.py").touch()

    def write_instance(self, name: str):
        paths = InstancePaths(self.root, "headless", name)
        directory = paths.runs / ("run-" + name)
        directory.mkdir(parents=True)
        paths.bridge.mkdir(parents=True)
        paths.registration.parent.mkdir(parents=True, exist_ok=True)
        record = {"container_id": "container-" + name, "run_id": "run-" + name,
                  "image": "sha256:image", "run_dir": str(directory), "character_id": 6,
                  "world": 0, "channel": 1, "instance": name, "target_container_id": "server-" + name}
        paths.registration.write_text(json.dumps(record))
        sampled = {**deepcopy(self.files.state), "instance_id": "native-" + name, "run_id": record["run_id"]}
        (paths.bridge / "state.json").write_text(json.dumps(sampled))
        return paths, record, sampled

    def cli(self, *arguments: str):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--root", str(self.root), "--backend", "headless", "--json", *arguments])
        return code, json.loads(output.getvalue())

    def test_cli_selects_named_instance_and_rejects_unsafe_or_cross_instance_batch(self) -> None:
        self.write_instance("alpha")
        self.write_instance("beta")
        for words in (("--instance", "alpha", "bridge", "status"),
                      ("bridge", "status", "--instance", "beta")):
            code, report = self.cli(*words)
            selected = words[1] if words[0] == "--instance" else words[-1]
            self.assertEqual(0, code)
            self.assertEqual(selected, report["instance"])
            self.assertEqual("native-" + selected, report["data"]["instance_id"])
        code, report = self.cli("--instance", "../peer", "status")
        self.assertEqual((2, "invalid_instance"), (code, report["error"]["code"]))
        batch = self.root / "batch.json"
        batch.write_text(json.dumps([["--instance", "beta", "walk", "right"]]))
        code, report = self.cli("--instance", "alpha", "batch", "--file", str(batch))
        self.assertEqual((2, "usage"), (code, report["error"]["code"]))

    def test_named_controls_share_lua_actions_with_separate_input_locks_and_bridges(self) -> None:
        alpha, _, first = self.write_instance("alpha")
        beta, _, second = self.write_instance("beta")
        backends = [Backend(self.root, "headless", name) for name in ("alpha", "beta")]
        with control(backends[0], "walk"), control(backends[1], "face"):
            with self.assertRaises(ClientError) as busy:
                with control(backends[0], "attack"):
                    self.fail("同一实例不能同时接受两个输入控制者")
        self.assertEqual("input_busy", busy.exception.code)
        calls = []

        def execute(bridge, source, *, seconds):
            calls.append((bridge.directory, source.read_text()))
            return {"last_state": first if bridge.directory == alpha.bridge else second}

        with patch.object(BridgeClient, "run_script", autospec=True, side_effect=execute):
            action(backends[0], "move", direction="right", seconds=.2)
            action(backends[1], "face", direction="left")
        self.assertEqual([alpha.bridge, beta.bridge], [directory for directory, _ in calls])
        self.assertNotEqual(alpha.input_lock, beta.input_lock)

    def test_close_can_stop_the_container_while_lua_owns_input(self) -> None:
        self.write_instance("alpha")
        backend = Backend(self.root, "headless", "alpha")
        with control(backend, "script"), patch("beidou_pilot.headless.close_game", return_value={"status": "closed"}) as close:
            code, report = self.cli("--instance", "alpha", "close")
        self.assertEqual((0, "closed"), (code, report["data"]["status"]))
        close.assert_called_once_with(self.root, "alpha")

    def test_observation_subprocess_and_native_session_keep_the_selected_instance(self) -> None:
        self.write_instance("alpha")
        paths, record, _ = self.write_instance("beta")
        with patch("beidou_pilot.backend.subprocess.run") as run:
            run.return_value.stdout = '{"quests": []}'
            self.assertEqual({"quests": []}, Backend(self.root, "headless", "beta").read("quests"))
        self.assertEqual("beta", run.call_args.kwargs["env"]["MAPLE_INSTANCE"])
        container = {"Id": record["container_id"], "Image": record["image"],
                     "HostConfig": {"Privileged": False, "PortBindings": {}, "NetworkMode": "isolated"},
                     "Config": {"Labels": {"beidou.client.instance": "beta"}}}
        with patch("beidou_pilot.observations._docker", side_effect=[record["container_id"] + "\n",
                                                                json.dumps([container])]) as docker:
            observer = NativeObserver(self.root, "headless", "beta")
            self.assertEqual("native-beta", observer.snapshot()["instance_id"])
        self.assertIn("id=" + record["container_id"], docker.call_args_list[0].args)
        self.assertEqual(paths.bridge, observer.directory)

    def test_closing_one_instance_archives_its_reason_and_preserves_the_peer(self) -> None:
        alpha, record, _ = self.write_instance("alpha")
        beta, _, _ = self.write_instance("beta")
        peer_registration = beta.registration.read_bytes()
        stopped = {"Running": False, "Pid": 0, "ExitCode": 0, "FinishedAt": "2026-11-09T00:00:00Z"}
        calls = []

        def docker(*arguments):
            calls.append(arguments)
            return json.dumps([{"State": stopped}]) if arguments[0] == "inspect" else ""

        with patch("beidou_pilot.headless.current_container", return_value={"Id": record["container_id"],
                                                                        "State": {"Running": True}}):
            with patch("beidou_pilot.headless.docker", side_effect=docker):
                with patch("beidou_pilot.headless.subprocess.run", return_value=subprocess.CompletedProcess(
                        [], 0, '{"event":"closed","reason":"sigterm"}\n', "")):
                    closed = close_game(self.root, "alpha")
        self.assertEqual("sigterm", closed["stop_reason"])
        self.assertEqual(0, closed["exit_code"])
        self.assertIn(("stop", "--time", "10", record["container_id"]), calls)
        self.assertIn(("rm", record["container_id"]), calls)
        self.assertEqual(peer_registration, beta.registration.read_bytes())
        self.assertEqual("sigterm", json.loads((Path(record["run_dir"]) / "exit.json").read_text())["stop_reason"])
        self.assertEqual("native-beta", BridgeClient(self.root, "headless", "beta").snapshot()["instance_id"])

    def test_stopped_status_and_reopen_preserve_the_previous_run_before_registration_changes(self) -> None:
        paths, record, sampled = self.write_instance("alpha")
        old_run = Path(record["run_dir"])
        stopped = {"Id": record["container_id"],
                   "State": {"Running": False, "Pid": 0, "ExitCode": 2, "FinishedAt": "2026-11-09T00:00:00Z"}}
        target = self.root / "target.json"
        target.write_text('{"project":"isolated"}')
        profile = self.root / "profile.json"
        profile.write_text('{"username":"fixture","password":"fixture","character_id":6}')
        profile.chmod(0o600)
        resources = self.root / "resources"
        resources.mkdir()
        planned = {"running": True, "ip": "10.0.0.2", "network": "isolated", "container_id": "server-alpha"}
        commands = []

        def run(arguments, **options):
            output = ('{"event":"closed","reason":"disconnected"}\n' if arguments[0] == "docker"
                      else json.dumps(planned))
            return subprocess.CompletedProcess(arguments, 0, output, "")

        def docker(*arguments):
            commands.append(arguments)
            if arguments[0] == "inspect":
                return json.dumps([stopped])
            if arguments[0] == "image":
                return "sha256:image\n"
            if arguments[0] == "run":
                return "new-alpha\n"
            return ""

        with patch("beidou_pilot.headless.subprocess.run", side_effect=run):
            with patch("beidou_pilot.headless.current_container", return_value=stopped):
                observed = status(self.root, "alpha")
            self.assertEqual(("STOPPED", 2, "disconnected"),
                             (observed["stage"], observed["exit_code"], observed["stop_reason"]))
            with patch("beidou_pilot.headless.current_container", side_effect=[stopped, stopped,
                    {"Id": "new-alpha", "State": {"Running": True}}]):
                with patch("beidou_pilot.headless.docker", side_effect=docker):
                    with patch("beidou_pilot.headless.load_resources", return_value=ResourcePaths(
                            metadata_root=resources, headless_resources=resources,
                            gui_client=resources, gui_dll=resources / "ijl15.dll", config_file=None)):
                        with patch.object(BridgeClient, "snapshot", return_value=sampled):
                            opened = open_game(self.root, target=target, profile=profile, instance="alpha")
        self.assertTrue(opened["ready"])
        self.assertEqual("new-alpha", json.loads(paths.registration.read_text())["container_id"])
        previous = json.loads((old_run / "exit.json").read_text())
        self.assertEqual((2, "disconnected"), (previous["exit_code"], previous["stop_reason"]))
        self.assertNotEqual(old_run, Path(opened["run_dir"]))
        self.assertLess(commands.index(("rm", record["container_id"])),
                        next(index for index, command in enumerate(commands) if command[0] == "run"))
        launched = next(command for command in commands if command[0] == "run")
        self.assertEqual("-d", launched[1])
        self.assertIn(("image", "inspect", "local/beidou-pilot:local", "--format", "{{.Id}}"), commands)
        self.assertNotIn("max_seconds", json.loads((Path(opened["run_dir"]) / "runtime.private.json").read_text()))

    def test_open_rejects_retired_process_lifetime_before_starting_a_container(self) -> None:
        profile = self.root / "profile.json"
        profile.write_text(json.dumps({"username": "fixture", "password": "fixture", "character_id": 6,
                                       "max_seconds": 0}))
        profile.chmod(0o600)
        with patch("beidou_pilot.headless.docker") as docker:
            with self.assertRaises(ClientError) as failure:
                open_game(self.root, target=self.root / "target.json", profile=profile, instance="alpha")
        self.assertEqual("headless_profile_invalid", failure.exception.code)
        docker.assert_not_called()

    def test_capabilities_report_offline_unknown_and_online_native_values(self) -> None:
        code, report = self.cli("--instance", "alpha", "capabilities")
        self.assertEqual(0, code)
        self.assertFalse(report["data"]["connected"])
        self.assertIsNone(report["data"]["native_actions"])
        paths, _, sampled = self.write_instance("alpha")
        sampled["capabilities"] = {"move": True, "raw_keys": False, "skill": False}
        (paths.bridge / "state.json").write_text(json.dumps(sampled))
        code, report = self.cli("--instance", "alpha", "capabilities")
        self.assertEqual(0, code)
        self.assertTrue(report["data"]["connected"])
        self.assertEqual(sampled["capabilities"], report["data"]["native_actions"])
        self.assertEqual(["character", "interaction", "inventory", "quests", "scene", "stage"],
                         report["data"]["observation_domains"])

    def test_concurrent_open_cannot_start_the_same_character_twice(self) -> None:
        target = self.root / "target.json"
        target.write_text('{"project":"isolated"}')
        profile = self.root / "profile.json"
        profile.write_text('{"username":"fixture","password":"fixture","character_id":6}')
        profile.chmod(0o600)
        resources = self.root / "resources"
        resources.mkdir()
        planned = {"running": True, "ip": "10.0.0.2", "network": "isolated", "container_id": "same-server"}
        planning = threading.Barrier(2)
        containers = {}
        launches = []

        def plan(arguments, **options):
            planning.wait(timeout=1)
            return subprocess.CompletedProcess(arguments, 0, json.dumps(planned), "")

        def docker(*arguments):
            if arguments[0] == "ps":
                identifier = next((word.removeprefix("id=") for word in arguments if word.startswith("id=")), None)
                return identifier + "\n" if identifier in containers else ""
            if arguments[0] == "inspect":
                return json.dumps([containers[arguments[1]]])
            if arguments[0] == "image":
                return "sha256:image\n"
            self.assertEqual("run", arguments[0])
            instance = next(word.split("=", 1)[1] for word in arguments
                            if word.startswith("beidou.client.instance="))
            launches.append(instance)
            # Docker创建并返回ID需要时间；两个请求已在目标规划边界同时就绪。
            time.sleep(.03)
            config = next(word.removesuffix(":/run/headless-config.json:ro") for word in arguments
                          if word.endswith(":/run/headless-config.json:ro"))
            configured = json.loads(Path(config).read_text())
            paths = InstancePaths(self.root, "headless", instance)
            sampled = {**deepcopy(self.files.state), "instance_id": "native-" + instance,
                       "run_id": configured["run_id"], "observed_at_ms": int(time.time() * 1000)}
            (paths.bridge / "state.json").write_text(json.dumps(sampled))
            identifier = "container-" + instance
            containers[identifier] = {"Id": identifier, "Image": "sha256:image", "State": {"Running": True},
                                     "Config": {"Labels": {"beidou.task": "maple-headless-maintained",
                                                           "beidou.client.root": str(self.root),
                                                           "beidou.client.instance": instance}},
                                     "HostConfig": {"Privileged": False, "PortBindings": {}, "NetworkMode": "isolated"}}
            return identifier + "\n"

        def attempt(instance):
            try:
                return open_game(self.root, target=target, profile=profile, instance=instance)
            except ClientError as error:
                return error.code

        with patch("beidou_pilot.headless.subprocess.run", side_effect=plan):
            with patch("beidou_pilot.headless.docker", side_effect=docker):
                with patch("beidou_pilot.headless.load_resources", return_value=ResourcePaths(
                        metadata_root=resources, headless_resources=resources,
                        gui_client=resources, gui_dll=resources / "ijl15.dll", config_file=None)):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        pending = [pool.submit(attempt, instance) for instance in ("alpha", "beta")]
                        results = [future.result(timeout=3) for future in pending]
        self.assertEqual(1, len(launches))
        self.assertEqual(1, sum(isinstance(result, dict) and result["ready"] for result in results))
        self.assertIn("character_already_controlled", results)


if __name__ == "__main__":
    unittest.main()
