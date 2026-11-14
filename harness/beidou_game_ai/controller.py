"""游戏角色的可选 Codex 旁路；只管理 LLM 会话调度。"""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import cast

from .client import GameClient, GameClientError
from .protocol import AppServer, AppServerError, JsonObject, JsonValue


BASE_INSTRUCTIONS = "你是专用游戏角色的决策 AI。依据本实例的游戏事实和已授权能力行动，需要协助时向开发 AI 询问。"
GAME_INSTRUCTIONS = """使用 beidou-pilot-client 技能，通过 shell 调用本容器的 beidou-pilot CLI。
LLM 是可选旁路，客户端任务独立运行。持续任务通过原生 script start 启动，不靠常驻 shell 或模型回合维持。
每次接入和恢复先读取当前 script、command、held_keys 和游戏快照，再根据现有任务决定下一步。
已有脚本或命令 running 时只观察和汇报，不重复 start、cancel 或抢占；任务接管或取消必须由用户明确要求。
pause、stop、退出和重连只影响 LLM 调度，不取消脚本、关闭客户端或清理后台 shell。需要取消任务或关闭客户端时使用明确命令。
持续动作、战斗和等待交给现有 Lua，不做逐帧模型控制。动作后核对实际结果，接受请求不等于游戏效果。
未知事实保留未知。需越界或协助才用 request_user_input 向开发 AI 询问。遵守既有养成方案，不试验性分配永久点数或消耗稀缺资源。
"""
TOOL_SURFACE = "cli-v1"
SKILL_NAME = "beidou-pilot-client"
SKILL_PATH = "/game/.agents/skills/beidou-pilot-client/SKILL.md"
GUIDE_NAME = "beidou-game-guide"
GUIDE_PATH = "/game/.agents/skills/beidou-game-guide/SKILL.md"
OBSERVATION_TOOLS: list[JsonObject] = [
    {
        "type": "function",
        "name": "game_observe",
        "description": "读取所属实例的新鲜身份与实际游戏快照。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "type": "function",
        "name": "game_script_status",
        "description": "读取所属实例的 tick Lua 会话、持键及最近执行结果。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


class Controller:
    def __init__(
        self,
        server: AppServer,
        game: GameClient,
        state: Path,
        model: str,
        role: str,
        task: str,
        binding: JsonObject,
        *,
        read_only: bool = False,
    ) -> None:
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
        self.questions: dict[int | str, JsonObject] = {}
        self.queued_messages: list[str] = []
        self.done = asyncio.Event()
        self._control = asyncio.Lock()
        self._messages = asyncio.Lock()
        self._turn_finished = asyncio.Event()
        self._turn_finished.set()
        self._turn_failure: AppServerError | None = None
        self._turn_started = 0.0
        self._turns = 0
        self._tools = 0
        self._usage_updates = 0
        self._decision_reported = False
        self.tool_surface = TOOL_SURFACE

    def emit(self, event: str, data: JsonObject) -> None:
        record = {"at": datetime.now(timezone.utc).isoformat(), "event": event, **data}
        with (self.state / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False), flush=True)

    def status(self) -> JsonObject:
        return {
            "mode": self.mode,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "model": self.model,
            "effort": self.effort,
            "task": self.task,
            "read_only": self.read_only,
            "pending_questions": list(self.questions),
            "turn_requests": self._turns,
            "dynamic_tool_calls": self._tools,
            "token_usage_updates": self._usage_updates,
            "backend_api_requests": None,
            "cost": None,
            "tool_surface": self.tool_surface,
        }

    async def initialize(self) -> None:
        initialized = cast(
            JsonObject,
            await self.server.call(
                "initialize",
                {
                    "clientInfo": {"name": "beidou_game_ai", "version": "0.1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            ),
        )
        await self.server.notify("initialized", {})
        configuration = cast(JsonObject, await self.server.call("config/read", {"cwd": "/game", "includeLayers": True}))
        config = cast(JsonObject, configuration["config"])
        skills = cast(JsonObject, await self.server.call("skills/list", {"cwds": ["/game"], "forceReload": True}))
        mcps = cast(JsonObject, await self.server.call("mcpServerStatus/list", {"limit": 100}))
        loaded_skills = [
            cast(JsonObject, skill)
            for item in cast(list[JsonValue], skills["data"])
            for skill in cast(list[JsonValue], cast(JsonObject, item)["skills"])
        ]
        skill_errors = [
            error
            for item in cast(list[JsonValue], skills["data"])
            for error in cast(list[JsonValue], cast(JsonObject, item).get("errors", []))
        ]
        if (
            len(loaded_skills) != 2
            or {(skill["name"], skill["path"]) for skill in loaded_skills}
            != {(SKILL_NAME, SKILL_PATH), (GUIDE_NAME, GUIDE_PATH)}
            or any(skill.get("enabled", True) is not True for skill in loaded_skills)
            or skill_errors
            or mcps["data"]
        ):
            raise AppServerError("context_not_isolated", "游戏 AI 只允许装载本镜像的客户端和攻略技能。")
        features = cast(JsonObject, config.get("features", {}))
        unwanted = (
            "apps",
            "multi_agent",
            "memories",
            "goals",
            "hooks",
            "plugins",
            "image_generation",
            "view_image",
        )
        code_mode = cast(JsonObject, features.get("code_mode", {}))
        excluded = cast(list[str], code_mode.get("excluded_tool_namespaces", []))
        if (
            any(features.get(name) is not False for name in unwanted)
            or features.get("shell_tool") is not (not self.read_only)
            or config.get("project_doc_max_bytes") != 0
            or features.get("sleep_tool") is not False
            or "clock" not in excluded
            or ("functions" in excluded) != self.read_only
        ):
            raise AppServerError("context_not_isolated", "游戏 AI 的工具或项目指令裁剪配置不符合启动合同。")
        cursor: JsonValue = None
        selected: JsonObject | None = None
        while True:
            catalog = cast(
                JsonObject,
                await self.server.call("model/list", {"limit": 100, "includeHidden": False, "cursor": cursor}),
            )
            selected = next(
                (
                    cast(JsonObject, item)
                    for item in cast(list[JsonValue], catalog["data"])
                    if cast(JsonObject, item)["model"] == self.model
                ),
                None,
            )
            if selected is not None or catalog.get("nextCursor") is None:
                break
            cursor = catalog["nextCursor"]
        if selected is None:
            raise AppServerError(
                "model_unavailable", "所选模型没有出现在当前运行身份的 model/list 中。", {"model": self.model}
            )
        efforts = [
            cast(str, cast(JsonObject, item)["reasoningEffort"])
            for item in cast(list[JsonValue], selected["supportedReasoningEfforts"])
        ]
        self.effort = next(
            (
                value
                for value in ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
                if value in efforts
            ),
            cast(str, selected["defaultReasoningEffort"]),
        )
        checkpoint = self.state / "checkpoint.json"
        saved: JsonObject | None = None
        if checkpoint.is_file():
            saved = cast(JsonObject, json.loads(checkpoint.read_text(encoding="utf-8")))
            if saved["binding"] != self.binding:
                raise AppServerError("binding_mismatch", "保存的游戏会话属于另一组客户端选择，未续接。")
            if saved.get("tool_surface", "lua-v1") != TOOL_SURFACE:
                raise AppServerError(
                    "tool_surface_mismatch",
                    "旧 lua-v1/hunt-v1 会话使用已退役的动态工具；历史已保留，请另选状态目录启动 CLI 会话。",
                    {"saved_tool_surface": saved.get("tool_surface", "lua-v1"), "required_tool_surface": TOOL_SURFACE},
                )
        developer_text = (
            (
                "本会话只读观察和交流，只使用 game_observe、game_script_status，不接管或取消角色。"
                if self.read_only
                else GAME_INSTRUCTIONS
            )
            + "\n角色与养成约束：\n"
            + self.role
        )
        tool_specs: list[JsonObject] = (
            [{"type": "namespace", "name": "game", "description": "所属实例的只读观察。", "tools": OBSERVATION_TOOLS}]
            if self.read_only
            else []
        )
        params: JsonObject = {
            "model": self.model,
            "cwd": "/game",
            "approvalPolicy": "never",
            "sandbox": "read-only" if self.read_only else "danger-full-access",
            "baseInstructions": BASE_INSTRUCTIONS,
            "developerInstructions": developer_text,
        }
        if saved is not None:
            params["threadId"] = saved["thread_id"]
            params["excludeTurns"] = True
            thread = cast(JsonObject, await self.server.call("thread/resume", params))
        else:
            if self.read_only:
                params["dynamicTools"] = tool_specs
            params["allowProviderModelFallback"] = False
            thread = cast(JsonObject, await self.server.call("thread/start", params))
        if thread.get("instructionSources"):
            raise AppServerError(
                "context_not_isolated", "游戏会话加载了未授权的指令文件。", thread["instructionSources"]
            )
        self.thread_id = cast(str, cast(JsonObject, thread["thread"])["id"])
        self._checkpoint()
        self.emit(
            "startup",
            {
                "model": self.model,
                "effort": self.effort,
                "advertised_efforts": efforts,
                "codex_user_agent": initialized.get("userAgent"),
                "configured_context_window": config.get("model_context_window"),
                "configured_compact_limit": config.get("model_auto_compact_token_limit"),
                "skills": len(loaded_skills),
                "shell_tool": not self.read_only,
                "mcp_servers": 0,
                "instruction_sources": thread.get("instructionSources", []),
                "excluded_tool_namespaces": code_mode["excluded_tool_namespaces"],
                "role_sha256": hashlib.sha256(self.role.encode()).hexdigest(),
                "controlled_base_instruction_bytes": len(BASE_INSTRUCTIONS.encode()),
                "controlled_developer_instruction_bytes": len(developer_text.encode()),
                "declared_dynamic_tool_schema_bytes": len(json.dumps(tool_specs, ensure_ascii=False).encode()),
                "component_tokens": None,
                "declared_game_capabilities": (
                    [tool["name"] for tool in OBSERVATION_TOOLS] if self.read_only else ["beidou-pilot CLI"]
                ),
                "collaboration": "Codex同步/异步询问，经专用开发AI通道回答",
                "cost": None,
            },
        )
        self.mode = "ready"

    def _checkpoint(self) -> None:
        (self.state / "checkpoint.json").write_text(
            json.dumps(
                {
                    "thread_id": self.thread_id,
                    "binding": self.binding,
                    "model": self.model,
                    "task": self.task,
                    "tool_surface": self.tool_surface,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

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
                await self.server.call(
                    "turn/steer",
                    {
                        "threadId": self.thread_id,
                        "expectedTurnId": self.turn_id,
                        "input": [{"type": "text", "text": text}],
                    },
                )
                self.emit("message_delivered", {"turn_id": self.turn_id})
            else:
                self._turn_finished.clear()
                self._turn_failure = None
                self._turn_started = time.monotonic()
                self._decision_reported = False
                try:
                    result = cast(
                        JsonObject,
                        await self.server.call(
                            "turn/start",
                            {
                                "threadId": self.thread_id,
                                "effort": self.effort,
                                "input": (
                                    []
                                    if self.read_only
                                    else [
                                        {"type": "skill", "name": SKILL_NAME, "path": SKILL_PATH},
                                        {"type": "skill", "name": GUIDE_NAME, "path": GUIDE_PATH},
                                    ]
                                )
                                + [{"type": "text", "text": text}],
                            },
                        ),
                    )
                except AppServerError:
                    self.mode = "error"
                    self._turn_failure = AppServerError(
                        "model_turn_unconfirmed", "turn/start 未返回身份，无法确认模型回合已停止。"
                    )
                    raise
                self.turn_id = cast(str, cast(JsonObject, result["turn"])["id"])
                self._turns += 1
                if self.mode in {"ready", "running"}:
                    self.mode = "running"
                self.emit("turn_requested", {"turn_id": self.turn_id})

    async def _tool(self, request: JsonObject) -> None:
        identifier = cast(int | str, request["id"])
        params = cast(JsonObject, request["params"])
        tool = cast(str, params["tool"])
        started = time.monotonic()
        try:
            if not self.read_only or tool not in {"game_observe", "game_script_status"}:
                raise GameClientError("unknown_game_tool", "本会话未注册这个动态工具；普通模式通过 CLI 操作。")
            if params["arguments"] != {}:
                raise GameClientError("invalid_tool_arguments", "观察工具不接收参数或实例选择。")
            if self.mode not in {"ready", "running"}:
                raise GameClientError("game_paused", "当前执行已暂停或停止，未派发游戏工具。")
            result = await self.game.observe() if tool == "game_observe" else await self.game.script_status()
            output: JsonObject = {"ok": True, "data": result}
        except GameClientError as error:
            output = {"ok": False, "error": {"code": error.code, "message": error.message, "details": error.details}}
        self._tools += 1
        self.emit(
            "tool_finished", {"tool": tool, "elapsed_seconds": round(time.monotonic() - started, 4), "result": output}
        )
        await self.server.respond(
            identifier,
            {
                "success": output["ok"],
                "contentItems": [{"type": "inputText", "text": json.dumps(output, ensure_ascii=False)}],
            },
        )

    async def control(self, command: str) -> None:
        async with self._control:
            if command == "resume":
                if self.mode != "paused":
                    raise GameClientError("not_paused", "仅已确认暂停的 LLM 会话可以恢复。")
                observed = await self.game.observe()
                self.mode = "ready"
                messages = self.queued_messages
                self.queued_messages = []
                await self.message(
                    "恢复后先核对现有任务，不重复启动或抢占。当前任务："
                    + self.task
                    + "\n"
                    + "\n".join(messages)
                    + "\n新鲜观察："
                    + json.dumps(observed, ensure_ascii=False)
                )
                return
            self.mode = "pausing" if command == "pause" else "stopping"
            try:
                # message 持有此锁直到在途 turn/start 返回，先取得确切 turn ID。
                async with self._messages:
                    turn_id = self.turn_id
                    if self._turn_failure is not None:
                        raise self._turn_failure
                if turn_id is not None:
                    try:
                        await self.server.call("turn/interrupt", {"threadId": self.thread_id, "turnId": turn_id})
                    except AppServerError as error:
                        # 自然结束可能先于 interrupt；仍须由事件泵确认同一 turn 的终态。
                        if error.code != -32600 or "no active turn" not in error.message.lower():
                            raise
                    await self._turn_finished.wait()
                    if self._turn_failure is not None:
                        raise self._turn_failure
            except AppServerError:
                self.mode = "error"
                raise
            self.mode = "paused" if command == "pause" else "stopped"
            self.emit(
                "control_completed",
                {
                    "command": command,
                    "mode": self.mode,
                    "read_only": self.read_only,
                    "scope": "llm",
                },
            )
            if command == "stop":
                self.done.set()

    async def events(self) -> None:
        try:
            async with asyncio.TaskGroup() as pending:
                while True:
                    event = await self.server.events.get()
                    method = cast(str, event["method"])
                    params = cast(JsonObject, event.get("params", {}))
                    if (
                        method
                        in {"item/tool/call", "item/tool/requestUserInput", "item/agentMessage/delta", "item/started"}
                        and not self._decision_reported
                    ):
                        self._decision_reported = True
                        self.emit(
                            "first_decision",
                            {
                                "elapsed_seconds": round(time.monotonic() - self._turn_started, 4),
                                "includes_transport": True,
                            },
                        )
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
                        # 在途 start 的响应由独立传输读取器处理；等它登记 ID 再认领终态。
                        async with self._messages:
                            current = completed["id"] == self.turn_id
                            if current:
                                self.turn_id = None
                                self._turn_finished.set()
                                if self.mode == "running":
                                    self.mode = "ready"
                        self.emit(
                            "turn_completed",
                            {
                                "turn_id": completed["id"],
                                "status": completed["status"],
                                "elapsed_seconds": round(time.monotonic() - self._turn_started, 4) if current else None,
                                "error": completed.get("error"),
                            },
                        )
                    elif method == "serverRequest/resolved":
                        self.questions.pop(cast(int | str, params["requestId"]), None)
                    elif method == "transport/closed":
                        self.mode = "error" if self.mode != "stopped" else self.mode
                        self.emit("transport_closed", params)
                        self.done.set()
                        return
        finally:
            if not self._turn_finished.is_set():
                self._turn_failure = AppServerError("model_turn_unconfirmed", "模型连接已结束，未确认活动 turn 终止。")
                self._turn_finished.set()
