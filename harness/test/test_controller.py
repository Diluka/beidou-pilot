"""控制器的会话与交接合同；替身不证明实际模型或游戏效果。"""

import asyncio
from collections.abc import Callable
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beidou_game_ai.cli import commands
from beidou_game_ai.client import GameClient
from beidou_game_ai.controller import Controller
from beidou_game_ai.protocol import AppServer, AppServerError, JsonObject, JsonValue


class SessionServer(AppServer):
    """只控制 app-server 外部协议响应，不替换控制器的会话规则。"""

    def __init__(self, efforts: list[str]) -> None:
        self.events: asyncio.Queue[JsonObject] = asyncio.Queue()
        self.efforts = efforts
        self.calls: list[tuple[str, JsonObject]] = []
        self.responses: dict[int | str, JsonValue] = {}
        self.fail_response = False
        self.fail_steer = False
        self.pause_before_reply: Controller | None = None
        self.turns = 0
        self.turn_start_entered = asyncio.Event()
        self.turn_start_release = asyncio.Event()
        self.turn_start_release.set()

    async def call(self, method: str, params: JsonObject) -> JsonValue:
        self.calls.append((method, params))
        if method == "initialize":
            return {"userAgent": "contract"}
        if method == "config/read":
            return {"config": {"project_doc_max_bytes": 0, "features": {
                **{name: False for name in ("shell_tool", "apps", "multi_agent", "memories", "goals", "hooks",
                                          "plugins", "image_generation", "view_image", "sleep_tool")},
                "code_mode": {"excluded_tool_namespaces": ["functions", "clock"]}}}}
        if method == "skills/list":
            return {"data": [{"cwd": "/game", "skills": []}]}
        if method == "mcpServerStatus/list":
            return {"data": []}
        if method == "model/list":
            return {"data": [{"model": "gpt-6-luna", "defaultReasoningEffort": "medium",
                "supportedReasoningEfforts": [{"reasoningEffort": effort, "description": effort}
                                              for effort in self.efforts]}], "nextCursor": None}
        if method in {"thread/start", "thread/resume"}:
            return {"thread": {"id": "game-thread"}, "instructionSources": []}
        if method == "turn/start":
            self.turns += 1
            self.turn_start_entered.set()
            await self.turn_start_release.wait()
            return {"turn": {"id": f"turn-{self.turns}"}}
        if method == "turn/steer" and self.fail_steer:
            raise AppServerError(-32600, "No active turn")
        if method in {"turn/steer", "turn/interrupt"}:
            return {}
        raise AssertionError("unexpected method: " + method)

    async def notify(self, method: str, params: JsonObject) -> None:
        self.calls.append((method, params))

    async def respond(self, request_id: int | str, result: JsonValue) -> None:
        if self.fail_response:
            raise AppServerError("transport_closed", "controlled disconnect")
        if self.pause_before_reply is not None and request_id == 1:
            controller, self.pause_before_reply = self.pause_before_reply, None
            await controller.control("pause")
        self.responses[request_id] = result
        if request_id == 77:
            await self.events.put({"method": "serverRequest/resolved", "params": {"requestId": request_id}})
            await asyncio.sleep(0)


class ControlledGame(GameClient):
    """用可等待的游戏/取消边界验证上层，原进程与桥合同另在 test_client 覆盖。"""

    def __init__(self) -> None:
        self.active = False
        self.codes: list[str] = []
        self.observations = 0
        self.release = asyncio.Event()
        self.release.set()
        self.cancel_requested = asyncio.Event()
        self.cancellations = 0

    @property
    def running(self) -> bool:
        return self.active

    async def observe(self) -> JsonObject:
        self.observations += 1
        return {"instance_id": "actor", "run_id": "run", "seq": self.observations,
                "snapshot": {"position": {"x": self.observations}}}

    async def script_status(self) -> JsonObject:
        return {"instance_id": "actor", "run_id": "run", "held_keys": [39] if self.active else []}

    async def run_lua(self, code: str, seconds: float) -> JsonObject:
        self.codes.append(code)
        self.active = True
        await self.release.wait()
        self.active = False
        return {"status": "completed", "cancelled": False}

    async def cancel(self) -> JsonObject:
        self.cancellations += 1
        if self.active:
            self.cancel_requested.set()
            await self.release.wait()
            self.active = False
        return {"instance_id": "actor", "run_id": "run", "held_keys": [],
                "script": {"status": "cancelled"}, "command": {"status": "completed"}}


class ControllerContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name)
        self.server = SessionServer(["medium", "low"])
        self.game = ControlledGame()
        self.binding: JsonObject = {"root": "/dedicated/client", "backend": "headless", "instance": "worker", "read_only": False}
        self.controller = Controller(self.server, self.game, self.state, "gpt-6-luna",
                                     "保留角色养成路线", "在安全区域验证移动与停止", self.binding)
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        self.pumps: list[asyncio.Task[None]] = []
        self.addAsyncCleanup(self.finish_pumps)

    async def finish_pumps(self) -> None:
        for pump in self.pumps:
            if not pump.done():
                await self.server.events.put({"method": "transport/closed", "params": {}})
                await pump

    async def wait_until(self, predicate: Callable[[], bool]) -> None:
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0)

    async def test_initialization_selects_advertised_minimum_and_resumes_own_thread(self) -> None:
        await self.controller.initialize()
        self.assertEqual(("gpt-6-luna", "low"), (self.controller.model, self.controller.effort))
        start = next(params for method, params in self.server.calls if method == "thread/start")
        self.assertIn("保留角色养成路线", start["developerInstructions"])
        self.assertFalse(start["allowProviderModelFallback"])
        self.assertNotIn("model_context_window", start)
        self.assertNotIn("model_auto_compact_token_limit", start)
        second_server = SessionServer(["low", "none"])
        second = Controller(second_server, self.game, self.state, "gpt-6-luna", "相同角色", "续接任务", self.binding)
        await second.initialize()
        self.assertEqual(("game-thread", "none"), (second.thread_id, second.effort))
        resume = next(params for method, params in second_server.calls if method == "thread/resume")
        self.assertEqual("game-thread", resume["threadId"])
        self.assertFalse(any(method == "thread/start" for method, _ in second_server.calls))
        read_only = Controller(self.server, self.game, self.state, "gpt-6-luna", "只读角色", "观察",
                               {**self.binding, "read_only": True}, read_only=True)
        with self.assertRaises(AppServerError) as mismatch:
            await read_only.initialize()
        self.assertEqual("binding_mismatch", mismatch.exception.code)

    async def test_question_answer_and_finished_lua_continue_the_same_session(self) -> None:
        await self.controller.initialize()
        self.pumps.append(asyncio.create_task(self.controller.events()))
        await self.controller.message("执行当前任务")
        await self.server.events.put({"id": 77, "method": "item/tool/requestUserInput", "params": {
            "questions": [{"id": "proceed", "question": "是否继续补充观察？"}]}})
        await self.wait_until(lambda: 77 in self.controller.questions)
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd)
        try:
            with patch("sys.stdin", reader):
                incoming = asyncio.create_task(commands(self.controller))
                os.write(write_fd, (json.dumps({"id": "answer", "command": "answer", "request_id": 77,
                    "answers": {"proceed": {"answers": ["继续"]}}}) + "\n").encode())
                await self.wait_until(lambda: 77 in self.server.responses)
                self.assertEqual({"answers": {"proceed": {"answers": ["继续"]}}}, self.server.responses[77])
                await self.server.events.put({"id": 88, "method": "item/tool/call", "params": {
                    "tool": "game_run_lua", "arguments": {"code": "safe_move", "seconds": 1}}})
                await self.wait_until(lambda: self.controller.last_script is not None)
                await self.wait_until(lambda: any(method == "turn/steer" for method, _ in self.server.calls))
                steer = next(params for method, params in self.server.calls if method == "turn/steer")
                self.assertEqual("game-thread", steer["threadId"])
                self.assertIn("重新观察", steer["input"][0]["text"])
                self.assertEqual(["safe_move"], self.game.codes)
                self.assertEqual(1, sum(method == "thread/start" for method, _ in self.server.calls))
                os.write(write_fd, b'{"id":"stop","command":"stop"}\n')
                await incoming
                self.assertEqual("stopped", self.controller.mode)
        finally:
            os.close(write_fd)
            reader.close()

    async def test_pause_covers_accepted_work_and_waits_for_release_before_resume(self) -> None:
        await self.controller.initialize()
        self.pumps.append(asyncio.create_task(self.controller.events()))
        await self.controller.message("开始")
        # 开发AI在工具请求已受理、回复尚未完成时暂停，Lua任务尚未获得执行机会。
        self.server.pause_before_reply = self.controller
        await self.server.events.put({"id": 1, "method": "item/tool/call", "params": {
            "tool": "game_run_lua", "arguments": {"code": "must_not_start_after_pause", "seconds": 1}}})
        await self.wait_until(lambda: 1 in self.server.responses)
        await self.wait_until(lambda: self.controller.execution is not None and self.controller.execution.done())
        self.assertEqual([], self.game.codes)
        self.assertEqual("paused", self.controller.mode)
        revised_task = "在安全区等待并核对停止"
        await self.controller.update_task(revised_task)
        self.assertEqual(revised_task, self.controller.status()["task"])
        self.assertEqual(revised_task, json.loads((self.state / "checkpoint.json").read_text())["task"])
        await self.controller.control("resume")
        resume_message = [params for method, params in self.server.calls if method == "turn/start"][-1]
        self.assertIn(revised_task, resume_message["input"][0]["text"])
        self.assertEqual(1, self.game.observations)
        self.game.release.clear()
        await self.server.events.put({"id": 2, "method": "item/tool/call", "params": {
            "tool": "game_run_lua", "arguments": {"code": "hold", "seconds": 1}}})
        await self.wait_until(lambda: self.game.running)
        pause = asyncio.create_task(self.controller.control("pause"))
        await self.game.cancel_requested.wait()
        self.assertFalse(pause.done())
        self.assertEqual("pausing", self.controller.mode)
        self.game.release.set()
        await pause
        self.assertEqual("paused", self.controller.mode)
        await self.controller.control("resume")
        self.assertEqual(2, self.game.observations)
        self.assertEqual(["hold"], self.game.codes)
        await self.controller.control("stop")
        self.assertEqual("stopped", self.controller.mode)

    async def test_pause_waits_for_late_turn_start_and_rejects_following_actions(self) -> None:
        await self.controller.initialize()
        self.pumps.append(asyncio.create_task(self.controller.events()))
        self.server.turn_start_release.clear()
        message = asyncio.create_task(self.controller.message("执行当前有界任务"))
        await self.server.turn_start_entered.wait()
        pause = asyncio.create_task(self.controller.control("pause"))
        await self.wait_until(lambda: self.controller.mode == "pausing")
        self.assertFalse(pause.done())
        self.assertFalse(any(method == "turn/interrupt" for method, _ in self.server.calls))
        self.server.turn_start_release.set()
        await asyncio.wait_for(asyncio.gather(message, pause), 2)
        interrupted = next(params for method, params in self.server.calls if method == "turn/interrupt")
        self.assertEqual(("game-thread", "turn-1"), (interrupted["threadId"], interrupted["turnId"]))
        self.assertEqual("paused", self.controller.mode)
        self.assertIsNone(self.controller.turn_id)
        await self.server.events.put({"id": 102, "method": "item/tool/call", "params": {
            "tool": "game_run_lua", "arguments": {"code": "must_not_run", "seconds": 1}}})
        await self.wait_until(lambda: 102 in self.server.responses)
        reply = self.server.responses[102]
        self.assertFalse(reply["success"])
        self.assertEqual("game_paused", json.loads(reply["contentItems"][0]["text"])["error"]["code"])
        self.assertEqual([], self.game.codes)
        self.assertEqual("paused", self.controller.mode)

    async def test_late_completion_preserves_the_resumed_turn_and_its_control(self) -> None:
        await self.controller.initialize()
        self.pumps.append(asyncio.create_task(self.controller.events()))
        await self.controller.message("执行当前任务")
        await self.controller.control("pause")
        await self.controller.control("resume")
        self.assertEqual("turn-2", self.controller.status()["turn_id"])
        await self.server.events.put({"method": "turn/completed", "params": {
            "threadId": "game-thread", "turn": {"id": "turn-1", "status": "interrupted"}}})
        await self.wait_until(self.server.events.empty)
        status = self.controller.status()
        self.assertEqual(("turn-2", "running"), (status["turn_id"], status["mode"]))
        await self.controller.message("补充观察当前任务")
        steer = [params for method, params in self.server.calls if method == "turn/steer"][-1]
        self.assertEqual("turn-2", steer["expectedTurnId"])
        await self.controller.control("pause")
        interrupted = [params for method, params in self.server.calls if method == "turn/interrupt"][-1]
        self.assertEqual("turn-2", interrupted["turnId"])
        await self.controller.control("resume")
        await self.server.events.put({"method": "turn/completed", "params": {
            "threadId": "game-thread", "turn": {"id": "turn-3", "status": "completed"}}})
        await self.wait_until(self.server.events.empty)
        status = self.controller.status()
        self.assertEqual((None, "ready"), (status["turn_id"], status["mode"]))

    async def test_read_only_surface_rejects_lua_and_never_cancels_another_operator(self) -> None:
        read_only = Controller(self.server, self.game, self.state, "gpt-6-luna", "只观察角色", "核对现状",
                               {**self.binding, "read_only": True}, read_only=True)
        await read_only.initialize()
        start = next(params for method, params in self.server.calls if method == "thread/start")
        tools = {tool["name"] for namespace in start["dynamicTools"] for tool in namespace["tools"]}
        self.assertEqual({"game_observe", "game_script_status"}, tools)
        self.assertTrue(read_only.status()["read_only"])
        self.pumps.append(asyncio.create_task(read_only.events()))
        # 另一个明确操作者的Lua仍在执行，只读会话不得接管或取消。
        self.game.active = True
        self.game.release.clear()
        await self.server.events.put({"id": 100, "method": "item/tool/call", "params": {
            "tool": "game_run_lua", "arguments": {"code": "must_not_run", "seconds": 1}}})
        await self.wait_until(lambda: 100 in self.server.responses)
        reply = self.server.responses[100]
        self.assertFalse(reply["success"])
        failure = json.loads(reply["contentItems"][0]["text"])
        self.assertEqual("read_only", failure["error"]["code"])
        await read_only.control("pause")
        await read_only.control("resume")
        await read_only.control("stop")
        self.assertEqual("stopped", read_only.mode)
        self.assertEqual(0, self.game.cancellations)
        self.assertEqual([], self.game.codes)
        self.assertTrue(self.game.active)

    async def test_failed_lua_continuation_wakes_owner_and_preserves_the_failure(self) -> None:
        await self.controller.initialize()
        self.pumps.append(asyncio.create_task(self.controller.events()))
        await self.controller.message("执行有界任务")
        self.server.fail_steer = True
        await self.server.events.put({"id": 101, "method": "item/tool/call", "params": {
            "tool": "game_run_lua", "arguments": {"code": "safe_move", "seconds": 1}}})
        await asyncio.wait_for(self.controller.done.wait(), 2)
        self.assertEqual("error", self.controller.mode)
        self.assertEqual(["safe_move"], self.game.codes)
        records = [json.loads(line) for line in (self.state / "events.jsonl").read_text().splitlines()]
        failure = next(record for record in records if record["event"] == "continuation_failed")
        self.assertEqual((-32600, "No active turn"), (failure["code"], failure["message"]))
        self.assertIsNotNone(self.controller.execution)
        with self.assertRaises(AppServerError) as execution:
            await self.controller.execution
        self.assertEqual(-32600, execution.exception.code)
        self.assertEqual(1, sum(method == "turn/steer" for method, _ in self.server.calls))

    async def test_dynamic_tool_disconnect_propagates_to_the_controller_owner(self) -> None:
        await self.controller.initialize()
        self.server.fail_response = True
        pump = asyncio.create_task(self.controller.events())
        await self.server.events.put({"id": 9, "method": "item/tool/call", "params": {
            "tool": "game_observe", "arguments": {}}})
        with self.assertRaises(ExceptionGroup) as failure:
            await asyncio.wait_for(pump, 2)
        self.assertTrue(any(isinstance(error, AppServerError) and error.code == "transport_closed"
                            for error in failure.exception.exceptions))


if __name__ == "__main__":
    unittest.main()
