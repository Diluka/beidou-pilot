"""宿主适配器到假 CLI 的消费合同，不验证 Lua 解释或游戏效果。"""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest

from beidou_game_ai.client import GameClient, GameClientError


FAKE_CLI = r'''
import json
import os
from pathlib import Path
import signal
import sys
import time

arguments = sys.argv[1:]
root = Path(arguments[arguments.index("--root") + 1])
command = arguments[arguments.index("--json") + 1:]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps({"arguments": arguments, "pid": os.getpid()}) + "\n")
path = root / "bridge.json"

def save(state):
    temporary = path.with_suffix("." + str(os.getpid()) + ".tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(path)

def result(data):
    print(json.dumps({"ok": True, "data": data}), flush=True)

if command == ["status"]:
    result(json.loads((root / "status.json").read_text()))
elif command == ["bridge", "status"]:
    state = json.loads(path.read_text())
    state["seq"] += 1
    state["observed_at_ms"] = int(time.time() * 1000)
    save(state)
    result(state)
elif command == ["snapshot"]:
    result({"stage": "IN_GAME", "character": {"level": 8}, "position": {"x": 3, "y": 4}})
elif command[:2] == ["script", "run"]:
    state = json.loads(path.read_text())
    code = command[command.index("--code") + 1]
    if code in ("hold", "fail_release"):
        def interrupt(number, frame):
            (root / "cancel-requested").write_text(str(os.getpid()))
            if code == "fail_release":
                print(json.dumps({"ok": False, "error": {
                    "code": "bridge_release_unconfirmed", "message": "fake release missing",
                    "details": {"held_keys": [39]}}}), flush=True)
                raise SystemExit(2)
            while not (root / "allow-release").exists():
                time.sleep(0.005)
            state["held_keys"] = []
            state["command"]["status"] = "completed"
            state["script"]["status"] = "cancelled"
            save(state)
            print(json.dumps({"ok": False, "error": {
                "code": "interrupted", "message": "fake interrupted"}}), flush=True)
            raise SystemExit(130)
        signal.signal(signal.SIGINT, interrupt)
        state["held_keys"] = [39]
        state["command"]["status"] = "running"
        state["script"] = {"id": "script-a", "status": "running"}
        save(state)
        while True:
            time.sleep(0.005)
    else:
        result({"status": "completed", "cancelled": False, "last_state": state})
else:
    raise SystemExit("unexpected command")
'''


class ClientContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cli = self.root / "fake-cli"
        self.cli.write_text("#!" + sys.executable + "\n" + FAKE_CLI)
        self.cli.chmod(0o700)
        (self.root / "status.json").write_text('{"running":true,"stage":"IN_GAME"}')
        self.path = self.root / "bridge.json"
        self.path.write_text(json.dumps({
            "instance_id": "native-alpha", "run_id": "run-a", "seq": 1,
            "observed_at_ms": 0, "held_keys": [], "script": None,
            "command": {"id": None, "status": "idle"},
        }))
        self.client = GameClient(self.cli, self.root, "headless", "alpha")

    async def wait_for_held_input(self) -> None:
        async with asyncio.timeout(3):
            while json.loads(self.path.read_text())["held_keys"] != [39]:
                await asyncio.sleep(0.005)

    def calls(self) -> list[dict[str, list[str] | int]]:
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    async def test_observes_and_executes_using_only_fixed_cli_identity(self) -> None:
        observation = await self.client.observe()
        self.assertTrue(observation["running"])
        self.assertEqual(("native-alpha", "run-a", "IN_GAME"),
                         (observation["instance_id"], observation["run_id"], observation["snapshot"]["stage"]))
        code = 'game.log("中文")\n'
        report = await self.client.run_lua(code, 1.25)
        self.assertEqual("completed", report["status"])
        status = await self.client.script_status()
        self.assertEqual(("run-a", [], None), (status["run_id"], status["held_keys"], status["script"]))
        prefix = ["--root", str(self.root), "--backend", "headless", "--instance", "alpha", "--json"]
        commands = []
        for call in self.calls():
            arguments = call["arguments"]
            self.assertEqual(prefix, arguments[:len(prefix)])
            commands.append(arguments[len(prefix):])
        self.assertIn(["script", "run", "--code", code, "--seconds", "1.25"], commands)
        self.assertNotIn(["close"], commands)
        self.assertFalse(self.client.running)

    async def test_stopped_instance_observation_does_not_read_bridge_or_open(self) -> None:
        status = {"running": False, "stage": "STOPPED"}
        (self.root / "status.json").write_text(json.dumps(status))
        self.path.unlink()
        self.assertEqual({"running": False, "status": status}, await self.client.observe())
        self.assertEqual([["status"]], [call["arguments"][-1:] for call in self.calls()])

    async def test_cancel_waits_for_original_process_and_bridge_release(self) -> None:
        script = asyncio.create_task(self.client.run_lua("hold", 60))
        await self.wait_for_held_input()
        with self.assertRaises(GameClientError) as busy:
            await self.client.run_lua("game.attack()", 1)
        self.assertEqual("input_busy", busy.exception.code)
        cancellation = asyncio.create_task(self.client.cancel())
        async with asyncio.timeout(3):
            while not (self.root / "cancel-requested").exists():
                await asyncio.sleep(0.005)
        self.assertFalse(cancellation.done())
        self.assertTrue(self.client.running)
        (self.root / "allow-release").touch()
        state = await cancellation
        report = await script
        self.assertEqual(([], "cancelled", "completed"),
                         (state["held_keys"], state["script"]["status"], state["command"]["status"]))
        self.assertEqual("cancelled", report["status"])
        runs = [call for call in self.calls() if "run" in call["arguments"]]
        self.assertEqual(1, len(runs))
        self.assertEqual(str(runs[0]["pid"]), (self.root / "cancel-requested").read_text())
        self.assertFalse(any("stop" in call["arguments"] or "close" in call["arguments"] for call in self.calls()))

    async def test_changed_identity_refuses_new_control(self) -> None:
        await self.client.observe()
        state = json.loads(self.path.read_text())
        state["run_id"] = "replacement-run"
        self.path.write_text(json.dumps(state))
        with self.assertRaises(GameClientError) as failure:
            await self.client.run_lua("game.attack()", 1)
        self.assertEqual("client_identity_changed", failure.exception.code)
        self.assertFalse(any("run" in call["arguments"] for call in self.calls()))

    async def test_release_failure_stays_a_failure(self) -> None:
        script = asyncio.create_task(self.client.run_lua("fail_release", 60))
        await self.wait_for_held_input()
        with self.assertRaises(GameClientError) as cancellation:
            await self.client.cancel()
        with self.assertRaises(GameClientError) as execution:
            await script
        self.assertEqual("bridge_release_unconfirmed", cancellation.exception.code)
        self.assertEqual("bridge_release_unconfirmed", execution.exception.code)
        self.assertEqual([39], json.loads(self.path.read_text())["held_keys"])


if __name__ == "__main__":
    unittest.main()
