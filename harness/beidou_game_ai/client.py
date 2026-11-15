"""通过同一容器内的 CLI 只读观察，游戏任务与客户端独立运行。"""

import asyncio
import json
from pathlib import Path
from typing import TypeAlias, cast


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class GameClientError(Exception):
    def __init__(self, code: str, message: str, details: JsonObject | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details if details is not None else {}


class GameClient:
    def __init__(self, cli: Path) -> None:
        self._arguments = [str(cli.resolve()), "--json"]
        self._identity: tuple[str, str] | None = None

    async def _call(self, *arguments: str) -> JsonObject:
        try:
            process = await asyncio.create_subprocess_exec(
                *self._arguments,
                *arguments,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise GameClientError("cli_unavailable", "无法启动容器内的客户端 CLI。", {"reason": str(error)}) from error
        output, errors = await process.communicate()
        try:
            raw = json.loads(output)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise GameClientError(
                "invalid_cli_response",
                "客户端 CLI 未返回有效 JSON。",
                {"exit_code": process.returncode, "stderr": errors.decode("utf-8", errors="replace")},
            ) from error
        if not isinstance(raw, dict) or type(raw.get("ok")) is not bool:
            raise GameClientError("invalid_cli_response", "客户端 CLI 缺少有效结果信封。")
        report = cast(JsonObject, raw)
        if report["ok"] is True and process.returncode == 0:
            if not isinstance(report.get("data"), dict):
                raise GameClientError("invalid_cli_response", "客户端 CLI 缺少结果对象。")
            return cast(JsonObject, report["data"])
        failure = report.get("error")
        if (
            not isinstance(failure, dict)
            or not isinstance(failure.get("code"), str)
            or not isinstance(failure.get("message"), str)
        ):
            raise GameClientError("invalid_cli_response", "客户端 CLI 缺少错误对象。")
        raise GameClientError(failure["code"], failure["message"], cast(JsonObject, failure.get("details", {})))

    async def _bridge(self) -> JsonObject:
        state = await self._call("bridge", "status")
        identity = cast(str, state["instance_id"]), cast(str, state["run_id"])
        if self._identity is None:
            self._identity = identity
        elif identity != self._identity:
            raise GameClientError(
                "client_identity_changed",
                "客户端身份已变化，不能延续原实例的观察。",
                {"instance_id": identity[0], "run_id": identity[1]},
            )
        return state

    async def observe(self) -> JsonObject:
        status = await self._call("status")
        if status.get("running") is False:
            return {"running": False, "status": status}
        state = await self._bridge()
        snapshot = await self._call("snapshot")
        return {
            "running": True,
            "instance_id": state["instance_id"],
            "run_id": state["run_id"],
            "seq": state["seq"],
            "observed_at_ms": state["observed_at_ms"],
            "snapshot": snapshot,
            "script": state.get("script"),
            "scripts": state.get("scripts"),
            "command": state["command"],
            "held_keys": state["held_keys"],
        }

    async def script_status(self) -> JsonObject:
        state = await self._bridge()
        return {
            key: state.get(key)
            for key in (
                "instance_id",
                "run_id",
                "seq",
                "observed_at_ms",
                "script",
                "scripts",
                "command",
                "held_keys",
            )
        }
