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
            "gear": 3,
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
            "input_action": None,
            "action": None,
            "phase": "idle",
            "busy": False,
            "held": [] if stopped else ["right"],
            "reason": "",
            "effect": "unknown",
            "dispatched": False,
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

    def test_snapshot_and_status_consume_sanitized_native_terminal_scripts(self) -> None:
        # 按当前共享Runtime投影维护的脱敏结构；身份、计数和时间固定化，不保留运行原件。
        native_script = json.loads(
            """{
                "id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "mode": "tick",
                "status": "completed", "reason": "script_returned", "error": null,
                "resumes": 4, "budget_yields": 0, "last_resume_us": 12.5, "max_resume_us": 18.25,
                "tasks": [], "control": {"owner": "", "pending": "", "from": "", "to": "", "reason": ""},
                "control_released": true,
                "tick": {
                    "index": 4, "gear": 4, "time": 1.5, "delta": 0.008, "scene_generation": 1,
                    "overrun": false, "overruns": 0, "budget_ms": 100,
                    "overrun_policy": "abort", "abort_commit": true,
                    "profile": {
                        "scope": "runtime_lifetime", "host_tick_calls": 4,
                        "active_frames": 4, "reentrant_tick_calls": 0,
                        "tick": {"samples": 4, "total_us": 80, "max_us": 30},
                        "observe": {"samples": 4, "total_us": 8, "max_us": 3},
                        "refresh_core": {"samples": 4, "total_us": 40, "max_us": 15},
                        "lua": {"samples": 4, "total_us": 25, "max_us": 18.25}
                    }
                },
                "player": {
                    "moving": null, "input_action": null, "action": null,
                    "phase": "idle", "busy": false, "held": [], "reason": "native_jump_input_consumed",
                    "effect": "unknown", "dispatched": true
                }
            }"""
        )
        for backend, status, reason, player_reason, dispatched in (
            ("headless", "completed", "script_returned", "native_jump_input_consumed", True),
            ("beidou", "cancelled", "time_limit", "", False),
        ):
            with self.subTest(backend=backend):
                self.files.register(backend)
                script = deepcopy(native_script)
                script.update(status=status, reason=reason)
                script["player"].update(reason=player_reason, dispatched=dispatched)
                self.files.state.update(
                    script=script,
                    scripts=[script],
                    command={"id": "native-command", "status": status, "reason": reason},
                )
                self.files.publish()
                with patch.dict(os.environ, self.files.environment):
                    state = BridgeClient(self.files.root, backend).snapshot()
                    code, report = self.cli("script", "status", "--session", script["id"])
                self.assertEqual(script, state["script"])
                self.assertEqual([script], state["scripts"])
                for projected in (state["script"], state["scripts"][0]):
                    self.assertNotIn("input_settled", projected["player"])
                    self.assertNotIn("control_released", projected["player"])
                    self.assertTrue(projected["control_released"])
                self.assertEqual((0, script), (code, report["data"]["script"]))
                self.assertFalse((self.files.directory / "command.txt").exists())

    def test_snapshot_keeps_held_input_separate_from_current_native_action(self) -> None:
        for player in (
            {"input_action": "skill", "input_skill_id": 1001004, "action": "attack", "held": ["right", "skill"]},
            {
                "input_action": "use_item",
                "input_item_id": 2000000,
                "action": "skill",
                "skill_id": 1001004,
                "held": ["right", "use_item"],
            },
            {"input_action": None, "action": "skill", "skill_id": 1001004, "held": ["right"]},
        ):
            with self.subTest(player=player):
                script = tick_state("a" * 32)
                script["player"].update(player, phase="running", busy=True)
                self.files.state.update(script=script, scripts=[script])
                self.files.publish()
                self.assertEqual(script["player"], self.client.snapshot()["scripts"][0]["player"])

    def test_snapshot_accepts_each_native_semantic_action(self) -> None:
        for action in ("jump", "attack", "skill", "use_item", "pickup"):
            with self.subTest(action=action):
                script = tick_state("a" * 32)
                script["player"].update(
                    input_action=action, action=action, held=["right", action], phase="running", busy=True
                )
                if action == "skill":
                    script["player"].update(input_skill_id=1001004, skill_id=1001004)
                elif action == "use_item":
                    script["player"].update(input_item_id=2000000, item_id=2000000)
                self.files.state.update(script=script, scripts=[script])
                self.files.publish()
                self.assertEqual(script["player"], self.client.snapshot()["script"]["player"])

    def test_snapshot_accepts_held_input_before_native_action_starts_or_idle_is_known(self) -> None:
        for phase, busy in (("idle", False), ("unknown", None)):
            with self.subTest(phase=phase):
                script = tick_state("a" * 32)
                script["player"].update(
                    input_action="skill",
                    input_skill_id=1001004,
                    held=["right", "skill"],
                    phase=phase,
                    busy=busy,
                )
                self.files.state.update(script=script, scripts=[script])
                self.files.publish()
                self.assertEqual(script["player"], self.client.snapshot()["script"]["player"])

    def test_run_completes_after_input_release_while_native_animation_continues(self) -> None:
        def peer() -> list[str]:
            request = self.files.command()
            script = tick_state(request[6], stopped=True)
            script.update(status="completed", reason="script_returned")
            script["player"].update(action="skill", skill_id=1001004, phase="running", busy=True)
            self.files.state.update(
                script=script,
                scripts=[script],
                command={"id": request[3], "status": "completed", "reason": "script_returned"},
            )
            self.files.publish()
            return request

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            report = self.client.run_script(code=TICK_SOURCE)
            request = native.result(2)
        self.assertEqual((request[6], "completed"), (report["script_id"], report["status"]))
        self.assertTrue(report["script"]["control_released"])
        self.assertEqual(("skill", True), (report["script"]["player"]["action"], report["script"]["player"]["busy"]))
        self.assertEqual(request, self.files.command(), "终态后的动画不应触发取消或重放")

    def test_terminal_session_still_requires_own_release_when_shared_player_is_idle(self) -> None:
        for operation in ("run", "cancel"):
            with self.subTest(operation=operation):
                target = tick_state("a" * 32)
                self.files.state.update(
                    script=target if operation == "cancel" else None,
                    scripts=[target] if operation == "cancel" else [],
                )
                previous = self.files.state["command"]["id"]
                self.files.publish()

                def peer() -> list[str]:
                    request = self.files.command(previous)
                    script = tick_state(request[6], stopped=True)
                    script.update(status="completed" if operation == "run" else "cancelled", control_released=False)
                    self.files.state.update(
                        script=script,
                        scripts=[script],
                        command={"id": request[3], "status": "completed", "reason": None},
                    )
                    self.files.publish()
                    return request

                with ThreadPoolExecutor(max_workers=1) as pool:
                    native = pool.submit(peer)
                    with self.assertRaises(ClientError) as unconfirmed:
                        if operation == "run":
                            self.client.run_script(code=TICK_SOURCE)
                        else:
                            self.client.cancel_script(target["id"])
                    request = native.result(2)
                self.assertEqual("bridge_release_unconfirmed", unconfirmed.exception.code)
                self.assertFalse(unconfirmed.exception.details["script"]["control_released"])
                player = unconfirmed.exception.details["script"]["player"]
                self.assertIsNone(player["input_action"])
                self.assertEqual([], player["held"])
                self.assertNotIn("input_settled", player)
                self.assertNotIn("control_released", player)
                self.assertEqual(request, self.files.command())

    def test_cancel_confirms_only_session_release_while_shared_player_keeps_another_input(self) -> None:
        target, sibling = tick_state("a" * 32), tick_state("b" * 32)
        player = deepcopy(target["player"])
        player.update(
            input_action="use_item",
            input_item_id=2000000,
            action="skill",
            skill_id=1001004,
            phase="running",
            busy=True,
            held=["right", "use_item"],
        )
        target["player"] = deepcopy(player)
        sibling["player"] = deepcopy(player)
        self.files.state.update(script=sibling, scripts=[target, sibling], held_keys=[39])
        self.files.publish()

        def peer() -> list[str]:
            request = self.files.command()
            target.update(status="cancelled", reason="stop_requested", control_released=True)
            self.files.state["command"] = {"id": request[3], "status": "completed", "reason": None}
            self.files.publish()
            return request

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            report = self.client.cancel_script(target["id"])
            request = native.result(2)
        self.assertEqual(["cancel_script", "0", target["id"]], request[4:])
        self.assertEqual(("cancelled", True, [39]), (report["status"], report["control_released"], report["held_keys"]))
        self.assertEqual(player, report["script"]["player"])
        self.assertNotIn("control_released", report["script"]["player"])
        self.assertEqual("already_stopped", self.client.cancel_script(target["id"])["status"])
        self.assertEqual(request, self.files.command())

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

    def test_snapshot_keeps_the_exact_selected_tick_gear(self) -> None:
        for gear in (1, 2, 3, 4):
            with self.subTest(gear=gear):
                script = tick_state("a" * 32)
                script["tick"]["gear"] = gear
                self.files.state.update(script=script, scripts=[script])
                self.files.publish()
                self.assertEqual(gear, self.client.snapshot()["scripts"][0]["tick"]["gear"])

    def test_snapshot_keeps_positive_int32_input_and_actual_ids(self) -> None:
        for field, action_field, action in (
            ("input_skill_id", "input_action", "skill"),
            ("input_item_id", "input_action", "use_item"),
            ("skill_id", "action", "skill"),
            ("item_id", "action", "use_item"),
        ):
            for identifier in (1, 0x7FFFFFFF):
                with self.subTest(field=field, identifier=identifier):
                    script = tick_state("a" * 32)
                    script["player"].update({field: identifier, action_field: action})
                    self.files.state.update(script=script, scripts=[script])
                    self.files.publish()
                    self.assertEqual(identifier, self.client.snapshot()["script"]["player"][field])

    def test_snapshot_rejects_malformed_input_and_action_fields_in_both_script_projections(self) -> None:
        valid = tick_state("a" * 32)
        player = valid["player"]
        cases = [
            {**player, "phase": "releasing"},
            {**player, "phase": None},
            {**player, "busy": 1},
            {**player, "busy": "unknown"},
            {**player, "dispatched": 0},
            {**player, "moving": "sideways"},
            {**player, "held": "skill"},
            {**player, "held": ["cast"]},
            {**player, "held": [None]},
            {**player, "reason": None},
            {**player, "effect": True},
            *[
                {key: value for key, value in player.items() if key != field}
                for field in ("input_action", "action", "busy", "dispatched")
            ],
            *[
                {**player, field: value}
                for field in ("action", "input_action")
                for value in ("cast", "stop", 1, False, [], {})
            ],
            *[
                {**player, field: value}
                for field in ("input_skill_id", "input_item_id", "skill_id", "item_id")
                for value in (True, 0, -1, 0x80000000, 1.0, "1", None)
            ],
            # 旧形状不能靠pending_action冒充新的输入意图字段。
            {key: value for key, value in {**player, "pending_action": None}.items() if not key.startswith("input_")},
        ]
        for projection in ("script", "scripts"):
            for malformed in cases:
                with self.subTest(projection=projection, player=malformed):
                    script = dict(valid, player=malformed)
                    self.files.state.update(
                        script=script if projection == "script" else None,
                        scripts=[script] if projection == "scripts" else [],
                    )
                    self.files.publish()
                    with self.assertRaises(ClientError) as invalid:
                        self.client.snapshot()
                    self.assertEqual("invalid_bridge_state", invalid.exception.code)
                    self.assertEqual("原生桥的tick角色操作状态字段无效。", invalid.exception.message)

    def package_directory(self, entry: str, modules: dict[str, str] | None = None) -> Path:
        self.package_serial = getattr(self, "package_serial", 0) + 1
        directory = self.files.root / ("policy-" + str(self.package_serial))
        directory.mkdir()
        (directory / "main.lua").write_text(entry, encoding="utf-8")
        for name, source in (modules or {}).items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        return directory

    def test_directory_package_publishes_require_root_and_projects_loaded_modules(self) -> None:
        directory = self.package_directory(
            "-- @mode tick\n"
            "-- @option[type=int,opt,default=2] ticks 观察次数\n"
            'local lib = require("lib.value")\n'
            'function main(context)\n    return "done"\nend\n',
            {"lib/value.lua": "return {}\n"},
        )
        modules = [{"name": "lib.value", "file": str(directory.resolve() / "lib/value.lua")}]

        def peer() -> list[str]:
            request = self.files.command()
            script = tick_state(request[6], stopped=True)
            script.update(
                status="completed",
                reason="script_returned",
                module_root=str(directory.resolve()),
                modules=modules,
            )
            self.files.state.update(
                script=script,
                scripts=[script],
                command={"id": request[3], "status": "completed", "reason": "script_returned"},
            )
            self.files.publish()
            return request

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            code, report = self.cli("script", "run", str(directory), "--ticks", "4", "--seconds", ".3")
            request = native.result(2)
        self.assertEqual(code, 0)
        self.assertEqual(request[4:6], ["script", "300"])
        package = self.files.directory / "scripts" / (request[6] + ".package")
        self.assertEqual(package.read_text(encoding="utf-8"), str(directory.resolve()) + "\n")
        source = (self.files.directory / "scripts" / (request[6] + ".lua")).read_text(encoding="utf-8")
        self.assertIn("__beidou_context", source, "目录入口按策略注入上下文")
        self.assertIn('["ticks"]=4', source)
        self.assertEqual(report["data"]["status"], "completed")
        self.assertEqual(report["data"]["package_root"], str(directory.resolve()))
        self.assertEqual(report["data"]["script_file"], str(directory / "main.lua"))
        self.assertEqual(report["data"]["script"]["modules"], modules)

    def test_rejected_package_reports_the_source_module_and_line(self) -> None:
        directory = self.package_directory(
            "-- @mode tick\n"
            'local broken = require("lib.broken")\n'
            'local function main(context)\n    return "done"\nend\n',
            {"lib/broken.lua": "return {\n    missing = ,\n}\n"},
        )
        previous = tick_state("a" * 32)
        self.files.state.update(script=previous, scripts=[previous])
        self.files.publish()
        error_text = (
            "error loading module 'lib.broken' from file '" + str(directory.resolve() / "lib/broken.lua") + "':\n"
            "\t" + str(directory.resolve() / "lib/broken.lua") + ":2: unexpected symbol near ','\n"
            "stack traceback:\n\tmain.lua:4: in main chunk"
        )

        def peer() -> list[str]:
            request = self.files.command()
            rejected = tick_state(request[6], stopped=True)
            rejected.update(
                status="rejected",
                reason="script_error",
                error=error_text,
                module_root=str(directory.resolve()),
                modules=[],
            )
            self.files.state.update(
                script=previous,
                scripts=[previous, rejected],
                rejected_command={"id": request[3], "status": "rejected", "reason": "script_load_error"},
            )
            self.files.publish()
            return request

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            code, report = self.cli("script", "run", str(directory), "--seconds", ".3")
            native.result(2)
        self.assertEqual(code, 2)
        self.assertEqual(report["error"]["code"], "bridge_command_rejected")
        self.assertEqual(report["error"]["details"]["reason"], "script_load_error")
        script = report["error"]["details"]["script"]
        self.assertEqual(script["status"], "rejected")
        self.assertEqual(script["error"], error_text)
        self.assertEqual(script["module_root"], str(directory.resolve()))
        self.assertEqual(script["modules"], [])

    def test_directory_package_rejects_missing_entry_coroutine_and_library_before_publication(self) -> None:
        empty = self.files.root / "empty"
        empty.mkdir()
        for arguments, code in (
            (("script", "run", str(empty)), "script_package_entry_missing"),
            (
                (
                    "script",
                    "run",
                    str(self.package_directory("function main(context)\nend\n")),
                ),
                "package_requires_tick",
            ),
            (
                (
                    "script",
                    "run",
                    str(self.package_directory('-- @mode tick\nfunction main(context)\n    return "done"\nend\n')),
                    "--library",
                    "travel",
                ),
                "usage",
            ),
        ):
            with self.subTest(code=code):
                result_code, report = self.cli(*arguments)
                self.assertEqual(result_code, 2)
                self.assertEqual(report["error"]["code"], code)
                self.assertFalse((self.files.directory / "command.txt").exists())
                self.assertFalse((self.files.directory / "scripts").exists())

    def test_directory_package_describe_reports_usage_entry_and_tick_options(self) -> None:
        directory = self.package_directory(
            "-- @mode tick\n-- @option[type=int,opt,default=2] ticks 观察次数\nfunction main(context)\nend\n"
        )
        code, report = self.cli("script", "describe", str(directory))
        self.assertEqual(code, 0)
        data = report["data"]
        self.assertEqual(data["file"], str(directory))
        self.assertEqual(data["package_entry"], str(directory / "main.lua"))
        self.assertEqual(data["mode"], "tick")
        self.assertEqual(
            data["usage"],
            "beidou-pilot script run/start " + str(directory) + " [--ticks <int>] [--seconds N|--continuous]",
        )
        self.assertEqual([option["name"] for option in data["options"]], ["ticks"])

    def test_package_root_must_be_an_absolute_container_path(self) -> None:
        with self.assertRaises(ClientError) as invalid:
            self.client.run_script(code=TICK_SOURCE, package_root="relative/path")
        self.assertEqual("invalid_bridge_options", invalid.exception.code)
        self.assertFalse((self.files.directory / "scripts").exists())

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
            [dict(valid, tick={key: value for key, value in valid["tick"].items() if key != "gear"})],
            *[[dict(valid, tick={**valid["tick"], "gear": gear})] for gear in (True, 3.0, "3", 0, -1, 5, None)],
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
