"""tick 脚本与状态入口的文件IPC合同；不模拟Lua解释器或游戏规则。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from typing import Literal
import unittest
from unittest.mock import patch

from beidou_pilot.bridge import BridgeClient
from beidou_pilot.cli import main
from beidou_pilot.errors import ClientError
from .test_bridge import BridgeFiles, tick_script


TICK_SOURCE = "-- @mode tick\nlocal function main(context)\n    context.state.calls = 0\nend\n"


def script_state(script_id: str, status: Literal["running", "completed", "cancelled", "rejected"],
                 reason: str | None = None, error: str | None = None) -> dict:
    script = tick_script(script_id, status=status, control_released=status != "running", reason=reason, error=error)
    script.update(resumes=3, budget_yields=1, last_resume_us=12.5, max_resume_us=18.25)
    return script


class NativeScriptContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = BridgeFiles(Path(temporary.name))
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.files.state.update(script=None, scripts=[], monsters=[], facing="Right")
        self.files.publish()
        self.client = BridgeClient(self.files.root)
        self.path = self.files.root / "example.lua"
        self.path.write_text(TICK_SOURCE, encoding="utf-8")

    def publish_running(self, command: list[str]) -> dict:
        self.files.state["command"] = {"id": command[3], "status": "running", "reason": None}
        script = script_state(command[6], "running")
        self.files.state.update(script=script, scripts=[script], held_keys=[39])
        self.files.publish()
        return script

    def start_cli(self, *arguments: str) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.Popen(
            [sys.executable, "-m", "beidou_pilot", "--json", "--root", str(self.files.root), *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=environment,
        )

    def test_cli_publishes_compiled_tick_script_and_status_is_readonly_during_execution(self) -> None:
        process = self.start_cli("script", "run", str(self.path), "--seconds", ".3")
        try:
            command = self.files.command()
            self.assertEqual(command[4:6], ["script", "300"])
            script_id = command[6]
            published = (self.files.directory / "scripts" / (script_id + ".lua")).read_text(encoding="utf-8")
            self.assertIn("context.state.calls = 0", published)
            self.assertIn("return {main=main,context=__beidou_context}", published)
            self.publish_running(command)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--json", "--root", str(self.files.root), "script", "status"])
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["data"]["script"]["status"], "running")
            self.assertIsNone(process.poll(), "脚本运行不代表受理等待结束")
            self.files.state["command"]["status"] = "completed"
            script = script_state(script_id, "completed")
            self.files.state.update(script=script, scripts=[script], held_keys=[])
            self.files.publish()
            output, errors = process.communicate(timeout=2)
            self.assertEqual(process.returncode, 0, errors)
            report = json.loads(output)["data"]
            self.assertEqual(report["request_id"], command[3])
            self.assertEqual(report["script"]["id"], script_id)
            self.assertEqual(report["script"]["max_resume_us"], 18.25)
            self.assertEqual(report["last_state"]["held_keys"], [])
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_cli_sigterm_ends_wait_without_canceling_published_script(self) -> None:
        for action in ("run", "start"):
            with self.subTest(action=action):
                (self.files.directory / "command.txt").unlink(missing_ok=True)
                self.files.state.update(
                    command={"id": None, "status": "idle", "reason": None},
                    script=None, scripts=[], held_keys=[],
                )
                self.files.publish()
                process = self.start_cli("script", action, str(self.path), "--continuous")
                try:
                    command = self.files.command()
                    self.assertEqual(command[4:6], ["script", "0"])
                    script = self.publish_running(command)
                    if action == "run":
                        self.files.publish()
                    process.send_signal(signal.SIGTERM)
                    if action == "start":
                        # start 尚在等待原生受理；退出等待不撤销已经发布的请求。
                        self.files.publish()
                    output, errors = process.communicate(timeout=2)
                    self.assertEqual(process.returncode, 130, errors)
                    self.assertEqual(json.loads(output)["error"]["code"], "interrupted")
                    self.assertEqual(command, self.files.command())
                    state = self.client.snapshot()
                    self.assertEqual((script["id"], "running", [39]),
                                     (state["script"]["id"], state["script"]["status"], state["held_keys"]))

                    def peer() -> None:
                        cancel_command = self.files.command(command[3])
                        if cancel_command[4:] != ["cancel_script", "0", script["id"]]:
                            raise AssertionError("取消应发送目标cancel_script命令")
                        cancelled = script_state(script["id"], "cancelled", "stop_requested")
                        self.files.state.update(
                            script=cancelled, scripts=[cancelled], held_keys=[],
                            command={"id": cancel_command[3], "status": "completed", "reason": None},
                        )
                        self.files.publish()

                    with ThreadPoolExecutor(max_workers=1) as pool:
                        native = pool.submit(peer)
                        report = self.client.cancel_script(script["id"])
                        native.result(2)
                    self.assertEqual(("cancelled", []), (report["status"], report["held_keys"]))
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()

    def test_native_runtime_error_remains_a_failure_after_release(self) -> None:
        def peer() -> None:
            command = self.files.command()
            script = script_state(command[6], "cancelled", "script_error", "example.lua:2: deliberate failure")
            self.files.state.update(
                command={"id": command[3], "status": "cancelled", "reason": "script_error"},
                script=script, scripts=[script], held_keys=[],
            )
            self.files.publish()

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            with self.assertRaises(ClientError) as failure:
                self.client.run_script(code=TICK_SOURCE, seconds=1)
            native.result(2)
        self.assertEqual(failure.exception.code, "bridge_script_error")
        self.assertEqual(failure.exception.details["script"]["error"], "example.lua:2: deliberate failure")
        self.assertEqual(failure.exception.details["last_state"]["held_keys"], [])
        self.assertEqual(self.files.command()[4], "script")

    def test_continuous_cli_reports_stale_observation_without_stopping_task(self) -> None:
        process = self.start_cli("script", "run", str(self.path), "--continuous")
        try:
            command = self.files.command()
            self.publish_running(command)
            # 对端从此不更新；结束观察不代表任务结束，也不发送取消请求。
            output, errors = process.communicate(timeout=9)
            self.assertEqual(process.returncode, 2, errors)
            failure = json.loads(output)["error"]
            self.assertEqual(failure["code"], "stale_bridge_state")
            self.assertEqual(command, self.files.command())
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_cancel_file_retains_script_identity_and_waits_for_native_stop(self) -> None:
        cancel_file = self.files.root / "cancel"

        def peer() -> None:
            command = self.files.command()
            self.publish_running(command)
            cancel_file.write_text("controller_cancel")
            cancel_command = self.files.command(command[3])
            if cancel_command[4:] != ["cancel_script", "0", command[6]]:
                raise AssertionError("取消应发送目标cancel_script命令")
            cancelled = script_state(command[6], "cancelled", "stop_requested")
            self.files.state.update(
                script=cancelled, scripts=[cancelled], held_keys=[],
                command={"id": cancel_command[3], "status": "completed", "reason": None},
            )
            self.files.publish()

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            report = self.client.run_script(self.path, seconds=None, cancel_file=cancel_file)
            native.result(2)
        self.assertTrue(report["cancelled"])
        self.assertEqual(report["script_id"], report["script"]["id"])
        self.assertEqual(report["script"]["status"], "cancelled")
        self.assertEqual(report["last_state"]["held_keys"], [])

    def test_old_dll_refuses_script_without_copying_or_publishing(self) -> None:
        del self.files.state["scripts"]
        self.files.publish()
        with self.assertRaises(ClientError) as failure:
            self.client.run_script(self.path)
        self.assertEqual(failure.exception.code, "bridge_tick_unsupported")
        self.assertFalse((self.files.directory / "command.txt").exists())
        self.assertFalse((self.files.directory / "scripts").exists())


if __name__ == "__main__":
    unittest.main()
