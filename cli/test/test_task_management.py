"""任务管理CLI的文件IPC合同；协议对端不解释Lua，也不证明游戏效果。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import fcntl
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from beidou_pilot.cli import main
from beidou_pilot.errors import JsonObject
from beidou_pilot.instances import InstancePaths
from .test_bridge import BridgeFiles


class TaskManagementContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = BridgeFiles(Path(temporary.name))
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.session = "a" * 32
        self.files.state["script"] = {
            "id": self.session,
            "status": "running",
            "reason": None,
            "error": None,
            "resumes": 1,
            "budget_yields": 0,
            "last_resume_us": 1.0,
            "max_resume_us": 1.0,
            "tasks": [
                {
                    "name": "main",
                    "revision": 1,
                    "priority": 0,
                    "status": "waiting",
                    "wait": "action",
                    "reason": None,
                    "error": None,
                }
            ],
        }
        self.files.state["command"] = {"id": "c" * 32, "status": "running", "reason": None}
        self.files.state["held_keys"] = [39]
        native = BridgeFiles(self.files.root / "headless", "headless", "alpha")
        native.environment["HOSTNAME"] = "headless-container"
        native.state = deepcopy(self.files.state)
        self.instances = {("beidou", "default"): self.files, ("headless", "alpha"): native}
        self.prepare_instance()

    def prepare_instance(self, backend="beidou", instance="default"):
        self.files = self.instances[(backend, instance)]
        self.files.register(backend, instance)
        paths = InstancePaths(self.files.root, backend, instance)
        self.files.state["instance_id"] = backend + "-" + instance
        self.files.publish()
        self.original_command = f"1 {self.files.state['instance_id']} 1 {'c' * 32} script 0 {self.session}\n".encode(
            "ascii"
        )
        (paths.bridge / "command.txt").write_bytes(self.original_command)
        return paths

    def hold_session(self, paths):
        stack = ExitStack()
        for path in (paths.input_lock, paths.bridge / "control.lock"):
            handle = stack.enter_context(path.open("a"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return stack

    def cli(self, *arguments, backend="beidou", instance="default"):
        output = io.StringIO()
        with patch.dict(os.environ, self.files.environment), redirect_stdout(output):
            exit_code = main(
                [
                    "--root",
                    str(self.files.root),
                    "--backend",
                    backend,
                    "--instance",
                    instance,
                    "--json",
                    "task",
                    *arguments,
                ]
            )
        return exit_code, json.loads(output.getvalue())

    def request(self):
        path = self.files.directory / "task-request.txt"
        until = time.monotonic() + 3
        while time.monotonic() < until:
            try:
                fields = path.read_text(encoding="ascii").split()
            except FileNotFoundError:
                time.sleep(0.005)
                continue
            path.unlink()
            return fields
        raise AssertionError("未收到任务管理请求")

    def reply(self, overrides: JsonObject | None = None):
        fields = self.request()
        source = (self.files.directory / "scripts" / (fields[10] + ".lua")).read_bytes() if fields[10] != "-" else None
        self.files.publish()
        result = {
            "protocol": 1,
            "instance_id": fields[1],
            "run_id": fields[2],
            "script_id": fields[3],
            "scene_generation": int(fields[4]),
            "seq": self.files.state["seq"],
            "observed_at_ms": self.files.state["observed_at_ms"],
            "request_id": fields[5],
            "operation": fields[6],
            "name": bytes.fromhex(fields[7]).decode("utf-8"),
            "expected_revision": int(fields[8]),
            "revision": int(fields[8]) + 1 if fields[6] != "stop" else int(fields[8]),
            "status": "completed",
            "reason": None,
            "error": None,
            "changed": True,
            "control_released": True,
        }
        result.update(overrides or {})
        directory = self.files.directory / "task-results"
        directory.mkdir(exist_ok=True)
        temporary = directory / (fields[5] + ".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(directory / (fields[5] + ".json"))
        return fields, source

    def test_management_uses_its_own_lane_and_preserves_utf8_sources(self) -> None:
        name = "观察 中文"
        inline = 'game.log("你好 \\"引号\\"")\r\ngame.sleep(0)\n'
        path = self.files.root / "task.lua"
        file_source = 'game.log("文件当前内容")\r\n'.encode("utf-8")
        path.write_bytes(file_source)
        cases = [
            ("beidou", "default", "add", ["--code", inline, "--priority", "20"], 0, 20, inline.encode("utf-8")),
            ("headless", "alpha", "replace", [str(path), "--revision", "3", "--priority", "30"], 3, 30, file_source),
            ("headless", "alpha", "stop", ["--revision", "4"], 4, 0, None),
        ]
        for backend, instance, operation, options, revision, priority, expected_source in cases:
            with self.subTest(operation=operation):
                paths = self.prepare_instance(backend, instance)
                self.files.state["script"]["tasks"] = self.files.state["script"]["tasks"][:1]
                if revision:
                    self.files.state["script"]["tasks"].append(
                        {
                            "name": name,
                            "revision": revision,
                            "priority": priority,
                            "status": "waiting",
                            "wait": "sleep",
                            "reason": None,
                            "error": None,
                        }
                    )
                self.files.publish()
                with self.hold_session(paths), ThreadPoolExecutor(max_workers=1) as pool:
                    peer = pool.submit(self.reply)
                    code, report = self.cli(
                        operation, name, "--session", self.session, *options, backend=backend, instance=instance
                    )
                    fields, source = peer.result(3)
                    self.assertEqual(0, code, report)
                    self.assertEqual((backend, instance), (report["backend"], report["instance"]))
                    self.assertEqual(["1", backend + "-" + instance, "bridge-contract", self.session, "1"], fields[:5])
                    self.assertEqual(
                        (operation, name, revision, priority),
                        (fields[6], bytes.fromhex(fields[7]).decode("utf-8"), int(fields[8]), int(fields[9])),
                    )
                    self.assertEqual(expected_source, source)
                    self.assertEqual(self.original_command, (paths.bridge / "command.txt").read_bytes())
                    result_code, result = self.cli("result", fields[5], backend=backend, instance=instance)
                    self.assertEqual((0, report["data"]), (result_code, result["data"]))

    def test_management_rejects_foreign_result_identity(self) -> None:
        for field, value in (
            ("instance_id", "other-native"),
            ("script_id", "b" * 32),
            ("request_id", "b" * 32),
            ("expected_revision", 99),
        ):
            with self.subTest(field=field), ThreadPoolExecutor(max_workers=1) as pool:
                self.files.publish()
                peer = pool.submit(self.reply, {field: value})
                code, report = self.cli(
                    "add", "observer", "--session", self.session, "--priority", "0", "--code", "game.sleep(0)"
                )
                peer.result(3)
                self.assertEqual((2, "invalid_task_result"), (code, report["error"]["code"]))
                self.assertEqual(self.original_command, (self.files.directory / "command.txt").read_bytes())

    def test_management_timeout_keeps_the_session_and_request_identity(self) -> None:
        code, report = self.cli("stop", "observer", "--session", self.session, "--revision", "3", "--timeout", ".03")
        fields = self.request()
        self.assertEqual((2, "task_result_unconfirmed"), (code, report["error"]["code"]))
        self.assertEqual(fields[5], report["error"]["details"]["request_id"])
        self.assertEqual(self.original_command, (self.files.directory / "command.txt").read_bytes())

    def test_management_signals_return_unconfirmed_without_stopping_session(self) -> None:
        environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]), PYTHONDONTWRITEBYTECODE="1")
        paths = InstancePaths(self.files.root)
        for interrupt in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=interrupt), self.hold_session(paths):
                self.files.publish()
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "beidou_pilot",
                        "--root",
                        str(self.files.root),
                        "--json",
                        "task",
                        "add",
                        "observer",
                        "--session",
                        self.session,
                        "--priority",
                        "0",
                        "--code",
                        "game.sleep(0)",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=environment,
                )
                try:
                    fields = self.request()
                    process.send_signal(interrupt)
                    output, errors = process.communicate(timeout=3)
                    self.assertEqual(130, process.returncode, errors)
                    report = json.loads(output)
                    self.assertEqual("task_request_interrupted", report["error"]["code"])
                    self.assertEqual(fields[5], report["error"]["details"]["request_id"])
                    self.assertEqual(self.original_command, (paths.bridge / "command.txt").read_bytes())
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()

    def test_cli_requires_explicit_session_revision_and_source(self) -> None:
        cases = [
            ["add", "observer", "--priority", "0", "--code", "game.sleep(0)"],
            ["replace", "observer", "--session", self.session, "--priority", "0", "--code", "game.sleep(0)"],
            ["add", "observer", "--session", self.session, "--priority", "0"],
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                code, report = self.cli(*arguments)
                self.assertEqual((2, "usage"), (code, report["error"]["code"]))
        self.assertFalse((self.files.directory / "task-request.txt").exists())


if __name__ == "__main__":
    unittest.main()
