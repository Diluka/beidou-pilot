"""真实子进程验证 JSON-RPC 双向接线，不运行模型或游戏。"""

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest

from beidou_game_ai.protocol import AppServer, AppServerError


SERVER = r"""
import json
import sys

def send(message):
    print(json.dumps(message), flush=True)

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({"id": message["id"], "method": "item/tool/call", "params": {"tool": "game_observe"}})
        send({"method": "thread/started", "params": {"thread": {"id": "thread-contract"}}})
        send({"id": message["id"], "result": {"ready": True}})
    elif method == "initialized":
        send({"method": "notice_received", "params": {}})
    elif method == "reject":
        send({"id": message["id"], "error": {"code": -32602, "message": "invalid params", "data": {"field": "model"}}})
    elif method == "exit":
        sys.exit(0)
    elif method == "invalid":
        print("{", flush=True)
        sys.exit(0)
    elif method is None:
        send({"method": "answer_received", "params": {"id": message["id"], "result": message["result"]}})
"""


class AppServerContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.server = await AppServer.start(
            [sys.executable, "-u", "-c", SERVER], Path(directory.name) / "app-server.stderr.log"
        )
        self.addAsyncCleanup(self.server.close)

    async def test_bidirectional_ids_and_notifications_do_not_steal_pending_response(self) -> None:
        self.assertEqual({"ready": True}, await self.server.call("initialize", {}))
        request = await self.server.events.get()
        self.assertEqual((1, "item/tool/call"), (request["id"], request["method"]))
        self.assertEqual("thread/started", (await self.server.events.get())["method"])
        await self.server.respond(1, {"observed": True})
        self.assertEqual(
            {"method": "answer_received", "params": {"id": 1, "result": {"observed": True}}},
            await self.server.events.get(),
        )
        await self.server.notify("initialized", {})
        self.assertEqual("notice_received", (await self.server.events.get())["method"])
        with self.assertRaises(AppServerError) as rejected:
            await self.server.call("reject", {})
        self.assertEqual((-32602, {"field": "model"}), (rejected.exception.code, rejected.exception.details))

    async def test_process_exit_fails_waiting_request(self) -> None:
        with self.assertRaises(AppServerError) as closed:
            await asyncio.wait_for(self.server.call("exit", {}), 2)
        self.assertEqual("transport_closed", closed.exception.code)
        self.assertEqual("transport/closed", (await self.server.events.get())["method"])

    async def test_invalid_json_fails_waiting_request(self) -> None:
        with self.assertRaises(AppServerError) as invalid:
            await asyncio.wait_for(self.server.call("invalid", {}), 2)
        self.assertEqual("invalid_json_rpc", invalid.exception.code)
        event = await self.server.events.get()
        self.assertEqual("invalid_json_rpc", event["params"]["code"])


if __name__ == "__main__":
    unittest.main()
