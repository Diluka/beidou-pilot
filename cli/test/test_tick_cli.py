"""tick CLI 多会话文件协议合同；对端替身不证明真实游戏输入。"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.bridge import BridgeClient, BridgeScript
from beidou_pilot.cli import main
from beidou_pilot.errors import ClientError, JsonObject
from .test_bridge import BridgeFiles
from .test_native_scripts import script_state


TICK_SOURCE = "-- @mode tick\nfunction main(context) context.state.calls = (context.state.calls or 0) + 1 end\n"


def tick_state(script_id: str, *, stopped: bool = False) -> BridgeScript:
    script = script_state(script_id, "cancelled" if stopped else "running", "stop_requested" if stopped else None)
    script.update(
        mode="tick",
        control_released=stopped,
        tick={
            "index": 4,
            "time": 1.5,
            "delta": 0.008,
            "scene_generation": 1,
            "overrun": False,
            "budget_ms": 100,
            "overrun_policy": "abort",
            "abort_commit": True,
            "overruns": 0,
        },
        player={
            "moving": None if stopped else "right",
            "action": None,
            "phase": "idle",
            "busy": False,
            "held": [] if stopped else ["right"],
            "pending_action": None,
            "reason": "",
            "effect": "unknown",
            "dispatched": False,
            "control_released": stopped,
        },
    )
    return script


class TickCliContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = BridgeFiles(Path(temporary.name))
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.files.state.update(script=None, scripts=[])
        self.files.publish()
        self.client = BridgeClient(self.files.root)

    def cli(self, *arguments: str) -> tuple[int, JsonObject]:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--json", "--root", str(self.files.root), *arguments])
        return code, json.loads(output.getvalue())

    def start_cli(self, *arguments: str) -> subprocess.Popen[str]:
        environment = {
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        process = subprocess.Popen(
            [sys.executable, "-m", "beidou_pilot", "--json", "--root", str(self.files.root), *arguments],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.addCleanup(self.finish_process, process)
        return process

    @staticmethod
    def finish_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.kill()
        process.communicate()

    def test_status_lists_sessions_and_selects_an_older_session_readonly(self) -> None:
        first, latest = tick_state("a" * 32), tick_state("b" * 32)
        self.files.state.update(script=latest, scripts=[first, latest])
        self.files.publish()
        code, report = self.cli("script", "status", "--session", first["id"])
        self.assertEqual(0, code, report)
        self.assertEqual(first, report["data"]["script"])
        self.assertEqual([first, latest], report["data"]["scripts"])
        code, report = self.cli("script", "status")
        self.assertEqual((0, latest), (code, report["data"]["script"]))
        code, report = self.cli("script", "status", "--session", "c" * 32)
        self.assertEqual((2, "script_session_mismatch"), (code, report["error"]["code"]))
        self.assertFalse((self.files.directory / "command.txt").exists())

    def test_run_releases_admission_locks_for_another_tick_start_and_targeted_cancel(self) -> None:
        first_cli = self.start_cli("script", "run", "--code=" + TICK_SOURCE, "--continuous")
        first_request = self.files.command()
        first = tick_state(first_request[6])
        self.files.state.update(
            script=first,
            scripts=[first],
            held_keys=[39],
            command={"id": first_request[3], "status": "running", "reason": None},
        )
        self.files.publish()
        second_cli = self.start_cli("script", "start", "--code=" + TICK_SOURCE, "--continuous")
        second_request = self.files.command(first_request[3])
        self.assertEqual(["script", "0"], second_request[4:6])
        second = tick_state(second_request[6])
        self.files.state.update(
            script=second,
            scripts=[first, second],
            held_keys=[37, 39],
            command={"id": second_request[3], "status": "running", "reason": None},
        )
        self.files.publish()
        output, errors = second_cli.communicate(timeout=2)
        self.assertEqual(0, second_cli.returncode, errors + output)
        self.assertEqual(second["id"], json.loads(output)["data"]["script_id"])
        self.assertIsNone(first_cli.poll(), "其他会话的受理不能结束第一个run等待")

        cancel_cli = self.start_cli("script", "cancel", "--session", first["id"])
        cancel_request = self.files.command(second_request[3])
        self.assertEqual(["cancel_script", "0", first["id"]], cancel_request[4:])
        lines = (self.files.directory / "command.txt").read_text().splitlines()
        self.assertEqual(1, len(lines), "取消必须沿用原生单行命令格式")
        first = tick_state(first["id"], stopped=True)
        self.files.state.update(
            script=second,
            scripts=[first, second],
            held_keys=[37],
            command={"id": cancel_request[3], "status": "completed", "reason": None},
        )
        self.files.publish()
        output, errors = cancel_cli.communicate(timeout=2)
        self.assertEqual(0, cancel_cli.returncode, errors + output)
        cancellation = json.loads(output)["data"]
        self.assertEqual(
            ("cancelled", True, [37]),
            (cancellation["status"], cancellation["control_released"], cancellation["held_keys"]),
        )
        output, errors = first_cli.communicate(timeout=2)
        self.assertEqual(0, first_cli.returncode, errors + output)
        report = json.loads(output)["data"]
        self.assertEqual(
            (first["id"], first_request[3], "cancelled"),
            (report["script"]["id"], report["request_id"], report["status"]),
        )
        self.assertEqual(
            (second["id"], "running", [37]),
            (
                report["last_state"]["script"]["id"],
                report["last_state"]["script"]["status"],
                report["last_state"]["held_keys"],
            ),
        )
        self.assertEqual("already_stopped", self.client.cancel_script(first["id"])["status"])
        self.assertEqual(cancel_request, self.files.command())

    def test_start_reports_an_accepted_draining_tick_error_without_claiming_release(self) -> None:
        def peer() -> list[str]:
            request = self.files.command()
            script = tick_state(request[6])
            script.update(reason="tick_overrun", error="tick execution budget exceeded")
            script["player"].update(action="attack", phase="running", busy=True, held=["attack"])
            self.files.state.update(
                script=script,
                scripts=[script],
                held_keys=[18],
                command={"id": request[3], "status": "running", "reason": None},
            )
            self.files.publish()
            return request

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            with self.assertRaises(ClientError) as failure:
                self.client.run_script(code=TICK_SOURCE, wait_for_start=True, timeout=0.25)
            request = native.result(2)
        self.assertEqual("bridge_script_error", failure.exception.code)
        self.assertIn("已受理", failure.exception.message)
        self.assertNotIn("已停止", failure.exception.message)
        report = failure.exception.details
        self.assertEqual(
            (request[3], request[6], "running", False),
            (report["request_id"], report["script_id"], report["status"], report["script"]["control_released"]),
        )
        self.assertEqual([18], report["last_state"]["held_keys"])
        self.assertEqual(request, self.files.command(), "受理后的错误报告不应取消或重放会话")

    def test_run_waits_for_draining_error_terminal_without_holding_admission_lock(self) -> None:
        first_cli = self.start_cli("script", "run", "--code=" + TICK_SOURCE, "--continuous")
        first_request = self.files.command()
        first = tick_state(first_request[6])
        first.update(reason="tick_overrun", error="tick execution budget exceeded")
        self.files.state.update(
            script=first,
            scripts=[first],
            held_keys=[18],
            command={"id": first_request[3], "status": "running", "reason": None},
        )
        self.files.publish()
        second_cli = self.start_cli("script", "start", "--code=" + TICK_SOURCE, "--continuous")
        second_request = self.files.command(first_request[3])
        second = tick_state(second_request[6])
        self.files.state.update(
            script=second,
            scripts=[first, second],
            held_keys=[18, 39],
            command={"id": second_request[3], "status": "running", "reason": None},
        )
        self.files.publish()
        output, errors = second_cli.communicate(timeout=2)
        self.assertEqual(0, second_cli.returncode, errors + output)
        self.assertIsNone(first_cli.poll(), "同步run须等错误会话排空及输入释放，不能把error字段当成终态")
        first = tick_state(first["id"], stopped=True)
        first.update(reason="tick_overrun", error="tick execution budget exceeded")
        self.files.state.update(scripts=[first, second], held_keys=[39])
        self.files.publish()
        output, errors = first_cli.communicate(timeout=2)
        self.assertEqual(2, first_cli.returncode, errors + output)
        failure = json.loads(output)["error"]
        self.assertEqual("bridge_script_error", failure["code"])
        report = failure["details"]
        self.assertEqual(
            (first_request[3], first["id"], "cancelled", True),
            (report["request_id"], report["script_id"], report["status"], report["script"]["control_released"]),
        )
        self.assertEqual(
            (second["id"], [39]), (report["last_state"]["script"]["id"], report["last_state"]["held_keys"])
        )

    def test_tick_and_coroutine_admit_independently_but_coroutine_stays_single_session(self) -> None:
        existing = script_state("c" * 32, "running")
        existing.update(mode="coroutine", control_released=False)
        self.files.state.update(
            script=existing,
            scripts=[existing],
            held_keys=[39],
            command={"id": "other-command", "status": "running", "reason": None},
        )
        self.files.publish()
        with self.assertRaises(ClientError) as busy:
            self.client.run_script(code="game.sleep(1)", wait_for_start=True)
        self.assertEqual("input_busy", busy.exception.code)

        def peer() -> None:
            request = self.files.command()
            script = tick_state(request[6])
            self.files.state.update(
                script=script,
                scripts=[existing, script],
                command={"id": request[3], "status": "running", "reason": None},
            )
            self.files.publish()

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            report = self.client.run_script(code=TICK_SOURCE, wait_for_start=True)
            native.result(2)
        self.assertEqual(("tick", "running"), (report["mode"], report["status"]))
        # 只剩tick会话时也允许建立一个coroutine会话。
        tick = self.files.state["script"]
        self.files.state["scripts"] = [tick]
        previous = self.files.command()[3]
        self.files.publish()

        def coroutine_peer() -> None:
            request = self.files.command(previous)
            script = script_state(request[6], "running")
            script.update(mode="coroutine", control_released=False)
            self.files.state.update(
                script=script, scripts=[tick, script], command={"id": request[3], "status": "running", "reason": None}
            )
            self.files.publish()

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(coroutine_peer)
            report = self.client.run_script(code="game.sleep(1)", wait_for_start=True)
            native.result(2)
        self.assertEqual(("coroutine", "running"), (report["mode"], report["status"]))

    def test_cancel_file_targets_only_its_session_when_another_session_holds_keys(self) -> None:
        cancel_file = self.files.root / "cancel"
        sibling = tick_state("b" * 32)

        def peer() -> None:
            request = self.files.command()
            target = tick_state(request[6])
            self.files.state.update(
                script=sibling,
                scripts=[target, sibling],
                held_keys=[39],
                command={"id": request[3], "status": "running", "reason": None},
            )
            self.files.publish()
            cancel_file.touch()
            cancel = self.files.command(request[3])
            self.assertEqual(["cancel_script", "0", target["id"]], cancel[4:])
            self.files.state.update(
                scripts=[tick_state(target["id"], stopped=True), sibling],
                command={"id": cancel[3], "status": "completed", "reason": None},
            )
            self.files.publish()

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            report = self.client.run_script(code=TICK_SOURCE, seconds=None, cancel_file=cancel_file)
            native.result(2)
        self.assertTrue(report["cancelled"])
        self.assertEqual(report["script_id"], report["script"]["id"])
        self.assertEqual(
            ("running", [39]), (report["last_state"]["script"]["status"], report["last_state"]["held_keys"])
        )

    def test_completed_coroutine_result_survives_a_newer_coroutine_admission(self) -> None:
        def peer() -> list[str]:
            request = self.files.command()
            completed = script_state(request[6], "completed", "script_returned")
            completed.update(mode="coroutine", control_released=True)
            latest = script_state("b" * 32, "running")
            latest.update(mode="coroutine", control_released=False)
            self.files.state.update(
                script=latest,
                scripts=[completed, latest],
                held_keys=[39],
                command={"id": "newer-command", "status": "running", "reason": None},
            )
            self.files.publish()
            return request

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            report = self.client.run_script(code="game.log('done')")
            request = native.result(2)
        self.assertEqual(
            (request[3], request[6], "completed"), (report["request_id"], report["script"]["id"], report["status"])
        )
        self.assertEqual(
            ("b" * 32, "running", [39]),
            (
                report["last_state"]["script"]["id"],
                report["last_state"]["script"]["status"],
                report["last_state"]["held_keys"],
            ),
        )

    def test_old_single_session_bridge_never_falls_back_to_coroutine_for_tick(self) -> None:
        del self.files.state["scripts"]
        self.files.publish()
        with self.assertRaises(ClientError) as unsupported:
            self.client.run_script(code=TICK_SOURCE)
        self.assertEqual("bridge_tick_unsupported", unsupported.exception.code)
        self.assertFalse((self.files.directory / "scripts").exists())
        self.assertFalse((self.files.directory / "command.txt").exists())

    def test_invalid_execution_config_does_not_copy_or_publish_a_script(self) -> None:
        with self.assertRaises(ClientError) as invalid:
            self.client.run_script(code="-- @mode tick\n-- @tick.overrun retry\nfunction main(context) end")
        self.assertEqual("invalid_strategy_metadata", invalid.exception.code)
        self.assertFalse((self.files.directory / "scripts").exists())
        self.assertFalse((self.files.directory / "command.txt").exists())

    def test_snapshot_validates_each_session_and_tick_state_at_the_boundary(self) -> None:
        valid = tick_state("a" * 32)
        cases = [
            [dict(valid, mode="unknown")],
            [dict(valid, tick=None)],
            [dict(valid, player=None)],
            [dict(valid, tick={**valid["tick"], "delta": float("nan")})],
            [dict(valid, tick={**valid["tick"], "budget_ms": 0})],
            [dict(valid, tick={**valid["tick"], "scene_generation": True})],
            [dict(valid, player={**valid["player"], "held": ["fake"]})],
            [dict(valid, player={**valid["player"], "skill_id": True})],
            [dict(valid, control_released=1)],
            [valid, valid],
            [{key: value for key, value in valid.items() if key != "mode"}],
        ]
        for scripts in cases:
            with self.subTest(scripts=scripts):
                self.files.state["scripts"] = deepcopy(scripts)
                self.files.publish()
                with self.assertRaises(ClientError) as invalid:
                    self.client.snapshot()
                self.assertEqual("invalid_bridge_state", invalid.exception.code)


if __name__ == "__main__":
    unittest.main()
