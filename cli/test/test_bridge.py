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


def tick_script(script_id: str, *, status: str = "running", control_released: bool = False,
                reason: str | None = None, error: str | None = None) -> dict:
    return {
        "id": script_id, "status": status, "reason": reason, "error": error,
        "resumes": 0, "budget_yields": 0, "last_resume_us": 0.0, "max_resume_us": 0.0,
        "mode": "tick", "control_released": control_released,
        "tick": {
            "index": 0, "gear": 3, "time": 0.0, "delta": 0.0, "scene_generation": 0,
            "overrun": False, "budget_ms": 100.0, "overrun_policy": "abort",
            "abort_commit": True, "overruns": 0,
        },
        "player": {
            "moving": None, "input_action": None, "action": None, "phase": "idle",
            "busy": None, "held": [], "reason": "", "effect": "", "dispatched": False,
        },
    }


TICK_SOURCE = (
    ""
    "local function main(context)\r\n"
    '    game.log("中文 \\"引号\\"")\r\n'
    "end\r\n"
)


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
            "script": None, "scripts": [],
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

    def start_script(self, command: list[str], *, held_keys: list[int] | None = None) -> dict:
        script = tick_script(command[6], status="running", control_released=False)
        self.state["script"] = script
        self.state["scripts"] = [script]
        self.state["command"] = {"id": command[3], "status": "running", "reason": None}
        self.state["held_keys"] = [39] if held_keys is None else held_keys
        self.publish()
        return script

    def finish_script(self, script_id: str, *, status: str = "completed", error: str | None = None,
                      reason: str | None = None) -> None:
        script = tick_script(script_id, status=status, control_released=True)
        script.update(error=error, reason=reason)
        self.state["script"] = script
        self.state["scripts"] = [item for item in self.state["scripts"] if item["id"] != script_id] + [script]
        self.state["command"] = {"id": self.state["command"]["id"], "status": "completed", "reason": None}
        self.state["held_keys"] = []
        self.publish()

    def complete_stop(self, original_id: str) -> list[str]:
        command = self.command(original_id)
        if command[4:] != ["stop", "0"]:
            raise AssertionError("stop后应发送独立stop命令")
        self.state["held_keys"] = []
        self.state["command"] = {"id": command[3], "status": "completed", "reason": None}
        for script in self.state.get("scripts", []):
            if script["status"] == "running":
                script["status"] = "cancelled"
                script["control_released"] = True
        if self.state.get("script") is not None and self.state["script"]["status"] == "running":
            self.state["script"]["status"] = "cancelled"
            self.state["script"]["control_released"] = True
        self.state["input_events"] += 1
        self.publish()
        return command

    def complete_cancel(self, original_id: str, script_id: str) -> list[str]:
        command = self.command(original_id)
        if command[4:] != ["cancel_script", "0", script_id]:
            raise AssertionError("取消后应发送目标cancel_script命令")
        cancelled = tick_script(script_id, status="cancelled", control_released=True, reason="stop_requested")
        self.state["scripts"] = [item for item in self.state.get("scripts", []) if item["id"] != script_id]
        self.state["scripts"].append(cancelled)
        if self.state.get("script") is not None and self.state["script"]["id"] == script_id:
            self.state["script"] = cancelled
        self.state["command"] = {"id": command[3], "status": "completed", "reason": None}
        self.state["held_keys"] = []
        self.publish()
        return command


class BridgeContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = BridgeFiles(Path(temporary.name))
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.client = BridgeClient(self.files.root)
        self.path = self.files.root / "control.lua"
        self.path.write_bytes(TICK_SOURCE.encode("utf-8"))

    def cli(self, *arguments: str) -> tuple[int, dict]:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["--root", str(self.files.root), "--json", *arguments])
        return exit_code, json.loads(output.getvalue())

    def test_cli_copies_compiled_tick_script_and_reports_identity(self) -> None:
        def peer() -> tuple[list[str], bytes]:
            command = self.files.command()
            source = (self.files.directory / "scripts" / (command[6] + ".lua")).read_bytes()
            self.files.start_script(command)
            self.files.finish_script(command[6])
            return command, source

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            exit_code, report = self.cli("script", "run", str(self.path), "--seconds", "1.25")
            command, published = native.result(3)
        self.assertEqual(0, exit_code, report)
        self.assertEqual([1, "client-1", "script", 1250],
                         [int(command[0]), command[1], command[4], int(command[5])])
        text = published.decode("utf-8")
        self.assertIn('game.log("中文 \\"引号\\"")', text)
        self.assertIn("return {main=main,context=__beidou_context}", text)
        data = report["data"]
        self.assertEqual((str(self.path), "tick", False, "completed"),
                         (data["script_file"], data["mode"], data["continuous"], data["status"]))
        self.assertEqual("main(context)", data["policy_entry"])

    def test_continuous_script_reports_running_until_cancelled(self) -> None:
        def peer() -> list[str]:
            command = self.files.command()
            self.files.start_script(command)
            return self.files.complete_cancel(command[3], command[6])

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            exit_code, report = self.cli("script", "start", str(self.path), "--continuous")
            data = report["data"]
            self.assertEqual(0, exit_code, report)
            self.assertEqual(("running", None, True), (data["status"], data["seconds"], data["continuous"]))
            self.assertEqual([39], self.client.snapshot()["held_keys"])
            exit_code, cancelled = self.cli("script", "cancel", "--session", data["script_id"])
            native.result(3)
        self.assertEqual(0, exit_code, cancelled)
        self.assertEqual(("cancelled", [], data["script_id"]),
                         (cancelled["data"]["status"], cancelled["data"]["held_keys"],
                          cancelled["data"]["script_id"]))

    def test_cli_rejects_missing_or_removed_script_inputs(self) -> None:
        cases = (
            ("script", "run"),
            ("script", "start"),
            ("script", "run", str(self.path), "--code", "function main(context) end"),
            ("script", "run", str(self.path), "--library", "travel"),
            ("script", "status", str(self.path)),
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                exit_code, report = self.cli(*arguments)
                self.assertEqual(2, exit_code)
                self.assertFalse((self.files.directory / "command.txt").exists())
                self.assertIn(report["error"]["code"], {"usage", "invalid_strategy_option"})

    def test_scene_loading_pause_can_resume_within_the_script_deadline(self) -> None:
        def peer() -> str:
            command = self.files.command()
            self.files.start_script(command)
            # 真实换图暂停采样；恢复后的状态仍归属于同一原生进程和脚本。
            time.sleep(1.1)
            self.files.state["scene_generation"] = 2
            self.files.state["map_id"] = 200
            self.files.finish_script(command[6])
            self.files.state["script"]["tick"]["scene_generation"] = 2
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

    def test_wait_timeout_preserves_native_script_until_explicit_cancel(self) -> None:
        def peer() -> None:
            command = self.files.command()
            self.files.start_script(command)
            cancel_command = self.files.command(command[3])
            self.files.state["script"]["status"] = "cancelled"
            self.files.state["script"]["control_released"] = True
            self.files.state["command"] = {"id": cancel_command[3], "status": "completed", "reason": None}
            self.files.state["held_keys"] = []
            self.files.publish()

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            with self.assertRaises(ClientError) as failure:
                self.client.run_script(self.path, seconds=1, timeout=.04)
            command = self.files.command()
            self.assertEqual("bridge_timeout", failure.exception.code)
            self.assertEqual("script", command[4])
            state = self.client.snapshot()
            self.assertEqual((command[6], "running", [39]),
                             (state["script"]["id"], state["script"]["status"], state["held_keys"]))
            self.client.cancel_script(command[6])
            native.result(2)
        self.assertEqual(self.client.snapshot()["script"]["status"], "cancelled")

    def test_async_start_returns_while_native_script_runs_until_targeted_cancel(self) -> None:
        def peer() -> list[str]:
            command = self.files.command()
            self.files.start_script(command)
            return self.files.complete_cancel(command[3], command[6])

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            exit_code, report = self.cli("script", "start", str(self.path), "--continuous")
            data = report["data"]
            self.assertEqual(0, exit_code, report)
            self.assertEqual(("running", "client-1", "bridge-contract"),
                             (data["status"], data["instance_id"], data["run_id"]))
            self.assertEqual([39], self.client.snapshot()["held_keys"])
            exit_code, busy = self.cli("notifications", "respond", "old-ref", "--button", "2000")
            self.assertEqual("input_busy", busy["error"]["code"])
            exit_code, cancelled = self.cli("script", "cancel", "--session", data["script_id"])
            cancel = native.result(3)
        self.assertEqual(0, exit_code, cancelled)
        self.assertEqual(("cancelled", [], data["script_id"]),
                         (cancelled["data"]["status"], cancelled["data"]["held_keys"],
                          cancelled["data"]["script_id"]))
        self.assertEqual(cancel[3], cancelled["data"]["request_id"])
        self.assertEqual("already_stopped", self.client.cancel_script(data["script_id"])["status"])

    def test_targeted_cancel_refuses_previous_script_without_stopping_current_owner(self) -> None:
        self.files.state["script"] = tick_script("a" * 32)
        self.files.state["scripts"] = [tick_script("a" * 32)]
        self.files.state["held_keys"] = [39]
        self.files.publish()
        with self.assertRaises(ClientError) as failure:
            self.client.cancel_script("b" * 32)
        self.assertEqual("script_session_mismatch", failure.exception.code)
        self.assertEqual([39], self.client.snapshot()["held_keys"])
        self.assertFalse((self.files.directory / "command.txt").exists())

    def test_rejected_admission_does_not_stop_another_owner(self) -> None:
        def peer() -> None:
            command = self.files.command()
            self.files.state["script"] = tick_script("a" * 32)
            self.files.state["scripts"] = [tick_script("a" * 32)]
            self.files.state["command"] = {"id": "other-owner", "status": "running", "reason": None}
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

    def test_stop_requires_release_confirmation(self) -> None:
        def peer() -> list[str]:
            command = self.files.command()
            self.files.state["command"] = {"id": command[3], "status": "completed", "reason": None}
            self.files.state["held_keys"] = []
            self.files.publish()
            return command

        with ThreadPoolExecutor(max_workers=1) as pool:
            native = pool.submit(peer)
            report = self.client.stop(timeout=2)
            command = native.result(3)
        self.assertEqual(("completed", []), (report["status"], report["held_keys"]))
        self.assertEqual(command[4:], ["stop", "0"])

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

    def test_coroutine_or_incomplete_script_state_is_invalid(self) -> None:
        cases = (
            {"mode": "coroutine"},
            {"mode": "tick", "tick": None},
            {"mode": "tick", "player": None},
            {"mode": "tick", "control_released": "no"},
        )
        for override in cases:
            with self.subTest(override=override):
                script = tick_script("c" * 32)
                script.update(override)
                self.files.state["script"] = script
                self.files.state["scripts"] = [script]
                self.files.publish()
                with self.assertRaises(ClientError) as failure:
                    self.client.snapshot()
                self.assertEqual("invalid_bridge_state", failure.exception.code)

    def test_revive_is_valid_only_as_input_action_in_running_script_state(self) -> None:
        script = tick_script("e" * 32)
        script["player"].update(
            input_action="revive", reason="revive_request_dispatched", dispatched=True
        )
        self.files.state["script"] = script
        self.files.state["scripts"] = [script]
        self.files.publish()

        state = self.client.snapshot()

        self.assertEqual("revive", state["script"]["player"]["input_action"])
        self.assertIsNone(state["script"]["player"]["action"])

    def test_auto_ap_is_valid_as_input_action_in_running_script_state(self) -> None:
        script = tick_script("d" * 32)
        script["player"].update(input_action="auto_ap", reason="", dispatched=False)
        self.files.state["script"] = script
        self.files.state["scripts"] = [script]
        self.files.publish()
        state = self.client.snapshot()
        self.assertEqual("auto_ap", state["script"]["player"]["input_action"])

    def test_revive_cannot_be_a_native_action_or_held_key(self) -> None:
        for field, value in (("action", "revive"), ("held", ["revive"])):
            with self.subTest(field=field):
                script = tick_script("f" * 32)
                script["player"][field] = value
                self.files.state["script"] = script
                self.files.state["scripts"] = [script]
                self.files.publish()

                with self.assertRaises(ClientError) as failure:
                    self.client.snapshot()

                self.assertEqual("invalid_bridge_state", failure.exception.code)

    def test_skill_up_record_validation(self) -> None:
        record = {'request_id': 'a' * 32, 'run_id': 'bridge-contract', 'instance_id': 'client-1',
                  'character_id': 4, 'skill_id': 1000, 'scene_generation': 1, 'job': 100,
                  'beginner': True, 'level_before': 0, 'sp_before': 1, 'status': 'confirmed'}
        self.files.state['skill_up_records'] = [record]
        self.files.publish()
        self.assertEqual(self.client.snapshot()['skill_up_records'], [record])
        for field in record:
            with self.subTest(missing=field):
                broken = {key: value for key, value in record.items() if key != field}
                self.files.state['skill_up_records'] = [broken]
                self.files.publish()
                with self.assertRaises(ClientError) as error:
                    self.client.snapshot()
                self.assertEqual(error.exception.code, 'invalid_bridge_state')
        for field, value in [('character_id', True), ('skill_id', True), ('scene_generation', True),
                             ('job', True), ('level_before', True), ('sp_before', True), ('beginner', 1),
                             ('request_id', 'bad!'), ('run_id', 'old'), ('instance_id', 'other'),
                             ('status', 'completed'), ('skill_id', 0), ('character_id', -1),
                             ('scene_generation', -1), ('job', -1), ('level_before', -1), ('sp_before', -1)]:
            with self.subTest(field=field):
                self.files.state['skill_up_records'] = [{**record, field: value}]
                self.files.publish()
                with self.assertRaises(ClientError) as error:
                    self.client.snapshot()
                self.assertEqual(error.exception.code, 'invalid_bridge_state')
        for value in (None, {}, [None]):
            with self.subTest(records=value):
                self.files.state['skill_up_records'] = value
                self.files.publish()
                with self.assertRaises(ClientError):
                    self.client.snapshot()
        self.files.state['skill_up_records'] = [record, record]
        self.files.publish()
        with self.assertRaises(ClientError):
            self.client.snapshot()
        del self.files.state['skill_up_records']
        self.files.publish()
        self.assertNotIn('skill_up_records', self.client.snapshot())

    def test_unknown_backend_fields_are_tolerated(self) -> None:
        self.files.state["future_field"] = {"nested": [1, 2]}
        self.files.state["script"] = {**tick_script("d" * 32), "future_script_field": True}
        self.files.state["scripts"] = [self.files.state["script"]]
        self.files.publish()
        state = self.client.snapshot()
        self.assertEqual("tick", state["script"]["mode"])


if __name__ == "__main__":
    unittest.main()
