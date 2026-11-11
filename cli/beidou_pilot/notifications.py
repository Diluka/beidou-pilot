"""统一读取通知气泡并响应当前真实按钮，不推断后续业务结果。"""

import hashlib
import json
import time
from typing import TypedDict, cast

from .backend import Backend
from .engines.ui import UIButton, UIWindow
from .errors import ClientError, JsonObject
from .ui import click_control


class NotificationButton(UIButton):
    action: str | None


class Notification(TypedDict):
    id: str
    ref: str
    native_kind: int
    kind: str | None
    source_text: str | None
    text: str | None
    sender_id: int | None
    party_id: int | None
    interaction_id: int | None
    quest_id: int | None
    expires_at_ms: int | None
    remaining_ms: int | None
    pending: bool
    available: bool
    window: UIWindow
    buttons: list[NotificationButton]


def read_notifications(backend: Backend) -> JsonObject:
    report = backend.read("notifications")
    client = cast(JsonObject, report["client"])
    for notification in cast(list[Notification], report["notifications"]):
        scope = [report["instance_id"], client["run_id"], report["scene_generation"], notification["id"]]
        notification["ref"] = "@notification" + hashlib.sha256(json.dumps(scope).encode()).hexdigest()[:16]
    return report


def respond(backend: Backend, reference: str, button_id: int) -> JsonObject:
    before = read_notifications(backend)
    notification = next(
        (item for item in cast(list[Notification], before["notifications"]) if item["ref"] == reference), None
    )
    if (
        notification is None
        or not notification["available"]
        or (notification["expires_at_ms"] is not None and notification["expires_at_ms"] <= time.time() * 1000)
    ):
        raise ClientError("stale_notification", "气泡引用已失效或当前不可响应，请重新读取 notifications。")
    button = next((item for item in notification["buttons"] if item["control_id"] == button_id), None)
    if button is None:
        raise ClientError(
            "notification_button_unavailable",
            "当前气泡没有指定按钮，未派发输入。",
            {"button_id": button_id, "buttons": cast(list[JsonObject], notification["buttons"])},
        )
    identity = before["instance_id"], cast(JsonObject, before["client"])["run_id"]
    click_control(backend, notification["window"], button_id)
    result: JsonObject = {
        "notification": cast(JsonObject, notification),
        "button": cast(JsonObject, button),
        "input_dispatched": True,
        "effect": "unknown",
    }
    try:
        current = read_notifications(backend)
    except ClientError as error:
        # 输入已经派发；后续界面或采样不可用时保留事实，调用方不能把它当成未发送而重放。
        return {
            **result,
            "after": None,
            "observation_error": {"code": error.code, "message": error.message, "details": error.details},
        }
    if (current["instance_id"], cast(JsonObject, current["client"])["run_id"]) != identity:
        raise ClientError("notification_identity_changed", "响应后实例已变化，未把后继实例当作本次结果。", result)
    after = next(
        (item for item in cast(list[Notification], current["notifications"]) if item["id"] == notification["id"]), None
    )
    return {
        **result,
        "after": {
            "present": after is not None,
            "pending": after["pending"] if after is not None else False,
            "available": after["available"] if after is not None else False,
            "notification": cast(JsonObject | None, after),
        },
    }
