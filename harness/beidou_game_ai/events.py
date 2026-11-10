"""将客户端原生事件送入已有 Codex 会话；不拥有游戏动作或模型服务。"""

import argparse
import asyncio
from contextlib import suppress
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Literal, cast

from websockets.exceptions import WebSocketException

from .daemon import DaemonConnection
from .protocol import AppServerError, JsonObject, JsonValue


@dataclass(frozen=True)
class EventCursor:
    instance_id: str
    run_id: str
    seq: int

    @classmethod
    def parse(cls, value: JsonValue) -> "EventCursor":
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("instance_id"), str)
            or not isinstance(value.get("run_id"), str)
            or type(value.get("seq")) is not int
            or cast(int, value["seq"]) < 0
        ):
            raise ValueError("客户端事件游标需要 instance_id、run_id 和非负 seq。")
        return cls(cast(str, value["instance_id"]), cast(str, value["run_id"]), cast(int, value["seq"]))

    def json(self) -> JsonObject:
        return {"instance_id": self.instance_id, "run_id": self.run_id, "seq": self.seq}


@dataclass(frozen=True)
class ClientEvent:
    cursor: EventCursor
    observed_at_ms: int
    type: str
    expires_at_ms: int | None
    report: JsonObject

    @classmethod
    def parse(cls, report: JsonObject) -> "ClientEvent":
        cursor = EventCursor.parse(report.get("cursor"))
        data = report.get("data")
        if (
            not isinstance(data, dict)
            or data.get("seq") != cursor.seq
            or type(data.get("observed_at_ms")) is not int
            or type(data.get("scene_generation")) is not int
            or "character_id" not in data
            or (data["character_id"] is not None and type(data["character_id"]) is not int)
            or not isinstance(data.get("type"), str)
            or not isinstance(data.get("source"), str)
            or "expires_at_ms" not in data
            or (data["expires_at_ms"] is not None and type(data["expires_at_ms"]) is not int)
            or not isinstance(data.get("data"), dict)
        ):
            raise ValueError("客户端事件缺少有效的原生序号、来源、时效或详情。")
        return cls(
            cursor,
            cast(int, data["observed_at_ms"]),
            cast(str, data["type"]),
            cast(int | None, data["expires_at_ms"]),
            report,
        )


def emit(event: str, data: JsonObject) -> None:
    print(json.dumps({"event": event, "at_ms": round(time.time() * 1000), **data}, ensure_ascii=False), flush=True)


class EventDispatcher:
    def __init__(
        self,
        server: DaemonConnection,
        thread_id: str,
        delivery: Literal["steer", "interrupt"],
        timeout: float,
    ) -> None:
        self.server = server
        self.thread_id = thread_id
        self.delivery = delivery
        self.timeout = timeout
        self._interruptions: dict[str, asyncio.Future[None]] = {}

    async def call(self, method: str, params: JsonObject) -> JsonValue:
        return await asyncio.wait_for(self.server.call(method, params), self.timeout)

    async def initialize(self, *, check_only: bool = False) -> JsonObject:
        await self.call("initialize", {"clientInfo": {"name": "beidou_game_events", "version": "1"}})
        await self.server.notify("initialized", {})
        result = cast(JsonObject, await self.call("thread/read", {"threadId": self.thread_id, "includeTurns": False}))
        thread = cast(JsonObject, result["thread"])
        if thread["id"] != self.thread_id:
            raise AppServerError("thread_identity_mismatch", "Codex 返回了其他会话，未装载事件监听。")
        if not check_only:
            await self.call("thread/resume", {"threadId": self.thread_id, "excludeTurns": True})
        return cast(JsonObject, thread["status"])

    async def notifications(self) -> None:
        while True:
            event = await self.server.events.get()
            params = cast(JsonObject, event.get("params", {}))
            if event["method"] == "transport/closed":
                raise AppServerError(cast(str, params["code"]), cast(str, params["message"]))
            if event["method"] != "turn/completed" or params.get("threadId", self.thread_id) != self.thread_id:
                continue
            turn = cast(JsonObject, params["turn"])
            completed = self._interruptions.get(cast(str, turn["id"]))
            if completed is not None and not completed.done():
                completed.set_result(None)

    async def active_turn(self) -> str | None:
        result = cast(
            JsonObject,
            await self.call("thread/turns/list", {"threadId": self.thread_id, "limit": 1, "sortDirection": "desc"}),
        )
        turns = cast(list[JsonObject], result["data"])
        return cast(str, turns[0]["id"]) if turns and turns[0]["status"] == "inProgress" else None

    async def deliver(self, event: ClientEvent) -> None:
        message = (
            "客户端事件通知，不增加游戏操作授权。请及时查看当前实例的新鲜状态，按已有明确决策处理仍有效的邀请；"
            "不使用旧引用，不因事件到达自动接受或拒绝。此通知器没有取消游戏任务。\n"
            + json.dumps(event.report, ensure_ascii=False)
        )
        started = time.monotonic()
        turn_id = await self.active_turn()
        if turn_id is not None and self.delivery == "interrupt":
            completed: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._interruptions[turn_id] = completed
            try:
                try:
                    await self.call("turn/interrupt", {"threadId": self.thread_id, "turnId": turn_id})
                except AppServerError as error:
                    # 旧回合已自然结束时可直接处理事件，不把中断请求转移给后继回合。
                    if error.code != -32600 or await self.active_turn() is not None:
                        raise
                else:
                    await asyncio.wait_for(completed, self.timeout)
            finally:
                self._interruptions.pop(turn_id, None)
            turn_id = None
        for attempt in range(2):
            method = "turn/steer" if turn_id is not None else "turn/start"
            params: JsonObject = {"threadId": self.thread_id, "input": [{"type": "text", "text": message}]}
            if turn_id is not None:
                params["expectedTurnId"] = turn_id
            try:
                result = cast(JsonObject, await self.call(method, params))
                break
            except AppServerError as error:
                # 自然完成可能发生在读 turn 和派发之间；仅在明确拒绝且状态已变化时重试一次。
                if attempt != 0 or error.code != -32600 or self.delivery == "interrupt":
                    raise
                current = await self.active_turn()
                if current == turn_id:
                    raise
                turn_id = current
        accepted_turn = result["turnId"] if method == "turn/steer" else cast(JsonObject, result["turn"])["id"]
        emit(
            "event_delivered",
            {
                "thread_id": self.thread_id,
                "turn_id": accepted_turn,
                "event_type": event.type,
                "cursor": event.cursor.json(),
                "method": method,
                "delivery": self.delivery,
                "delivery_elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                "observed_to_delivery_ms": round(time.time() * 1000 - event.observed_at_ms, 2),
                "effect": "unknown",
            },
        )


async def run(args: argparse.Namespace) -> None:
    state: Path = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    checkpoint = state / "cursor.json"
    binding: JsonObject = {
        "root": str(args.root.resolve()),
        "backend": args.backend,
        "instance": args.instance,
        "thread_id": args.thread,
        "socket": str(args.socket.absolute()),
    }
    cursor = None
    if checkpoint.exists():
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or saved.get("binding") != binding:
            raise ValueError("事件状态目录已绑定其他客户端或 Codex 会话。")
        cursor = EventCursor.parse(saved.get("cursor"))
    server = await DaemonConnection.connect(args.socket)
    dispatcher = EventDispatcher(server, args.thread, args.delivery, args.rpc_timeout)
    notifications = None
    process = None
    incoming = None
    try:
        status = await dispatcher.initialize(check_only=args.check)
        emit("codex_connected", {"thread_id": args.thread, "status": status, "check_only": args.check})
        if args.check:
            return
        notifications = asyncio.create_task(dispatcher.notifications())
        command = [
            str(args.cli.resolve()),
            "--root",
            str(args.root.resolve()),
            "--backend",
            args.backend,
            "--instance",
            args.instance,
            "--json",
            "events",
            "watch",
            "--interval",
            str(args.interval),
        ]
        if cursor is not None:
            command += ["--cursor", json.dumps(cursor.json())]
        if args.seconds is not None:
            command += ["--seconds", str(args.seconds)]
        with (state / "watch.stderr.log").open("ab") as stderr:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=stderr,
            )
        stdout = cast(asyncio.StreamReader, process.stdout)
        while True:
            incoming = asyncio.create_task(stdout.readline())
            done, _ = await asyncio.wait({incoming, notifications}, return_when=asyncio.FIRST_COMPLETED)
            if notifications in done:
                incoming.cancel()
                await notifications
            line = await incoming
            if not line:
                break
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("客户端事件监听没有返回 JSON 对象。")
            report = cast(JsonObject, value)
            if report.get("ok") is False:
                error = cast(JsonObject, report["error"])
                raise AppServerError(cast(str, error["code"]), cast(str, error["message"]))
            if report.get("event") not in {"events_ready", "client_event"}:
                raise ValueError("客户端事件监听返回未知消息。")
            next_cursor = EventCursor.parse(report.get("cursor"))
            if (
                report.get("backend") != args.backend
                or report.get("instance") != args.instance
                or report.get("instance_id") != next_cursor.instance_id
                or report.get("run_id") != next_cursor.run_id
                or (
                    cursor is not None
                    and (cursor.instance_id, cursor.run_id) != (next_cursor.instance_id, next_cursor.run_id)
                )
            ):
                raise ValueError("客户端事件身份已变化，未投递到 Codex。")
            if report["event"] == "client_event":
                event = ClientEvent.parse(report)
                if cursor is not None and next_cursor.seq <= cursor.seq:
                    continue
                if event.type not in args.event_type:
                    emit("event_skipped", {"cursor": next_cursor.json(), "reason": "type_not_selected"})
                elif event.expires_at_ms is not None and event.expires_at_ms <= round(time.time() * 1000):
                    emit("event_skipped", {"cursor": next_cursor.json(), "reason": "expired"})
                else:
                    await dispatcher.deliver(event)
            else:
                emit("events_ready", {"thread_id": args.thread, "cursor": next_cursor.json()})
            temporary = checkpoint.with_suffix(".tmp")
            temporary.write_text(
                json.dumps({"binding": binding, "cursor": next_cursor.json()}) + "\n", encoding="utf-8"
            )
            temporary.replace(checkpoint)
            cursor = next_cursor
        exit_code = await process.wait()
        if exit_code != 0:
            raise AppServerError("events_watch_failed", "客户端事件监听已退出。", {"exit_code": exit_code})
    finally:
        if incoming is not None and not incoming.done():
            incoming.cancel()
            with suppress(asyncio.CancelledError):
                await incoming
        if process is not None and process.returncode is None:
            process.terminate()
            await process.wait()
        if notifications is not None:
            notifications.cancel()
            with suppress(asyncio.CancelledError):
                await notifications
        await server.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="把客户端事件送入已有 SSH Codex 会话，不启动新模型或游戏客户端。")
    parser.add_argument("--cli", type=Path, default=Path(__file__).resolve().parents[2] / "cli/beidou-pilot")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--backend", choices=("beidou", "headless"), default="beidou")
    parser.add_argument("--instance", default="default")
    parser.add_argument("--thread", required=True)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--delivery", choices=("steer", "interrupt"), default="steer")
    parser.add_argument("--event-type", action="append", help="需处理的事件类型；默认仅 invitation.opened。")
    parser.add_argument("--interval", type=float, default=0.025)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("--rpc-timeout", type=float, default=15)
    parser.add_argument("--check", action="store_true", help="只验证既有 daemon 与会话可读，不监听或发送事件。")
    args = parser.parse_args()
    if (
        not math.isfinite(args.interval)
        or args.interval <= 0
        or not math.isfinite(args.rpc_timeout)
        or args.rpc_timeout <= 0
        or (args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0))
    ):
        parser.error("监听间隔、RPC 等待和有界时长必须大于零。")
    args.event_type = args.event_type or ["invitation.opened"]
    os.umask(0o077)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, TimeoutError, AppServerError, WebSocketException) as error:
        emit(
            "error",
            {
                "code": error.code if isinstance(error, AppServerError) else "events_consumer_failed",
                "message": str(error),
            },
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
