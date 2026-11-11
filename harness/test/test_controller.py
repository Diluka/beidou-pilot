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
from beidou_game_ai.controller import Controller, SKILL_NAME, SKILL_PATH
from beidou_game_ai.protocol import AppServer, AppServerError, JsonObject, JsonValue


class SessionServer(AppServer):
    """只控制 app-server 外部协议响应，不替换控制器的会话规则。"""

    def __init__(self, efforts: list[str], *, read_only: bool = False) -> None:
        self.events: asyncio.Queue[JsonObject] = asyncio.Queue()
        self.efforts = efforts
        self.read_only = read_only
        self.calls: list[tuple[str, JsonObject]] = []
        self.responses: dict[int | str, JsonValue] = {}
        self.fail_response = False
        self.fail_steer = False
        self.finish_before_interrupt = False
        self.fail_start = False
        self.complete_on_interrupt = True
        self.skill_names = [SKILL_NAME]
        self.turns = 0
        self.turn_start_entered = asyncio.Event()
        self.turn_start_release = asyncio.Event()
        self.turn_start_release.set()

    async def call(self, method: str, params: JsonObject) -> JsonValue:
        self.calls.append((method, params))
        if method == "initialize":
            return {"userAgent": "contract"}
        if method == "config/read":
            return {
                "config": {
                    "project_doc_max_bytes": 0,
                    "features": {
                        **{
                            name: False
                            for name in (
                                "apps",
                                "multi_agent",
                                "memories",
                                "goals",
                                "hooks",
                                "plugins",
                                "image_generation",
                                "view_image",
                                "sleep_tool",
                            )
                        },
                        "shell_tool": not self.read_only,
                        "code_mode": {
                            "excluded_tool_namespaces": ["functions", "clock"] if self.read_only else ["clock"]
                        },
                    },
                }
            }
        if method == "skills/list":
            return {
                "data": [
                    {
                        "cwd": "/game",
                        "skills": [{"name": name, "path": SKILL_PATH, "enabled": True} for name in self.skill_names],
                    }
                ]
            }
        if method == "mcpServerStatus/list":
            return {"data": []}
        if method == "model/list":
            return {
                "data": [
                    {
                        "model": "gpt-6-luna",
                        "defaultReasoningEffort": "medium",
                        "supportedReasoningEfforts": [
                            {"reasoningEffort": effort, "description": effort} for effort in self.efforts
                        ],
                    }
                ],
                "nextCursor": None,
            }
        if method in {"thread/start", "thread/resume"}:
            return {"thread": {"id": "game-thread"}, "instructionSources": []}
        if method == "turn/start":
            self.turns += 1
            identifier = f"turn-{self.turns}"
            self.turn_start_entered.set()
            await self.turn_start_release.wait()
            if self.fail_start:
                raise AppServerError("transport_closed", "start response lost")
            return {"turn": {"id": identifier}}
        if method == "turn/steer":
            if self.fail_steer:
                raise AppServerError(-32600, "No active turn")
            return {}
        if method == "turn/interrupt":
            if self.finish_before_interrupt:
                await self.complete(str(params["turnId"]))
                raise AppServerError(-32600, "No active turn to interrupt")
            if self.complete_on_interrupt:
                await self.complete(str(params["turnId"]), "interrupted")
            return {}
        raise AssertionError("unexpected method: " + method)

    async def complete(self, identifier: str, status: str = "completed") -> None:
        await self.events.put(
            {
                "method": "turn/completed",
                "params": {"threadId": "game-thread", "turn": {"id": identifier, "status": status}},
            }
        )

    async def notify(self, method: str, params: JsonObject) -> None:
        self.calls.append((method, params))

    async def respond(self, request_id: int | str, result: JsonValue) -> None:
        if self.fail_response:
            raise AppServerError("transport_closed", "controlled disconnect")
        self.responses[request_id] = result
        if request_id == 77:
            await self.events.put({"method": "serverRequest/resolved", "params": {"requestId": request_id}})


class ControlledGame(GameClient):
    """只提供观察协议，不能替控制器启动、取消或关闭游戏任务。"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.observations = 0
        self.script: JsonObject = {"id": "native-task", "status": "running"}

    async def observe(self) -> JsonObject:
        self.calls.append("observe")
        self.observations += 1
        return {
            "instance_id": "actor",
            "run_id": "run",
            "seq": self.observations,
            "script": self.script,
            "command": {"status": "running"},
            "held_keys": [39],
            "snapshot": {"position": {"x": self.observations}},
        }

    async def script_status(self) -> JsonObject:
        self.calls.append("script_status")
        return {"instance_id": "actor", "run_id": "run", "script": self.script, "held_keys": [39]}


class ControllerContract(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name)
        self.server = SessionServer(["medium", "low"])
        self.game = ControlledGame()
        self.binding: JsonObject = {
            "cli": "/usr/local/bin/beidou-pilot",
            "workbench_id": "dedicated",
            "character_id": 23,
            "read_only": False,
        }
        self.controller = Controller(
            self.server,
            self.game,
            self.state,
            "gpt-6-luna",
            "保留角色养成路线",
            "在安全区域验证移动与停止",
            self.binding,
        )
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        self.pumps: list[tuple[Controller, asyncio.Task[None]]] = []
        self.addAsyncCleanup(self.finish_pumps)

    async def finish_pumps(self) -> None:
        for controller, pump in self.pumps:
            if not pump.done():
                await controller.server.events.put({"method": "transport/closed", "params": {}})
                await asyncio.wait_for(pump, 2)

    async def wait_until(self, predicate: Callable[[], bool]) -> None:
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0)

    def pump(self, controller: Controller | None = None) -> None:
        selected = controller or self.controller
        self.pumps.append((selected, asyncio.create_task(selected.events())))

    async def test_cli_surface_selects_minimum_effort_and_resumes_own_thread(self) -> None:
        await self.controller.initialize()
        self.assertEqual(("gpt-6-luna", "low"), (self.controller.model, self.controller.effort))
        start = next(params for method, params in self.server.calls if method == "thread/start")
        self.assertIn("保留角色养成路线", start["developerInstructions"])
        self.assertFalse(start["allowProviderModelFallback"])
        self.assertNotIn("dynamicTools", start)
        self.assertEqual("danger-full-access", start["sandbox"])
        self.assertNotIn("model_context_window", start)
        self.assertEqual([], self.game.calls)
        await self.controller.message("开始")
        turn = next(params for method, params in self.server.calls if method == "turn/start")
        self.assertEqual({"type": "skill", "name": SKILL_NAME, "path": SKILL_PATH}, turn["input"][0])
        second_server = SessionServer(["low", "none"])
        second = Controller(second_server, self.game, self.state, "gpt-6-luna", "相同角色", "续接任务", self.binding)
        await second.initialize()
        self.assertEqual(("game-thread", "none"), (second.thread_id, second.effort))
        resume = next(params for method, params in second_server.calls if method == "thread/resume")
        self.assertEqual("game-thread", resume["threadId"])
        self.assertNotIn("dynamicTools", resume)
        self.assertEqual("cli-v1", json.loads((self.state / "checkpoint.json").read_text())["tool_surface"])
        self.assertFalse(any(method == "thread/start" for method, _ in second_server.calls))

    async def test_legacy_surface_and_binding_mismatch_preserve_checkpoint(self) -> None:
        for surface in (None, "lua-v1", "hunt-v1"):
            with self.subTest(surface=surface):
                saved = {"thread_id": "game-thread", "binding": self.binding, "model": "gpt-6-luna", "task": "旧任务"}
                if surface is not None:
                    saved["tool_surface"] = surface
                original = json.dumps(saved)
                (self.state / "checkpoint.json").write_text(original)
                with self.assertRaises(AppServerError) as failure:
                    await self.controller.initialize()
                self.assertEqual("tool_surface_mismatch", failure.exception.code)
                self.assertEqual(original, (self.state / "checkpoint.json").read_text())
        saved["binding"] = {**self.binding, "instance": "default"}
        (self.state / "checkpoint.json").write_text(json.dumps(saved))
        with self.assertRaises(AppServerError) as failure:
            await self.controller.initialize()
        self.assertEqual("binding_mismatch", failure.exception.code)
        self.assertFalse(any(method in {"thread/start", "thread/resume"} for method, _ in self.server.calls))

    async def test_only_extra_context_blocks_attachment_not_existing_game_tasks(self) -> None:
        self.server.skill_names.append("unrelated")
        with self.assertRaises(AppServerError) as failure:
            await self.controller.initialize()
        self.assertEqual("context_not_isolated", failure.exception.code)
        self.server.skill_names = [SKILL_NAME]
        await self.controller.initialize()
        self.assertEqual("ready", self.controller.mode)
        self.assertEqual({"id": "native-task", "status": "running"}, self.game.script)
        self.assertEqual([], self.game.calls)
        start = next(params for method, params in self.server.calls if method == "thread/start")
        self.assertIn("已有脚本或命令 running 时只观察", start["developerInstructions"])
        self.assertIn("原生 script start", start["developerInstructions"])

    async def test_question_answer_messages_and_usage_keep_the_same_session(self) -> None:
        await self.controller.initialize()
        self.pump()
        await self.controller.message("执行当前任务")
        await self.server.events.put(
            {
                "id": 77,
                "method": "item/tool/requestUserInput",
                "params": {"questions": [{"id": "proceed", "question": "是否继续补充观察？"}]},
            }
        )
        await self.server.events.put(
            {"method": "thread/tokenUsage/updated", "params": {"tokenUsage": {"total": {"totalTokens": 12}}}}
        )
        await self.wait_until(lambda: 77 in self.controller.questions)
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd)
        try:
            with patch("sys.stdin", reader):
                incoming = asyncio.create_task(commands(self.controller))
                os.write(
                    write_fd,
                    (
                        json.dumps(
                            {
                                "id": "answer",
                                "command": "answer",
                                "request_id": 77,
                                "answers": {"proceed": {"answers": ["继续"]}},
                            }
                        )
                        + "\n"
                    ).encode(),
                )
                await self.wait_until(lambda: 77 in self.server.responses)
                self.assertEqual({"answers": {"proceed": {"answers": ["继续"]}}}, self.server.responses[77])
                await self.controller.message("补充当前任务")
                steer = next(params for method, params in self.server.calls if method == "turn/steer")
                self.assertEqual("turn-1", steer["expectedTurnId"])
                os.write(write_fd, b'{"id":"stop","command":"stop"}\n')
                await asyncio.wait_for(incoming, 2)
                self.assertEqual("stopped", self.controller.mode)
                self.assertEqual(1, self.controller.status()["token_usage_updates"])
        finally:
            os.close(write_fd)
            reader.close()

    async def test_pause_only_stops_llm_and_resume_observes_the_existing_task(self) -> None:
        await self.controller.initialize()
        self.pump()
        await self.controller.message("开始")
        self.server.complete_on_interrupt = False
        pause = asyncio.create_task(self.controller.control("pause"))
        await self.wait_until(lambda: any(method == "turn/interrupt" for method, _ in self.server.calls))
        self.assertEqual("pausing", self.controller.mode)
        self.assertEqual([], self.game.calls)
        self.assertFalse(pause.done())
        await self.controller.message("暂停期间的补充")
        await self.server.complete("unrelated-turn", "interrupted")
        await self.wait_until(self.server.events.empty)
        self.assertFalse(pause.done())
        await self.server.complete("turn-1", "interrupted")
        await asyncio.wait_for(pause, 2)
        self.assertEqual("paused", self.controller.mode)
        self.assertEqual([], self.game.calls)
        self.assertFalse(self.pumps[0][1].done())
        revised = "观察已运行的养成任务"
        await self.controller.update_task(revised)
        self.assertEqual(revised, json.loads((self.state / "checkpoint.json").read_text())["task"])
        await self.controller.control("resume")
        self.assertIs(self.server, self.controller.server)
        resumed = [params for method, params in self.server.calls if method == "turn/start"][-1]
        text = resumed["input"][-1]["text"]
        self.assertIn(revised, text)
        self.assertIn("暂停期间的补充", text)
        self.assertIn('"id": "native-task"', text)
        self.assertIn('"status": "running"', text)
        self.assertIn("不重复启动或抢占", text)
        self.assertEqual(["observe"], self.game.calls)
        self.assertEqual(1, sum(method == "thread/start" for method, _ in self.server.calls))
        self.assertFalse(any(method == "thread/resume" for method, _ in self.server.calls))
        self.server.complete_on_interrupt = True
        await self.controller.control("stop")
        self.assertEqual("stopped", self.controller.mode)
        self.assertEqual(["observe"], self.game.calls)

    async def test_pause_waits_for_delayed_start_id_before_interrupt_and_terminal(self) -> None:
        await self.controller.initialize()
        self.pump()
        self.server.complete_on_interrupt = False
        self.server.turn_start_release.clear()
        message = asyncio.create_task(self.controller.message("执行当前任务"))
        await self.server.turn_start_entered.wait()
        pause = asyncio.create_task(self.controller.control("pause"))
        await self.wait_until(lambda: self.controller.mode == "pausing")
        self.assertFalse(any(method == "turn/interrupt" for method, _ in self.server.calls))
        self.server.turn_start_release.set()
        await message
        await self.wait_until(lambda: any(method == "turn/interrupt" for method, _ in self.server.calls))
        interrupted = next(params for method, params in self.server.calls if method == "turn/interrupt")
        self.assertEqual("turn-1", interrupted["turnId"])
        self.assertEqual([], self.game.calls)
        await self.server.complete("turn-1", "interrupted")
        await asyncio.wait_for(pause, 2)
        self.assertEqual(("paused", None), (self.controller.mode, self.controller.turn_id))

    async def test_lost_start_response_preserves_llm_error(self) -> None:
        await self.controller.initialize()
        self.pump()
        self.server.fail_start = True
        self.server.turn_start_release.clear()
        starting = asyncio.create_task(self.controller.message("开始"))
        await self.server.turn_start_entered.wait()
        await self.server.events.put({"method": "transport/closed", "params": {}})
        await asyncio.wait_for(self.controller.done.wait(), 2)
        self.assertIsNone(self.controller.turn_id)
        self.assertEqual([], self.game.calls)
        self.server.turn_start_release.set()
        with self.assertRaises(AppServerError):
            await starting
        with self.assertRaises(AppServerError) as failure:
            await self.controller.control("stop")
        self.assertEqual("model_turn_unconfirmed", failure.exception.code)
        self.assertEqual("error", self.controller.mode)
        self.assertEqual([], self.game.calls)

    async def test_natural_completion_racing_interrupt_still_requires_terminal(self) -> None:
        await self.controller.initialize()
        self.pump()
        await self.controller.message("开始")
        self.server.finish_before_interrupt = True
        await asyncio.wait_for(self.controller.control("pause"), 2)
        self.assertEqual(("paused", None), (self.controller.mode, self.controller.turn_id))
        self.assertEqual([], self.game.calls)

    async def test_steer_failure_propagates_without_restarting_thread(self) -> None:
        await self.controller.initialize()
        await self.controller.message("开始")
        self.server.fail_steer = True
        with self.assertRaises(AppServerError) as failure:
            await self.controller.message("补充")
        self.assertEqual(-32600, failure.exception.code)
        self.assertEqual(1, sum(method == "thread/start" for method, _ in self.server.calls))

    async def test_late_old_completion_preserves_resumed_turn(self) -> None:
        await self.controller.initialize()
        self.pump()
        await self.controller.message("开始")
        await self.controller.control("pause")
        await self.controller.control("resume")
        await self.server.complete("turn-1", "interrupted")
        await self.wait_until(self.server.events.empty)
        self.assertEqual(("turn-2", "running"), (self.controller.turn_id, self.controller.mode))
        await self.controller.message("当前任务补充")
        steer = [params for method, params in self.server.calls if method == "turn/steer"][-1]
        self.assertEqual("turn-2", steer["expectedTurnId"])
        await self.server.complete("turn-2")
        await self.wait_until(lambda: self.controller.turn_id is None)
        self.assertEqual("ready", self.controller.mode)

    async def test_read_only_surface_observes_without_takeover_or_cancel(self) -> None:
        self.server.read_only = True
        observer = Controller(
            self.server,
            self.game,
            self.state,
            "gpt-6-luna",
            "只观察",
            "核对现状",
            {**self.binding, "read_only": True},
            read_only=True,
        )
        await observer.initialize()
        start = next(params for method, params in self.server.calls if method == "thread/start")
        self.assertEqual("read-only", start["sandbox"])
        self.assertEqual(
            {"game_observe", "game_script_status"},
            {tool["name"] for namespace in start["dynamicTools"] for tool in namespace["tools"]},
        )
        self.pump(observer)
        await observer.message("观察")
        turn = next(params for method, params in self.server.calls if method == "turn/start")
        self.assertEqual([{"type": "text", "text": "观察"}], turn["input"])
        for identifier, tool in ((1, "game_observe"), (2, "game_script_status"), (3, "game_run_lua")):
            await self.server.events.put(
                {"id": identifier, "method": "item/tool/call", "params": {"tool": tool, "arguments": {}}}
            )
            await self.wait_until(lambda: identifier in self.server.responses)
            self.assertEqual(identifier != 3, self.server.responses[identifier]["success"])
        await observer.control("pause")
        await observer.control("resume")
        await observer.control("stop")
        self.assertEqual(["observe", "script_status", "observe"], self.game.calls)
        self.assertEqual({"id": "native-task", "status": "running"}, self.game.script)

    async def test_normal_mode_refuses_dynamic_tool_requests(self) -> None:
        await self.controller.initialize()
        self.pump()
        await self.server.events.put(
            {"id": 9, "method": "item/tool/call", "params": {"tool": "game_observe", "arguments": {}}}
        )
        await self.wait_until(lambda: 9 in self.server.responses)
        self.assertFalse(self.server.responses[9]["success"])
        self.assertEqual(0, self.game.observations)

    async def test_transport_close_before_terminal_does_not_cancel_game(self) -> None:
        await self.controller.initialize()
        self.pump()
        await self.controller.message("开始")
        self.server.complete_on_interrupt = False
        pause = asyncio.create_task(self.controller.control("pause"))
        await self.wait_until(lambda: any(method == "turn/interrupt" for method, _ in self.server.calls))
        await self.server.events.put({"method": "transport/closed", "params": {}})
        with self.assertRaises(AppServerError) as failure:
            await asyncio.wait_for(pause, 2)
        self.assertEqual("model_turn_unconfirmed", failure.exception.code)
        self.assertEqual("error", self.controller.mode)
        self.assertEqual([], self.game.calls)

    async def test_tool_response_disconnect_propagates_to_owner(self) -> None:
        self.server.read_only = True
        observer = Controller(
            self.server,
            self.game,
            self.state,
            "gpt-6-luna",
            "只观察",
            "观察",
            {**self.binding, "read_only": True},
            read_only=True,
        )
        await observer.initialize()
        self.server.fail_response = True
        pump = asyncio.create_task(observer.events())
        await self.server.events.put(
            {"id": 9, "method": "item/tool/call", "params": {"tool": "game_observe", "arguments": {}}}
        )
        with self.assertRaises(ExceptionGroup) as failure:
            await asyncio.wait_for(pump, 2)
        self.assertTrue(
            any(
                isinstance(error, AppServerError) and error.code == "transport_closed"
                for error in failure.exception.exceptions
            )
        )


if __name__ == "__main__":
    unittest.main()
