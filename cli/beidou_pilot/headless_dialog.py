"""无头交互：只激活客户端给出的原生引用，不模拟桌面点击。"""

from typing import cast

from .backend import Backend, ClientError, JsonObject
from .bridge import BridgeClient
from .dialogs import choose


def read(backend: Backend) -> JsonObject:
    observed = backend.read("interaction")
    page = cast(JsonObject | None, observed["page"])
    if page is None:
        return {"dialog_open": False, "lines": [], "choices": [], "buttons": [], "page": None,
                "unavailable": observed.get("unavailable", [])}
    controls = cast(list[JsonObject] | None, page["controls"])
    text = cast(str | None, page["text"])
    return {"dialog_open": True, "lines": text.splitlines() if text is not None else None,
            "choices": [c for c in controls if c["role"] == "option"] if controls is not None else None,
            "buttons": [c for c in controls if c["role"] == "button"] if controls is not None else None,
            "page": page, "unavailable": observed.get("unavailable", [])}


def activate(backend: Backend, reference: str) -> JsonObject:
    if not reference.startswith("@ui-") or not reference.isascii() or any(c.isspace() for c in reference):
        raise ClientError("stale_interaction_reference", "引用无效或已过期。", {"ref": reference})
    bridge = BridgeClient(backend.root, backend.name, backend.instance)
    with bridge._control():
        before = bridge._ready_state()
        if any(s["status"] == "running" for s in before.get("scripts", [])):
            raise ClientError("input_busy", "已有脚本控制客户端。")
        request = bridge._publish(before, "interact", 0, [reference])
        try:
            bridge._wait(before, request, 3)
        except ClientError as error:
            if error.code == "bridge_command_rejected":
                reason = str(error.details.get("reason", "interaction_rejected"))
                raise ClientError(reason, "客户端拒绝交互。", error.details) from error
            raise ClientError("interaction_unknown", "交互已发布，结果未知；请观察后再决定，不要重放。",
                              {"request_id": request, "cause": error.code}) from error
    return {"status": "dispatched", "ref": reference, "dialog": read(backend)}


def talk(backend: Backend, selector: str) -> JsonObject:
    if selector.startswith("@"):
        return activate(backend, selector)
    scene = backend.read("scene")
    npcs = cast(list[JsonObject], scene["npcs"])
    matches = [n for n in npcs if str(n.get("object_id")) == selector]
    npc = matches[0] if len(matches) == 1 else choose(npcs, selector, "name")
    result = activate(backend, cast(str, npc["ref"]))
    result["npc"] = npc
    return result


def act(backend: Backend, action: str, selector: str | None = None) -> JsonObject:
    if selector and selector.startswith("@"):
        return activate(backend, selector)
    dialog = read(backend)
    if not dialog["dialog_open"]:
        raise ClientError("no_dialog", "当前没有对话。")
    page = cast(JsonObject, dialog["page"])
    controls = cast(list[JsonObject] | None, page["controls"])
    if controls is None:
        raise ClientError("control_availability_unknown", "当前页面控件未知。")
    if action == "select":
        if selector is None:
            raise ClientError("usage", "dialog select需要选项文字或引用。")
        target = choose([c for c in controls if c["role"] == "option"], selector)
    else:
        labels = {"next": ("下一页", "确认"), "back": ("上一页", "返回列表"),
                  "confirm": ("确认", "接受", "交付"), "yes": ("是", "接受"),
                  "no": ("否", "暂不接受"), "end": ("结束", "关闭")}.get(action, ())
        if action == "next" and any(c["role"] == "option" for c in controls):
            raise ClientError("choice_required", "当前页面需要选择选项。")
        target = next((c for label in labels for c in controls if c["role"] == "button" and c["text"] == label), None)
        if target is None:
            raise ClientError("button_not_available", "当前页面没有该按钮。", {"action": action})
    return activate(backend, cast(str, target["ref"]))
