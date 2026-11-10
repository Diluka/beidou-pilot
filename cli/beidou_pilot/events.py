"""读取本实例原生事件序列；不取得输入控制权，也不决定游戏动作。"""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Iterator, cast

from .bridge import BridgeClient
from .errors import ClientError, JsonObject


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
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("instance_id"), str)
        or not raw["instance_id"]
        or not isinstance(raw.get("run_id"), str)
        or not raw["run_id"]
        or type(raw.get("seq")) is not int
        or raw["seq"] < 0
    ):
        raise ClientError("invalid_events_cursor", "事件游标须提供非空实例与运行身份及非负整数 seq。")
    return EventCursor(raw["instance_id"], raw["run_id"], raw["seq"])


class EventReader:
    def __init__(self, root: Path, backend: str, instance: str = "default") -> None:
        if backend != "beidou":
            raise ClientError("unsupported_capability", "当前无头客户端尚未提供原生邀请事件。")
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
        if (
            not isinstance(raw, dict)
            or type(raw.get("protocol")) is not int
            or raw["protocol"] != 1
            or not isinstance(raw.get("instance_id"), str)
            or not isinstance(raw.get("run_id"), str)
            or type(raw.get("first_seq")) is not int
            or type(raw.get("last_seq")) is not int
            or not isinstance(raw.get("events"), list)
        ):
            raise ClientError("invalid_events", "原生事件序列缺少有效信封。")
        if (raw["instance_id"], raw["run_id"]) != self.identity:
            raise ClientError("events_identity_changed", "原生事件序列不属于当前实例运行。")
        events = raw["events"]
        if raw["first_seq"] < 1 or raw["last_seq"] < 0 or raw["first_seq"] != raw["last_seq"] - len(events) + 1:
            raise ClientError("invalid_events", "原生事件序列的保留范围无效。")
        for seq, event in enumerate(events, start=raw["first_seq"]):
            if (
                not isinstance(event, dict)
                or type(event.get("seq")) is not int
                or event["seq"] != seq
                or any(type(event.get(key)) is not int for key in ("observed_at_ms", "scene_generation"))
                or "character_id" not in event
                or event.get("character_id") is not None
                and type(event["character_id"]) is not int
                or not isinstance(event.get("type"), str)
                or not isinstance(event.get("source"), str)
                or "expires_at_ms" not in event
                or event["expires_at_ms"] is not None
                and type(event["expires_at_ms"]) is not int
                or not isinstance(event.get("data"), dict)
            ):
                raise ClientError("invalid_events", "原生事件条目的类型或序号无效。")
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
        first = self.read(cursor)
        current = cursor or EventCursor(*self.identity, cast(int, first["last_seq"]))
        metadata: JsonObject = {
            "backend": self.backend,
            "instance": self.instance,
            "instance_id": self.identity[0],
            "run_id": self.identity[1],
        }
        deadline = time.monotonic() + seconds if seconds is not None else None
        yield {"event": "events_ready", **metadata, "cursor": current.document()}
        pending = cast(list[JsonObject], first["events"]) if cursor is not None else []
        while True:
            for event in pending:
                current = EventCursor(*self.identity, cast(int, event["seq"]))
                yield {"event": "client_event", **metadata, "cursor": current.document(), "data": event}
            if deadline is not None and time.monotonic() >= deadline:
                return
            time.sleep(interval if deadline is None else min(interval, max(0, deadline - time.monotonic())))
            pending = cast(list[JsonObject], self.read(current)["events"])
