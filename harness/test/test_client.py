"""harness 的本地 CLI 只读合同，不代表真实游戏效果验收。"""

import json
from pathlib import Path
import sys
import tempfile
import unittest

from beidou_game_ai.client import GameClient, GameClientError


FAKE_CLI = r"""
import json
from pathlib import Path
import sys

root = Path(__file__).parent
arguments = sys.argv[1:]
assert arguments[0] == "--json"
command = arguments[1:]
with (root / "calls.jsonl").open("a") as stream:
    stream.write(json.dumps(arguments) + "\n")

if command == ["status"]:
    data = json.loads((root / "status.json").read_text())
elif command == ["bridge", "status"]:
    data = json.loads((root / "bridge.json").read_text())
elif command == ["snapshot"]:
    data = {"stage": "IN_GAME", "character": {"level": 8}, "position": {"x": 3, "y": 4}}
else:
    raise SystemExit("unexpected command")
print(json.dumps({"ok": True, "data": data}), flush=True)
"""


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
        self.state = {
            "instance_id": "native-alpha",
            "run_id": "run-a",
            "seq": 1,
            "observed_at_ms": 0,
            "held_keys": [39],
            "script": {"id": "a" * 32, "status": "running"},
            "scripts": [{"id": "a" * 32, "status": "running"}],
            "command": {"id": "request-a", "status": "running"},
        }
        self.path.write_text(json.dumps(self.state))
        self.client = GameClient(self.cli)

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    async def test_observes_existing_script_command_and_keys_without_control(self) -> None:
        for observation in (
            await self.client.observe(),
            await self.client.observe(),
            await self.client.script_status(),
        ):
            self.assertEqual(
                ("native-alpha", "run-a", "a" * 32, "running", [39], "a" * 32),
                (
                    observation["instance_id"],
                    observation["run_id"],
                    observation["script"]["id"],
                    observation["command"]["status"],
                    observation["held_keys"],
                    observation["scripts"][0]["id"],
                ),
            )
        observation = await GameClient(self.cli).observe()
        self.assertEqual("IN_GAME", observation["snapshot"]["stage"])
        self.assertEqual("a" * 32, observation["script"]["id"])
        self.assertEqual(self.state, json.loads(self.path.read_text()))
        self.assertTrue(
            all(
                call in (["--json", "status"], ["--json", "bridge", "status"], ["--json", "snapshot"])
                for call in self.calls()
            )
        )

    async def test_stopped_instance_observation_does_not_read_bridge(self) -> None:
        status = {"running": False, "stage": "STOPPED"}
        (self.root / "status.json").write_text(json.dumps(status))
        self.path.unlink()
        self.assertEqual({"running": False, "status": status}, await self.client.observe())
        self.assertEqual([["--json", "status"]], self.calls())

    async def test_changed_identity_refuses_continued_observation(self) -> None:
        await self.client.observe()
        self.state["run_id"] = "replacement-run"
        self.path.write_text(json.dumps(self.state))
        with self.assertRaises(GameClientError) as failure:
            await self.client.observe()
        self.assertEqual("client_identity_changed", failure.exception.code)
        self.assertEqual(["--json", "bridge", "status"], self.calls()[-1])


if __name__ == "__main__":
    unittest.main()
