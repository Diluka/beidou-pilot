"""读取本实例原生事件序列；不取得输入控制权，也不决定游戏动作。"""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Iterator, cast

from .bridge import BridgeClient
from .errors import ClientError, JsonObject
from .validation import Integer, Object, String, validate


@dataclass(frozen=True)
class EventCursor:
    instance_id: str
    run_id: str
    seq: int

    def document(self) -> JsonObject:
        return {"instance_id": self.instance_id, "run_id": self.run_id, "seq": self.seq}


def parse_cursor(text: str | None) -> EventCursor | None:
    if text is None:
        return None
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise ClientError(
            "invalid_events_cursor", "事件游标须为包含 instance_id、run_id、seq 的 JSON 对象。"
        ) from error
    value = validate(raw, CURSOR_SCHEMA, code="invalid_events_cursor", label="事件游标")
    return EventCursor(value["instance_id"], value["run_id"], value["seq"])


CURSOR_SCHEMA = Object(
    {
        "instance_id": String(),
        "run_id": String(),
        "seq": Integer(minimum=0),
    },
    allow_extra=True,
)


class EventReader:
    def __init__(self, root: Path, backend: str, instance: str = "default") -> None:
        if backend != "beidou":
            raise ClientError("unsupported_capability", "当前无头客户端尚未提供原生通知事件。")
        self.backend = backend
        self.instance = instance
        self.bridge = BridgeClient(root, backend, instance)
        initial = self.bridge.snapshot()
        self.identity = initial["instance_id"], initial["run_id"]

    def read(self, cursor: EventCursor | None = None) -> JsonObject:
        try:
            state = self.bridge.snapshot()
        except ClientError as error:
            if error.code == "bridge_session_mismatch":
                raise ClientError("events_identity_changed", "事件所属原生客户端登记已变化。") from error
            raise
        if (state["instance_id"], state["run_id"]) != self.identity:
            raise ClientError("events_identity_changed", "事件所属原生客户端已变化，未跟随后继实例。")
        if cursor is not None and (cursor.instance_id, cursor.run_id) != self.identity:
            raise ClientError("events_identity_changed", "事件游标不属于当前原生客户端运行。")
        capabilities = state.get("capabilities")
        if not isinstance(capabilities, dict) or capabilities.get("events") is not True:
            raise ClientError("unsupported_capability", "当前 GUI 桥构建尚未提供原生事件序列。")
        if state.get("event_stream_status") != "ok":
            raise ClientError(
                "events_unavailable", "原生事件发布尚未成功。", {"status": state.get("event_stream_status")}
            )
        try:
            raw = json.loads((self.bridge.directory / "events.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ClientError("events_unavailable", "当前原生事件序列尚未有效发布。") from error
        events = raw["events"]
        after = cursor.seq if cursor is not None else raw["first_seq"] - 1
        if after < raw["first_seq"] - 1:
            raise ClientError(
                "events_gap",
                "游标之后的事件已超出原生保留区，须重新观察当前邀请。",
                {
                    "cursor": cursor.document() if cursor is not None else None,
                    "first_seq": raw["first_seq"],
                    "last_seq": raw["last_seq"],
                },
            )
        if after > raw["last_seq"]:
            raise ClientError("invalid_events_cursor", "事件游标超过当前原生事件序列。")
        return {
            "source": "client-native-events",
            "readonly": True,
            "backend": self.backend,
            "instance": self.instance,
            "instance_id": self.identity[0],
            "run_id": self.identity[1],
            "observed_at_ms": state["observed_at_ms"],
            "first_seq": raw["first_seq"],
            "last_seq": raw["last_seq"],
            "cursor": EventCursor(*self.identity, raw["last_seq"]).document(),
            "events": cast(list[JsonObject], [event for event in events if event["seq"] > after]),
        }

    def watch(
        self, cursor: EventCursor | None = None, *, seconds: float | None = None, interval: float = 0.025
    ) -> Iterator[JsonObject]:
        if seconds is not None and (not math.isfinite(seconds) or seconds <= 0):
            raise ClientError("invalid_events_options", "事件监听时长须为正数。")
        if not math.isfinite(interval) or not 0.01 <= interval <= 1:
            raise ClientError("invalid_events_options", "事件读取间隔须为 0.01 至 1 秒。")
        metadata: JsonObject = {
            "backend": self.backend,
            "instance": self.instance,
            "instance_id": self.identity[0],
            "run_id": self.identity[1],
        }
        deadline = time.monotonic() + seconds if seconds is not None else None
        current = cursor
        ready = False
        unavailable = False
        while deadline is None or time.monotonic() < deadline:
            try:
                report = self.read(current)
            except ClientError as error:
                if error.code != "stale_bridge_state":
                    raise
                if not unavailable:
                    yield {
                        "event": "events_unavailable",
                        **metadata,
                        "cursor": current.document() if current is not None else None,
                        "error": {"code": error.code, "message": error.message, "details": error.details},
                    }
                unavailable = True
            else:
                pending = cast(list[JsonObject], report["events"]) if current is not None else []
                if current is None:
                    current = EventCursor(*self.identity, cast(int, report["last_seq"]))
                if not ready or unavailable:
                    yield {"event": "events_ready", **metadata, "cursor": current.document()}
                    ready = True
                unavailable = False
                for event in pending:
                    current = EventCursor(*self.identity, cast(int, event["seq"]))
                    yield {"event": "client_event", **metadata, "cursor": current.document(), "data": event}
            if deadline is not None and time.monotonic() >= deadline:
                return
            time.sleep(interval if deadline is None else min(interval, max(0, deadline - time.monotonic())))
