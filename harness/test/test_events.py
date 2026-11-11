"""真实 Unix WebSocket 和 CLI 子进程验证既有会话的事件投递；不运行模型或游戏。"""

import argparse
import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import cast
import unittest

from websockets.asyncio.server import ServerConnection, unix_serve

from beidou_game_ai.events import run
from beidou_game_ai.protocol import JsonObject


class CodexPeer:
    def __init__(self, active: bool) -> None:
        self.active = active
        self.calls: list[tuple[str, JsonObject]] = []
        self.completion_sent = False
        self.interrupted = asyncio.Event()
        self.websocket: ServerConnection | None = None
        self.finish_before_interrupt = False

    async def handle(self, websocket: ServerConnection) -> None:
        self.websocket = websocket
        async for raw in websocket:
            message = cast(JsonObject, json.loads(raw))
            method = cast(str, message["method"])
            params = cast(JsonObject, message["params"])
            self.calls.append((method, params))
            if method == "initialized":
                continue
            if method == "initialize":
                result: JsonObject = {"userAgent": "contract"}
            elif method == "thread/read":
                result = {"thread": {"id": "receiver", "status": {"type": "active" if self.active else "idle"}}}
            elif method == "thread/resume":
                result = {"thread": {"id": "receiver"}}
            elif method == "thread/turns/list":
                result = {"data": [{"id": "old-turn", "status": "inProgress"}] if self.active else []}
            elif method == "turn/steer":
                result = {"turnId": "old-turn"}
            elif method == "turn/interrupt":
                if self.finish_before_interrupt:
                    self.active = False
                    await websocket.send(
                        json.dumps(
                            {
                                "id": message["id"],
                                "error": {"code": -32600, "message": "No active turn"},
                            }
                        )
                    )
                    continue
                result = {}
            elif method == "turn/start":
                result = {"turn": {"id": "event-turn"}}
            else:
                raise AssertionError("事件通知不应调用 " + method)
            await websocket.send(json.dumps({"id": message["id"], "result": result}))
            if method == "turn/interrupt":
                self.interrupted.set()

    async def complete_interrupt(self) -> None:
        self.active = False
        self.completion_sent = True
        await cast(ServerConnection, self.websocket).send(
            json.dumps(
                {
                    "method": "turn/completed",
                    "params": {"threadId": "receiver", "turn": {"id": "old-turn", "status": "interrupted"}},
                }
            )
        )


class EventConsumerContract(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.socket = self.root / "daemon.sock"

    def message(self, seq: int, event_type: str = "notification.opened", *, expired: bool = False) -> JsonObject:
        now = round(time.time() * 1000)
        return {
            "event": "client_event",
            "backend": "beidou",
            "instance": "default",
            "instance_id": "client",
            "run_id": "run",
            "cursor": {"instance_id": "client", "run_id": "run", "seq": seq},
            "data": {
                "seq": seq,
                "observed_at_ms": now,
                "scene_generation": 1,
                "character_id": 1,
                "type": event_type,
                "source": "client-native-ui",
                "expires_at_ms": now - 1 if expired else None,
                "data": {
                    "id": "current-notification",
                    "kind": None,
                    "native_kind": 99,
                    "source_text": None,
                    "text": None,
                    "buttons": [{"control_id": 2000, "action": "primary"}],
                },
            },
        }

    def arguments(
        self, messages: list[JsonObject], delivery: str = "steer", *, initial_ready: bool = True
    ) -> argparse.Namespace:
        cli = self.root / "client-cli"
        cli.with_suffix(".json").write_text(json.dumps(messages), encoding="utf-8")
        cli.write_text(
            f"#!{sys.executable}\n"
            "import json,pathlib,sys\n"
            "path=pathlib.Path(sys.argv[0])\n"
            "path.with_suffix('.argv').write_text(json.dumps(sys.argv[1:]))\n"
            "assert sys.argv[1:11] == ['--root', str(path.parent), '--backend', 'beidou', '--instance', 'default', '--json', 'events', 'watch', '--interval']\n"
            "cursor={'instance_id':'client','run_id':'run','seq':0}\n"
            + (
                "print(json.dumps({'event':'events_ready','backend':'beidou','instance':'default','instance_id':'client','run_id':'run','cursor':cursor}),flush=True)\n"
                if initial_ready
                else ""
            )
            + "for item in json.loads(path.with_suffix('.json').read_text()): print(json.dumps(item),flush=True)\n",
            encoding="utf-8",
        )
        cli.chmod(0o700)
        return argparse.Namespace(
            cli=cli,
            root=self.root,
            backend="beidou",
            instance="default",
            thread="receiver",
            socket=self.socket,
            state=self.root / "state",
            delivery=delivery,
            rpc_timeout=2,
            interval=0.025,
            seconds=None,
            event_type=["notification.opened"],
            check=False,
        )

    async def consume(self, peer: CodexPeer, args: argparse.Namespace) -> list[JsonObject]:
        output = io.StringIO()
        async with unix_serve(peer.handle, self.socket):
            with redirect_stdout(output):
                await asyncio.wait_for(run(args), 5)
        return [json.loads(line) for line in output.getvalue().splitlines()]

    async def test_active_thread_receives_unknown_notification_without_ending_its_turn(self) -> None:
        peer = CodexPeer(active=True)
        reports = await self.consume(peer, self.arguments([self.message(1)]))
        dispatches = [(method, params) for method, params in peer.calls if method.startswith("turn/")]
        self.assertEqual(["turn/steer"], [method for method, _ in dispatches])
        self.assertEqual("old-turn", dispatches[0][1]["expectedTurnId"])
        forwarded = json.loads(dispatches[0][1]["input"][0]["text"].split("\n", 1)[1])
        self.assertEqual(self.message(1)["data"]["data"], forwarded["data"]["data"])
        self.assertEqual(
            "unknown", next(report for report in reports if report["event"] == "event_delivered")["effect"]
        )

    async def test_idle_thread_wakes_once_and_checkpoint_covers_closed_and_expired_events(self) -> None:
        peer = CodexPeer(active=False)
        args = self.arguments(
            [self.message(1), self.message(1), self.message(2, "notification.closed"), self.message(3, expired=True)]
        )
        reports = await self.consume(peer, args)
        self.assertEqual(["turn/start"], [method for method, _ in peer.calls if method.startswith("turn/")])
        self.assertEqual(
            ["type_not_selected", "expired"],
            [report["reason"] for report in reports if report["event"] == "event_skipped"],
        )
        saved = json.loads((args.state / "cursor.json").read_text())
        self.assertEqual({"instance_id": "client", "run_id": "run", "seq": 3}, saved["cursor"])

    async def test_interrupt_delivery_waits_for_old_turn_completion_then_starts_event_turn(self) -> None:
        peer = CodexPeer(active=True)
        consuming = asyncio.create_task(self.consume(peer, self.arguments([self.message(1)], "interrupt")))
        await asyncio.wait_for(peer.interrupted.wait(), 2)
        await asyncio.sleep(0.02)
        self.assertFalse(any(method == "turn/start" for method, _ in peer.calls))
        await peer.complete_interrupt()
        await consuming
        self.assertTrue(peer.completion_sent)
        self.assertEqual(
            ["turn/interrupt", "turn/start"],
            [method for method, _ in peer.calls if method.startswith("turn/")],
        )

    async def test_successor_client_identity_is_not_forwarded_or_checkpointed(self) -> None:
        peer = CodexPeer(active=False)
        foreign = self.message(1)
        foreign["run_id"] = "successor"
        foreign["cursor"] = {"instance_id": "client", "run_id": "successor", "seq": 1}
        args = self.arguments([foreign])
        with self.assertRaisesRegex(ValueError, "身份已变化"):
            await self.consume(peer, args)
        self.assertFalse(any(method.startswith("turn/") for method, _ in peer.calls))
        self.assertEqual(0, json.loads((args.state / "cursor.json").read_text())["cursor"]["seq"])

    async def test_naturally_finished_turn_does_not_prevent_interrupt_mode_delivery(self) -> None:
        peer = CodexPeer(active=True)
        peer.finish_before_interrupt = True
        reports = await self.consume(peer, self.arguments([self.message(1)], "interrupt"))
        self.assertEqual(
            ["turn/interrupt", "turn/start"],
            [method for method, _ in peer.calls if method.startswith("turn/")],
        )
        self.assertEqual(1, sum(report["event"] == "event_delivered" for report in reports))

    async def test_stale_stream_diagnostics_preserve_cursor_and_do_not_wake_model(self) -> None:
        peer = CodexPeer(active=False)
        metadata: JsonObject = {
            "backend": "beidou",
            "instance": "default",
            "instance_id": "client",
            "run_id": "run",
        }
        ready: JsonObject = {
            "event": "events_ready",
            **metadata,
            "cursor": {"instance_id": "client", "run_id": "run", "seq": 0},
        }
        unavailable: JsonObject = {
            "event": "events_unavailable",
            **metadata,
            "cursor": None,
            "error": {"code": "stale_bridge_state", "message": "采样暂未更新", "details": {"age_seconds": 2}},
        }
        current_cursor: JsonObject = {"instance_id": "client", "run_id": "run", "seq": 1}
        args = self.arguments(
            [
                unavailable,
                ready,
                self.message(1),
                {**unavailable, "cursor": current_cursor},
                {**ready, "cursor": current_cursor},
            ],
            initial_ready=False,
        )
        reports = await self.consume(peer, args)
        self.assertEqual(["turn/start"], [method for method, _ in peer.calls if method.startswith("turn/")])
        diagnostics = [report for report in reports if report["event"] == "events_unavailable"]
        self.assertEqual([None, current_cursor], [report["cursor"] for report in diagnostics])
        self.assertEqual({"age_seconds": 2}, diagnostics[0]["error"]["details"])
        self.assertEqual(current_cursor, json.loads((args.state / "cursor.json").read_text())["cursor"])


if __name__ == "__main__":
    unittest.main()
