"""原生桥文件IPC的消费合同；不以协议对端替身证明游戏动作。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from beidou_pilot.bridge import BridgeClient, BridgeSnapshot
from beidou_pilot.cli import main
from beidou_pilot.errors import ClientError
from beidou_pilot.instances import InstancePaths


class BridgeFiles:
    def __init__(self, root: Path, backend: str = "beidou", instance: str = "default") -> None:
        self.root = root
        self.environment = {"RUN_ID": "bridge-contract", "HOSTNAME": "bridge-container"}
        self.register(backend, instance)
        self.state: BridgeSnapshot = {
            "protocol": 1, "instance_id": "client-1", "pid": 123, "run_id": "bridge-contract",
            "seq": 0, "observed_at_ms": 0, "scene_generation": 1, "ready": True, "map_id": 100,
            "character": {"id": 4, "name": "Fixture", "level": 10, "job": 100,
                          "hp": 100, "max_hp": 100, "mp": 20, "max_mp": 20,
                          "strength": 20, "dexterity": 10, "intelligence": 4, "luck": 4,
                          "ability_points": 0, "skill_points": 0, "experience": 123},
            "position": {"x": 10, "y": 20}, "held_keys": [],
            "command": {"id": None, "status": "idle", "reason": None},
            "rejected_command": None, "input_events": 0,
        }
        self.publish()

    def register(self, backend: str = "beidou", instance: str = "default") -> None:
        self.environment.update(MAPLE_BACKEND=backend, MAPLE_INSTANCE=instance)
        paths = InstancePaths(self.root, backend, instance)
        self.directory = paths.bridge
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.root / "state").mkdir(exist_ok=True)
        paths.state_directory.mkdir(parents=True, exist_ok=True)
        run_dir = paths.runs / self.environment["RUN_ID"]
        run_dir.mkdir(parents=True, exist_ok=True)
        self.runtime = {
            "backend": backend, "instance": instance, "run_id": self.environment["RUN_ID"],
            "container_id": self.environment["HOSTNAME"], "image": "sha256:image",
            "source_revision": "fixture-revision", "pid": os.getpid(), "run_dir": str(run_dir),
            "character_id": 4, "world": 0, "channel": 0,
            "target": {"project": "isolated", "service": "app", "network": "isolated", "expected_image": "sha256:server"},
            "target_ip": "10.0.0.2", "target_container_id": "server", "started_at": "2026-11-11T00:00:00Z",
        }
        (self.root / "state/container.json").write_text(json.dumps(self.runtime))

    def publish(self, age: float = 0) -> None:
        self.state["seq"] += 1
        self.state["observed_at_ms"] = int((time.time() - age) * 1000)
        temporary = self.directory / "native-state.tmp"
        temporary.write_text(json.dumps(self.state))
        temporary.replace(self.directory / "state.json")

    def command(self, previous_id: str | None = None) -> list[str]:
        until = time.monotonic() + 3
        while time.monotonic() < until:
            try:
                fields = (self.directory / "command.txt").read_text(encoding="ascii").split()
            except FileNotFoundError:
                fields = []
            if fields and fields[3] != previous_id:
                return fields
            time.sleep(0.005)
        raise AssertionError("未收到期望的桥接命令")

    def complete_stop(self, original_id: str) -> list[str]:
        command = self.command(original_id)
        if command[4:] != ["stop", "0"]:
            raise AssertionError("取消后应发送独立stop命令")
        self.state["held_keys"] = []
        self.state["command"] = {"id": command[3], "status": "completed", "reason": None}
        self.state["input_events"] += 1
        self.publish()
        return command


class BridgeContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = BridgeFiles(Path(temporary.name))
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.files.state["script"] = None
        self.files.publish()
        self.client = BridgeClient(self.files.root)
        self.path = self.files.root / "control.lua"
        self.path.write_text("game.sleep(0.1)\n", encoding="utf-8")

    def publish_running(self, command: list[str]) -> None:
        self.files.state["command"] = {"id": command[3], "status": "running", "reason": None}
        self.files.state["script"] = {"id": command[6], "status": "running", "reason": None,
                                      "error": None, "resumes": 1, "budget_yields": 0,
                                      "last_resume_us": 1.0, "max_resume_us": 1.0}
        self.files.state["held_keys"] = [39]
        self.files.publish()

    def test_cli_preserves_inline_and_current_file_bytes_on_selected_instance(self) -> None:
        code = 'game.log("中文 \\"引号\\"")\r\ngame.sleep(0)\n'
        first_file = b'game.log("first")\r\n'
        changed_file = 'game.log("文件已更新")\n'.encode("utf-8")
        cases = [
            ("beidou", "default", ["--code", code, "--seconds", "1.25"], code.encode("utf-8"), 1250, None),
            ("headless", "alpha", ["--code", code, "--continuous"], code.encode("utf-8"), 0, None),
            ("beidou", "default", [str(self.path)], first_file, 30000, str(self.path)),
            ("headless", "alpha", [str(self.path), "--continuous"], changed_file, 0, str(self.path)),
        ]
        for backend, instance, arguments, expected_source, milliseconds, script_file in cases:
            with self.subTest(backend=backend, arguments=arguments):
                if script_file is not None:
                    self.path.write_bytes(expected_source)
                paths = InstancePaths(self.files.root, backend, instance)
                self.files.register(backend, instance)
                self.files.state["instance_id"] = backend + "-" + instance
                self.files.publish()
                (paths.bridge / "command.txt").unlink(missing_ok=True)

                def peer() -> tuple[list[str], bytes]:
                    command = self.files.command()
                    source = (self.files.directory / "scripts" / (command[6] + ".lua")).read_bytes()
                    self.publish_running(command)
                    self.files.state["held_keys"] = []
                    self.files.state["command"]["status"] = "completed"
                    self.files.state["script"]["status"] = "completed"
                    self.files.publish()
                    return command, source

                output = io.StringIO()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    native = pool.submit(peer)
                    with redirect_stdout(output):
                        exit_code = main(["--root", str(self.files.root), "--backend", backend,
                                          "--instance", instance, "--json", "script", "run", *arguments])
                    command, published_source = native.result(3)
                report = json.loads(output.getvalue())
                self.assertEqual(0, exit_code, report)
                self.assertEqual((0, backend, instance), (exit_code, report["backend"], report["instance"]))
                self.assertEqual([1, backend + "-" + instance, "script", milliseconds],
                                 [int(command[0]), command[1], command[4], int(command[5])])
                self.assertEqual(expected_source, published_source)
                self.assertEqual(script_file, report["data"]["script_file"])
                self.assertEqual(milliseconds == 0, report["data"]["continuous"])
                self.assertEqual("completed", report["data"]["status"])

    def test_cli_rejects_missing_or_conflicting_script_inputs(self) -> None:
        for arguments in (["run"], ["run", str(self.path), "--code", "game.sleep(0)"],
                          ["status", str(self.path)], ["status", "--code", "game.sleep(0)"]):
            with self.subTest(arguments=arguments):
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = main(["--root", str(self.files.root), "--json", "script", *arguments])
                self.assertEqual((2, "usage"), (exit_code, json.loads(output.getvalue())["error"]["code"]))
        self.assertFalse((self.files.directory / "command.txt").exists())

    def test_scene_loading_pause_can_resume_within_the_script_deadline(self) -> None:
        def peer() -> str:
            command = self.files.command()
            self.publish_running(command)
            # 真实换图暂停采样；恢复后的状态仍归属于同一原生进程和脚本。
            time.sleep(1.1)
            self.files.state["scene_generation"] = 2
            self.files.state["map_id"] = 200
            self.files.state["held_keys"] = []
            self.files.state["command"]["status"] = "completed"
            self.files.state["script"]["status"] = "completed"
            self.files.publish()
            return command[3]

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            report = self.client.run_script(self.path, seconds=2, timeout=3)
            request_id = native.result(3)
        self.assertEqual(report["request_id"], request_id)
        self.assertEqual(report["status"], "completed")
        self.assertEqual(report["last_state"]["scene_generation"], 2)
        self.assertEqual(report["last_state"]["held_keys"], [])

    def test_timeout_preserves_error_after_confirmed_script_stop(self) -> None:
        def peer() -> None:
            command = self.files.command()
            self.publish_running(command)
            self.files.command(command[3])
            self.files.state["script"]["status"] = "cancelled"
            self.files.state["script"]["reason"] = "stop_requested"
            self.files.complete_stop(command[3])

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            with self.assertRaises(ClientError) as failure:
                self.client.run_script(code="game.move('right', 1)", seconds=1, timeout=.04)
            native.result(2)
        self.assertEqual(failure.exception.code, "bridge_timeout")
        self.assertEqual(failure.exception.details["cleanup"]["held_keys"], [])
        self.assertEqual(self.client.snapshot()["script"]["status"], "cancelled")

    def test_busy_rejection_does_not_stop_another_owner(self) -> None:
        def peer() -> None:
            command = self.files.command()
            self.publish_running(command)
            self.files.state["command"] = {"id": "other-owner", "status": "running", "reason": None}
            self.files.state["script"]["id"] = "other-script"
            self.files.state["held_keys"] = [37]
            self.files.state["rejected_command"] = {"id": command[3], "status": "rejected", "reason": "busy"}
            self.files.publish()

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            with self.assertRaises(ClientError) as failure:
                self.client.run_script(self.path, seconds=1)
            native.result(2)
        self.assertEqual(failure.exception.code, "bridge_command_rejected")
        self.assertEqual(self.files.command()[4], "script")
        self.assertEqual(self.client.snapshot()["held_keys"], [37])

    def test_foreign_or_expired_state_refuses_script_before_publication(self) -> None:
        self.files.state["run_id"] = "another-run"
        self.files.publish()
        with self.assertRaises(ClientError) as foreign:
            self.client.run_script(self.path)
        self.assertEqual(foreign.exception.code, "bridge_session_mismatch")
        self.files.state["run_id"] = self.files.environment["RUN_ID"]
        self.files.publish(age=5)
        with self.assertRaises(ClientError) as expired:
            self.client.run_script(self.path)
        self.assertEqual(expired.exception.code, "stale_bridge_state")
        self.assertFalse((self.files.directory / "command.txt").exists())
        self.assertFalse((self.files.directory / "scripts").exists())


if __name__ == "__main__":
    unittest.main()
