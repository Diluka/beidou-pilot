"""通过固定实例的现有 CLI 观察、执行和取消，不拥有客户端生命周期。"""

import asyncio
import json
from pathlib import Path
import signal
from typing import Literal, TypeAlias, cast


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class GameClientError(Exception):
    def __init__(self, code: str, message: str, details: JsonObject | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details if details is not None else {}


class GameClient:
    def __init__(self, cli: Path, root: Path, backend: Literal["beidou", "headless"], instance: str) -> None:
        self._arguments = [str(cli.resolve()), "--root", str(root.resolve()), "--backend", backend,
                           "--instance", instance, "--json"]
        self._identity: tuple[str, str] | None = None
        self._script_process: asyncio.subprocess.Process | None = None
        self._running = False
        self._cancel_requested = False
        self._script_error: GameClientError | None = None
        self._finished = asyncio.Event()
        self._finished.set()

    @property
    def running(self) -> bool:
        return self._running

    async def _interrupt(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is None:
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                # 自然完成可与取消相遇；等待已退出的所属进程，仍由桥核对释放。
                await process.wait()

    async def _call(self, *arguments: str, controlled: bool = False) -> JsonObject:
        try:
            process = await asyncio.create_subprocess_exec(
                *self._arguments, *arguments, stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except OSError as error:
            raise GameClientError("cli_unavailable", "无法启动固定的客户端 CLI。",
                                  {"reason": str(error)}) from error
        if controlled:
            self._script_process = process
            if self._cancel_requested:
                await self._interrupt(process)
        output, errors = await process.communicate()
        if (controlled and self._cancel_requested and not output
                and process.returncode == -signal.SIGINT):
            return {"status": "cancelled", "cancelled": True, "reason": "cancel_requested"}
        try:
            raw = json.loads(output)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise GameClientError("invalid_cli_response", "客户端 CLI 未返回有效 JSON。",
                                  {"exit_code": process.returncode,
                                   "stderr": errors.decode("utf-8", errors="replace")}) from error
        if not isinstance(raw, dict) or type(raw.get("ok")) is not bool:
            raise GameClientError("invalid_cli_response", "客户端 CLI 缺少有效结果信封。")
        report = cast(JsonObject, raw)
        if report["ok"] is True and process.returncode == 0:
            if not isinstance(report.get("data"), dict):
                raise GameClientError("invalid_cli_response", "客户端 CLI 缺少结果对象。")
            return cast(JsonObject, report["data"])
        failure = cast(JsonObject, report["error"])
        if controlled and self._cancel_requested and failure["code"] == "interrupted" and process.returncode == 130:
            return {"status": "cancelled", "cancelled": True, "reason": "cancel_requested"}
        raise GameClientError(cast(str, failure["code"]), cast(str, failure["message"]),
                              cast(JsonObject, failure.get("details", {})))

    async def _bridge(self) -> JsonObject:
        state = await self._call("bridge", "status")
        identity = cast(str, state["instance_id"]), cast(str, state["run_id"])
        if self._identity is None:
            self._identity = identity
        elif identity != self._identity:
            raise GameClientError("client_identity_changed", "客户端身份已变化，未向后继实例派发控制。",
                                  {"instance_id": identity[0], "run_id": identity[1]})
        return state

    async def observe(self) -> JsonObject:
        status = await self._call("status")
        if status.get("running") is False:
            return {"running": False, "status": status}
        state = await self._bridge()
        snapshot = await self._call("snapshot")
        return {"running": True, "instance_id": state["instance_id"], "run_id": state["run_id"],
                "seq": state["seq"], "observed_at_ms": state["observed_at_ms"], "snapshot": snapshot}

    async def script_status(self) -> JsonObject:
        state = await self._bridge()
        return {key: state.get(key) for key in
                ("instance_id", "run_id", "seq", "observed_at_ms", "script", "command", "held_keys")}

    async def run_lua(self, code: str, seconds: float) -> JsonObject:
        if self._running:
            raise GameClientError("input_busy", "本 harness 已有活动 Lua 执行。")
        self._running = True
        self._cancel_requested = False
        self._script_error = None
        self._finished.clear()
        try:
            await self._bridge()
            if self._cancel_requested:
                return {"status": "cancelled", "cancelled": True, "reason": "cancel_requested"}
            return await self._call("script", "run", "--code=" + code, "--seconds", str(seconds), controlled=True)
        except GameClientError as error:
            self._script_error = error
            raise
        finally:
            self._script_process = None
            self._running = False
            self._finished.set()

    async def cancel(self) -> JsonObject:
        if self._running:
            requested = self._cancel_requested
            self._cancel_requested = True
            if not requested and self._script_process is not None:
                await self._interrupt(self._script_process)
            await self._finished.wait()
            if self._script_error is not None:
                raise self._script_error
        state = await self._bridge()
        script = cast(JsonObject | None, state.get("script"))
        command = cast(JsonObject, state["command"])
        if state["held_keys"] or command["status"] == "running" or (script is not None and script["status"] == "running"):
            raise GameClientError("bridge_release_unconfirmed", "所属实例尚未确认停止 Lua 并释放输入。", state)
        return state
