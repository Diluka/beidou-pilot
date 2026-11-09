"""DLL脚本与技能入口的文件IPC合同；不模拟Lua解释器或游戏规则。"""

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

from beidou_pilot.bridge import BridgeClient, BridgeScript
from beidou_pilot.cli import main
from beidou_pilot.errors import ClientError
from .test_bridge import BridgeFiles


def script_state(script_id: str, status: Literal["running", "completed", "cancelled", "rejected"],
                 reason: str | None = None, error: str | None = None) -> BridgeScript:
    return {"id": script_id, "status": status, "reason": reason, "error": error,
            "resumes": 3, "budget_yields": 1, "last_resume_us": 12.5, "max_resume_us": 18.25}


class NativeScriptContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = BridgeFiles(Path(temporary.name))
        (self.files.root / "clientctl.py").touch()
        self.files.state.update(script=None, last_skill=None, monsters=[], facing="Right")
        self.files.publish()
        self.client = BridgeClient(self.files.root)
        self.path = self.files.root / "example.lua"
        self.path.write_text("-- 受信本地脚本\nlocal s = game.state()\nif s.ready then game.sleep(0.1) end\n", encoding="utf-8")

    def start_cli(self, *arguments: str) -> subprocess.Popen[str]:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.Popen(
            [sys.executable, "-m", "beidou_pilot", "--json", "--root", str(self.files.root), *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=environment,
        )

    def test_cli_copies_utf8_script_and_status_is_readonly_during_execution(self) -> None:
        process = self.start_cli("script", "run", str(self.path), "--seconds", ".3")
        try:
            command = self.files.command()
            self.assertEqual(command[4:6], ["script", "300"])
            script_id = command[6]
            self.assertEqual((self.files.directory / "scripts" / (script_id + ".lua")).read_bytes(), self.path.read_bytes())
            self.files.state["command"] = {"id": command[3], "status": "running", "reason": None}
            self.files.state["script"] = script_state(script_id, "running")
            self.files.publish()
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--json", "--root", str(self.files.root), "script", "status"])
            self.assertEqual(code, 0, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())["data"]["script"]["status"], "running")
            self.assertIsNone(process.poll(), "脚本睡眠和空按键集不代表脚本完成")
            self.files.state["command"]["status"] = "completed"
            self.files.state["script"] = script_state(script_id, "completed")
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

    def test_continuous_cli_sigterm_waits_for_script_stop_and_key_release(self) -> None:
        process = self.start_cli("script", "run", str(self.path), "--continuous")
        try:
            command = self.files.command()
            self.assertEqual(command[4:6], ["script", "0"])
            self.files.state["command"] = {"id": command[3], "status": "running", "reason": None}
            self.files.state["script"] = script_state(command[6], "running")
            self.files.state["held_keys"] = [39]
            self.files.publish()
            process.send_signal(signal.SIGTERM)
            stop = self.files.command(command[3])
            self.assertEqual(stop[4:], ["stop", "0"])
            self.assertIsNone(process.poll(), "脚本须确认停止和放键后再退出控制器")
            self.files.state["script"] = script_state(command[6], "cancelled", "stop_requested")
            self.files.complete_stop(command[3])
            output, errors = process.communicate(timeout=2)
            self.assertEqual(process.returncode, 130, errors)
            self.assertEqual(json.loads(output)["error"]["code"], "interrupted")
            self.assertEqual(self.files.state["held_keys"], [])
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_native_runtime_error_remains_a_failure_after_release(self) -> None:
        def peer() -> None:
            command = self.files.command()
            self.files.state["command"] = {"id": command[3], "status": "cancelled", "reason": "script_error"}
            self.files.state["script"] = script_state(command[6], "cancelled", "script_error", "example.lua:2: deliberate failure")
            self.files.publish()

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            with self.assertRaises(ClientError) as failure:
                self.client.run_script(self.path, seconds=1)
            native.result(2)
        self.assertEqual(failure.exception.code, "bridge_script_error")
        self.assertEqual(failure.exception.details["script"]["error"], "example.lua:2: deliberate failure")
        self.assertEqual(failure.exception.details["last_state"]["held_keys"], [])
        self.assertEqual(self.files.command()[4], "script")

    def test_continuous_cli_ends_with_unknown_release_when_sampling_stops(self) -> None:
        process = self.start_cli("script", "run", str(self.path), "--continuous")
        try:
            command = self.files.command()
            self.files.state["command"] = {"id": command[3], "status": "running", "reason": None}
            self.files.state["script"] = script_state(command[6], "running")
            self.files.state["held_keys"] = [39]
            self.files.publish()
            # 对端从此不更新，也不确认stop；控制器必须自行结束持续等待。
            output, errors = process.communicate(timeout=9)
            self.assertEqual(process.returncode, 2, errors)
            failure = json.loads(output)["error"]
            self.assertEqual(failure["code"], "bridge_release_unconfirmed")
            self.assertEqual(failure["details"]["original_error"], "stale_bridge_state")
            self.assertEqual(failure["details"]["release_error"], "bridge_timeout")
            self.assertEqual(self.files.command(command[3])[4:], ["stop", "0"])
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def test_cancel_file_retains_script_identity_and_waits_for_native_stop(self) -> None:
        cancel_file = self.files.root / "cancel"

        def peer() -> None:
            command = self.files.command()
            self.files.state["command"] = {"id": command[3], "status": "running", "reason": None}
            self.files.state["script"] = script_state(command[6], "running")
            self.files.state["held_keys"] = [39]
            self.files.publish()
            cancel_file.write_text("controller_cancel")
            self.files.command(command[3])
            self.files.state["script"] = script_state(command[6], "cancelled", "stop_requested")
            self.files.complete_stop(command[3])

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            report = self.client.run_script(self.path, seconds=None, cancel_file=cancel_file)
            native.result(2)
        self.assertTrue(report["cancelled"])
        self.assertEqual(report["script_id"], report["script"]["id"])
        self.assertEqual(report["script"]["status"], "cancelled")
        self.assertEqual(report["last_state"]["held_keys"], [])

    def test_old_dll_refuses_script_without_copying_or_publishing(self) -> None:
        del self.files.state["script"]
        self.files.publish()
        with self.assertRaises(ClientError) as failure:
            self.client.run_script(self.path)
        self.assertEqual(failure.exception.code, "bridge_script_unsupported")
        self.assertFalse((self.files.directory / "command.txt").exists())
        self.assertFalse((self.files.directory / "scripts").exists())



if __name__ == "__main__":
    unittest.main()
