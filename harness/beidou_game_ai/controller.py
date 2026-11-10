"""一个游戏会话的 Codex 消费者；动作与释放仍由现有客户端 CLI 拥有。"""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import cast

from .client import GameClient, GameClientError
from .protocol import AppServer, AppServerError, JsonObject, JsonValue


BASE_INSTRUCTIONS = "你是专用游戏角色的决策 AI。只使用本次游戏事实、游戏工具和向开发 AI 询问的协作入口。"
GAME_INSTRUCTIONS = """持续动作、战斗和等待交给 Lua，不做逐帧模型控制。先观察；动作后核对实际结果，接受请求不等于游戏效果。
最小 Lua 积木：game.state() 读取新状态；game.move("left"/"right"/"up"/"down", 秒) 有界移动并等待释放；game.sleep(秒) 等待；game.log(字符串) 记录；game.stop() 释放控制。
源码示例 game.move("right", 0.15) 只表示尝试移动；位置与停止效果通过后续观察确认。按实际能力使用接口，缺失能力明确报告，不猜快捷键或调用未说明的接口。
未知事实保留未知。普通游戏决策自主完成，需越界或协助才用 request_user_input 向开发 AI 询问。
game_run_lua 只提交有界执行，返回 starting 不证明原生受理。执行结束会自动收到结果；需要等待时结束本轮回复即可。
暂停后不再提交动作；恢复时根据最新观察重规划，不重放旧动作。遵守既有养成方案，不试验性分配永久点数或消耗稀缺资源。
"""
GAME_TOOLS: list[JsonObject] = [
    {"type": "function", "name": "game_observe", "description": "读取所属实例的新鲜身份与实际游戏快照。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"type": "function", "name": "game_script_status", "description": "读取所属实例的 Lua、任务、控制权、持键及最近执行结果。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"type": "function", "name": "game_run_lua", "description": "提交一段有界 Lua；结束后自动收到结果。源码使用现有 game API，不能更改所控实例。",
     "inputSchema": {"type": "object", "properties": {"code": {"type": "string"},
                     "seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 30}},
                     "required": ["code", "seconds"], "additionalProperties": False}},
]
TOOLS: list[JsonObject] = [{"type": "namespace", "name": "game", "description": "所属实例的游戏观察与有界Lua操作。", "tools": GAME_TOOLS}]


class Controller:
    def __init__(self, server: AppServer, game: GameClient, state: Path, model: str,
                 role: str, task: str, binding: JsonObject, *, read_only: bool = False) -> None:
        self.server = server
        self.game = game
        self.state = state
        self.model = model
        self.role = role
        self.task = task
        self.binding = binding
        self.read_only = read_only
        self.mode = "starting"
        self.thread_id = ""
        self.turn_id: str | None = None
        self.effort = ""
        self.execution: asyncio.Task[None] | None = None
        self.last_script: JsonObject | None = None
        self.questions: dict[int | str, JsonObject] = {}
        self.queued_messages: list[str] = []
        self.done = asyncio.Event()
        self._control = asyncio.Lock()
        self._messages = asyncio.Lock()
        self._turn_started = 0.0
        self._turns = 0
        self._tools = 0
        self._usage_updates = 0
        self._decision_reported = False

    def emit(self, event: str, data: JsonObject) -> None:
        record = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **data}
        with (self.state / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False), flush=True)

    def status(self) -> JsonObject:
        return {"mode": self.mode, "thread_id": self.thread_id, "turn_id": self.turn_id,
                "model": self.model, "effort": self.effort, "task": self.task,
                "read_only": self.read_only, "lua_running": self.game.running, "pending_questions": list(self.questions),
                "turn_requests": self._turns, "dynamic_tool_calls": self._tools,
                "token_usage_updates": self._usage_updates, "backend_api_requests": None, "cost": None}

    async def initialize(self) -> None:
        initialized = cast(JsonObject, await self.server.call("initialize", {
            "clientInfo": {"name": "beidou_game_ai", "version": "0.1.0"},
            "capabilities": {"experimentalApi": True}}))
        await self.server.notify("initialized", {})
        configuration = cast(JsonObject, await self.server.call("config/read", {"cwd": "/game", "includeLayers": True}))
        config = cast(JsonObject, configuration["config"])
        skills = cast(JsonObject, await self.server.call("skills/list", {"cwds": ["/game"], "forceReload": True}))
        mcps = cast(JsonObject, await self.server.call("mcpServerStatus/list", {"limit": 100}))
        if any(cast(JsonObject, item)["skills"] for item in cast(list[JsonValue], skills["data"])) or mcps["data"]:
            raise AppServerError("context_not_isolated", "游戏 AI 启动时发现额外技能或 MCP。")
        features = cast(JsonObject, config.get("features", {}))
        unwanted = ("shell_tool", "apps", "multi_agent", "memories", "goals", "hooks", "plugins", "image_generation", "view_image")
        code_mode = cast(JsonObject, features.get("code_mode", {}))
        if (any(features.get(name) is not False for name in unwanted) or config.get("project_doc_max_bytes") != 0
                or features.get("sleep_tool") is not False
                or not {"functions", "clock"}.issubset(cast(list[str], code_mode.get("excluded_tool_namespaces", [])))):
            raise AppServerError("context_not_isolated", "游戏 AI 的工具或项目指令裁剪配置不符合启动合同。")
        cursor: JsonValue = None
        selected: JsonObject | None = None
        while True:
            catalog = cast(JsonObject, await self.server.call("model/list", {"limit": 100, "includeHidden": False, "cursor": cursor}))
            selected = next((cast(JsonObject, item) for item in cast(list[JsonValue], catalog["data"])
                             if cast(JsonObject, item)["model"] == self.model), None)
            if selected is not None or catalog.get("nextCursor") is None:
                break
            cursor = catalog["nextCursor"]
        if selected is None:
            raise AppServerError("model_unavailable", "所选模型没有出现在当前运行身份的 model/list 中。", {"model": self.model})
        efforts = [cast(str, cast(JsonObject, item)["reasoningEffort"])
                   for item in cast(list[JsonValue], selected["supportedReasoningEfforts"])]
        self.effort = next((value for value in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
                            if value in efforts), cast(str, selected["defaultReasoningEffort"]))
        developer_text = (GAME_INSTRUCTIONS + ("\n本会话只读观察和交流，不提交Lua或接管角色。" if self.read_only else "")
                          + "\n角色与养成约束：\n" + self.role)
        tool_specs: list[JsonObject] = [{"type": "namespace", "name": "game", "description": "所属实例的游戏能力。",
                                       "tools": [tool for tool in GAME_TOOLS if not self.read_only or tool["name"] != "game_run_lua"]}]
        params: JsonObject = {"model": self.model, "cwd": "/game", "approvalPolicy": "never", "sandbox": "read-only",
                              "baseInstructions": BASE_INSTRUCTIONS, "developerInstructions": developer_text}
        checkpoint = self.state / "checkpoint.json"
        if checkpoint.is_file():
            saved = cast(JsonObject, json.loads(checkpoint.read_text(encoding="utf-8")))
            if saved["binding"] != self.binding:
                raise AppServerError("binding_mismatch", "保存的游戏会话属于另一组客户端选择，未续接。")
            params["threadId"] = saved["thread_id"]
            params["excludeTurns"] = True
            thread = cast(JsonObject, await self.server.call("thread/resume", params))
        else:
            params["dynamicTools"] = tool_specs
            params["allowProviderModelFallback"] = False
            thread = cast(JsonObject, await self.server.call("thread/start", params))
        if thread.get("instructionSources"):
            raise AppServerError("context_not_isolated", "游戏会话加载了未授权的指令文件。", thread["instructionSources"])
        self.thread_id = cast(str, cast(JsonObject, thread["thread"])["id"])
        self._checkpoint()
        self.emit("startup", {"model": self.model, "effort": self.effort, "advertised_efforts": efforts,
                              "codex_user_agent": initialized.get("userAgent"),
                              "configured_context_window": config.get("model_context_window"),
                              "configured_compact_limit": config.get("model_auto_compact_token_limit"),
                              "skills": 0, "mcp_servers": 0, "instruction_sources": thread.get("instructionSources", []),
                              "excluded_tool_namespaces": code_mode["excluded_tool_namespaces"],
                              "role_sha256": hashlib.sha256(self.role.encode()).hexdigest(),
                              "controlled_base_instruction_bytes": len(BASE_INSTRUCTIONS.encode()),
                              "controlled_developer_instruction_bytes": len(developer_text.encode()),
                              "declared_dynamic_tool_schema_bytes": len(json.dumps(tool_specs, ensure_ascii=False).encode()),
                              "component_tokens": None,
                              "declared_game_capabilities": [tool["name"] for tool in GAME_TOOLS
                                                             if not self.read_only or tool["name"] != "game_run_lua"],
                              "collaboration": "Codex同步/异步询问，经专用开发AI通道回答",
                              "cost": None})
        self.mode = "ready"

    def _checkpoint(self) -> None:
        (self.state / "checkpoint.json").write_text(json.dumps({"thread_id": self.thread_id, "binding": self.binding,
            "model": self.model, "task": self.task}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    async def update_task(self, text: str) -> None:
        self.task = text
        self._checkpoint()
        self.emit("task_updated", {"task": text})
        await self.message("当前任务已调整为：" + text + "。在已确认的动作边界按新目标重新规划。")

    async def message(self, text: str) -> None:
        async with self._messages:
            if self.mode in {"paused", "pausing", "stopping", "stopped", "error"}:
                self.queued_messages.append(text)
                self.emit("message_queued", {"mode": self.mode})
                return
            if self.turn_id is not None:
                await self.server.call("turn/steer", {"threadId": self.thread_id, "expectedTurnId": self.turn_id,
                                                     "input": [{"type": "text", "text": text}]})
                self.emit("message_delivered", {"turn_id": self.turn_id})
            else:
                self._turn_started = time.monotonic()
                self._decision_reported = False
                result = cast(JsonObject, await self.server.call("turn/start", {"threadId": self.thread_id, "effort": self.effort,
                    "input": [{"type": "text", "text": text}]}))
                self.turn_id = cast(str, cast(JsonObject, result["turn"])["id"])
                self._turns += 1
                if self.mode in {"ready", "running"}:
                    self.mode = "running"
                self.emit("turn_requested", {"turn_id": self.turn_id})

    async def _lua(self, code: str, seconds: float) -> None:
        started = time.monotonic()
        if self.mode not in {"ready", "running"}:
            self.last_script = {"ok": True, "data": {"status": "cancelled", "reason": "cancel_requested"}}
            self.emit("lua_finished", {"elapsed_seconds": 0, "result": self.last_script})
            return
        try:
            result = await self.game.run_lua(code, seconds)
            self.last_script = {"ok": True, "data": result}
        except GameClientError as error:
            self.last_script = {"ok": False, "error": {"code": error.code, "message": error.message, "details": error.details}}
            if error.code in {"bridge_release_unconfirmed", "client_identity_changed"}:
                self.mode = "error"
        self.emit("lua_finished", {"elapsed_seconds": round(time.monotonic() - started, 4), "result": self.last_script})
        if self.mode in {"ready", "running"}:
            try:
                await self.message("本次 Lua 已结束。请重新观察并核对实际效果，再按当前任务决定下一步。执行结果：" + json.dumps(self.last_script, ensure_ascii=False))
            except AppServerError as error:
                self.mode = "error"
                self.emit("continuation_failed", {"code": error.code, "message": error.message})
                self.done.set()
                raise

    async def _tool(self, request: JsonObject) -> None:
        identifier = cast(int | str, request["id"])
        params = cast(JsonObject, request["params"])
        tool = cast(str, params["tool"])
        started = time.monotonic()
        try:
            if not isinstance(params["arguments"], dict):
                raise GameClientError("invalid_tool_arguments", "游戏工具参数必须是 JSON 对象。")
            args = cast(JsonObject, params["arguments"])
            if tool != "game_run_lua" and args:
                raise GameClientError("invalid_tool_arguments", "观察工具不接收参数或实例选择。")
            if self.mode not in {"ready", "running"}:
                raise GameClientError("game_paused", "当前执行已暂停或停止，未派发游戏工具。")
            if tool == "game_observe":
                result = await self.game.observe()
            elif tool == "game_script_status":
                result = {**await self.game.script_status(), "last_execution": self.last_script}
            elif tool == "game_run_lua":
                if self.read_only:
                    raise GameClientError("read_only", "本游戏 AI 会话仅观察，未提交 Lua。")
                if (set(args) != {"code", "seconds"} or not isinstance(args["code"], str)
                        or type(args["seconds"]) not in (float, int) or not math.isfinite(args["seconds"])
                        or not 0 < args["seconds"] <= 30):
                    raise GameClientError("invalid_tool_arguments", "Lua 工具需要源码与0至30秒的有界时间。")
                if self.execution is not None and not self.execution.done():
                    raise GameClientError("input_busy", "本 harness 已有活动 Lua，先观察或等待结束。")
                self.execution = asyncio.create_task(self._lua(cast(str, args["code"]), cast(float, args["seconds"])))
                result = {"status": "starting", "seconds": args["seconds"], "effect": "unknown"}
            else:
                raise GameClientError("unknown_game_tool", "未注册这个游戏工具。")
            output: JsonObject = {"ok": True, "data": result}
        except GameClientError as error:
            output = {"ok": False, "error": {"code": error.code, "message": error.message, "details": error.details}}
        self._tools += 1
        self.emit("tool_finished", {"tool": tool, "elapsed_seconds": round(time.monotonic() - started, 4), "result": output})
        await self.server.respond(identifier, {"success": output["ok"],
            "contentItems": [{"type": "inputText", "text": json.dumps(output, ensure_ascii=False)}]})

    async def control(self, command: str) -> None:
        async with self._control:
            if command == "resume":
                if self.mode != "paused":
                    raise GameClientError("not_paused", "仅已确认暂停的游戏会话可以恢复。")
                observed = await self.game.observe()
                self.mode = "ready"
                messages = self.queued_messages
                self.queued_messages = []
                await self.message("恢复后重新规划，不重放旧动作。当前任务：" + self.task + "\n" + "\n".join(messages)
                                   + "\n新鲜观察：" + json.dumps(observed, ensure_ascii=False))
                return
            self.mode = "pausing" if command == "pause" else "stopping"
            cancellation = None if self.read_only else asyncio.create_task(self.game.cancel())
            try:
                async with self._messages:
                    if self.turn_id is not None:
                        await self.server.call("turn/interrupt", {"threadId": self.thread_id, "turnId": self.turn_id})
            finally:
                try:
                    released = await cancellation if cancellation is not None else None
                except GameClientError:
                    self.mode = "error"
                    raise
            self.turn_id = None
            self.mode = "paused" if command == "pause" else "stopped"
            self.emit("control_completed", {"command": command, "mode": self.mode, "read_only": self.read_only,
                                            "released_state": released, "game_input_cancelled": not self.read_only})
            if command == "stop":
                self.done.set()

    async def events(self) -> None:
        async with asyncio.TaskGroup() as pending:
            while True:
                event = await self.server.events.get()
                method = cast(str, event["method"])
                params = cast(JsonObject, event.get("params", {}))
                if (method in {"item/tool/call", "item/tool/requestUserInput", "item/agentMessage/delta"}
                        and not self._decision_reported):
                    self._decision_reported = True
                    self.emit("first_decision", {"elapsed_seconds": round(time.monotonic() - self._turn_started, 4),
                                                 "includes_transport": True})
                if method == "item/tool/call":
                    pending.create_task(self._tool(event))
                elif method == "item/tool/requestUserInput":
                    identifier = cast(int | str, event["id"])
                    self.questions[identifier] = params
                    self.emit("question", {"request_id": identifier, "questions": params["questions"]})
                elif method == "item/agentMessage/delta":
                    self.emit("reply_delta", {"text": params["delta"]})
                elif method == "thread/tokenUsage/updated":
                    self._usage_updates += 1
                    self.emit("usage", {"token_usage": params["tokenUsage"], "cost": None})
                elif method == "turn/completed":
                    completed = cast(JsonObject, params["turn"])
                    self.turn_id = None
                    if self.mode == "running":
                        self.mode = "ready"
                    self.emit("turn_completed", {"turn_id": completed["id"], "status": completed["status"],
                        "elapsed_seconds": round(time.monotonic() - self._turn_started, 4), "error": completed.get("error")})
                elif method == "serverRequest/resolved":
                    self.questions.pop(cast(int | str, params["requestId"]), None)
                elif method == "transport/closed":
                    self.mode = "error" if self.mode != "stopped" else self.mode
                    self.emit("transport_closed", params)
                    self.done.set()
                    break
