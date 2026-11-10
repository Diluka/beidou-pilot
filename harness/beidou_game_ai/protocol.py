"""Codex app-server 的异步 JSONL 传输；模型与游戏决策由调用者处理。"""

import asyncio
import json
from pathlib import Path
from typing import TypeAlias, cast


JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class AppServerError(RuntimeError):
    def __init__(self, code: int | str, message: str, details: JsonValue = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class AppServer:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self._stdin = cast(asyncio.StreamWriter, process.stdin)
        self._stdout = cast(asyncio.StreamReader, process.stdout)
        self._pending: dict[int, asyncio.Future[JsonValue]] = {}
        self._next_id = 0
        self._closing = False
        self.events: asyncio.Queue[JsonObject] = asyncio.Queue()
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def start(cls, command: list[str], stderr: Path) -> "AppServer":
        with stderr.open("ab") as stream:
            process = await asyncio.create_subprocess_exec(
                *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stream)
        return cls(process)

    async def _send(self, message: JsonObject) -> None:
        if self._closing or self._reader.done():
            raise AppServerError("transport_closed", "Codex app-server 连接已结束。")
        try:
            self._stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
            await self._stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise AppServerError("transport_closed", "Codex app-server 输入已关闭。") from error

    async def call(self, method: str, params: JsonObject) -> JsonValue:
        self._next_id += 1
        identifier = self._next_id
        result: asyncio.Future[JsonValue] = asyncio.get_running_loop().create_future()
        self._pending[identifier] = result
        try:
            await self._send({"id": identifier, "method": method, "params": params})
            return await result
        finally:
            self._pending.pop(identifier, None)

    async def notify(self, method: str, params: JsonObject) -> None:
        await self._send({"method": method, "params": params})

    async def respond(self, request_id: int | str, result: JsonValue) -> None:
        await self._send({"id": request_id, "result": result})

    async def _read(self) -> None:
        failure = AppServerError("transport_closed", "Codex app-server 输出已结束。")
        try:
            while line := await self._stdout.readline():
                try:
                    payload = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    failure = AppServerError("invalid_json_rpc", "Codex app-server 输出不是有效 JSON。")
                    break
                if not isinstance(payload, dict):
                    failure = AppServerError("invalid_json_rpc", "Codex app-server 输出必须是 JSON 对象。")
                    break
                message = cast(JsonObject, payload)
                if "method" in message:
                    if not isinstance(message["method"], str):
                        failure = AppServerError("invalid_json_rpc", "Codex app-server 方法字段无效。")
                        break
                    await self.events.put(message)
                    continue
                identifier = message.get("id")
                if type(identifier) not in (int, str) or ("result" in message) == ("error" in message):
                    failure = AppServerError("invalid_json_rpc", "Codex app-server 响应缺少请求身份或结果。")
                    break
                remote_error = message.get("error")
                if "error" in message and (not isinstance(remote_error, dict)
                        or type(remote_error.get("code")) is not int
                        or not isinstance(remote_error.get("message"), str)):
                    failure = AppServerError("invalid_json_rpc", "Codex app-server 错误响应字段无效。")
                    break
                pending = self._pending.get(identifier) if type(identifier) is int else None
                if pending is None or pending.done():
                    continue
                if remote_error is not None:
                    error = cast(JsonObject, remote_error)
                    pending.set_exception(AppServerError(cast(int, error["code"]),
                                                        cast(str, error["message"]), error.get("data")))
                else:
                    pending.set_result(message["result"])
        except OSError as error:
            failure = AppServerError("transport_closed", "无法继续读取 Codex app-server 输出。", str(error))
        finally:
            for pending in self._pending.values():
                if not pending.done():
                    pending.set_exception(failure)
            await self.events.put({"method": "transport/closed", "params": {
                "code": failure.code, "message": failure.message, "returncode": self._process.returncode}})

    async def close(self) -> None:
        self._closing = True
        self._stdin.close()
        await self._process.wait()
        await self._reader
