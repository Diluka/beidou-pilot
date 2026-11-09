"""按客户端当前正文、选项与投影坐标完成普通鼠标交互。"""

import time
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .snapshot import BUTTONS, collect
from .catalog import Catalog


def choose(values: list[JsonObject], selector: str, field: str = "text") -> JsonObject:
    exact = [v for v in values if str(v.get(field, "")).strip() == selector.strip() or v.get("ref") == selector]
    if not exact and selector.isdecimal():
        exact = [v for v in values if v.get("link_id") == int(selector) or v.get("template_id") == int(selector)]
    if not exact:
        exact = [v for v in values if selector in str(v.get(field, ""))]
    if len(exact) != 1:
        raise ClientError("ambiguous_target" if exact else "target_not_found", "请按当前快照中的文字、ID或引用指定唯一目标。",
                          {"selector": selector, "candidates": values})
    return exact[0]


def click_rect(backend: Backend, rect: JsonObject | None) -> JsonObject:
    if rect is None:
        raise ClientError("layout_unavailable", "当前目标没有可用的屏幕矩形，请重新 snapshot。")
    stage = backend.read("stage")
    geometry = cast(JsonObject, stage["game_geometry"])
    x = (cast(int, rect["left"]) + cast(int, rect["right"])) // 2
    y = (cast(int, rect["top"]) + cast(int, rect["bottom"])) // 2
    if not (cast(int, geometry["x"]) <= x < cast(int, geometry["x"]) + cast(int, geometry["width"])
            and cast(int, geometry["y"]) <= y < cast(int, geometry["y"]) + cast(int, geometry["height"])):
        raise ClientError("target_offscreen", "目标当前不在游戏窗口内，未发送点击。", {"rect": rect})
    return backend.desktop([{"action": "click", "x": x, "y": y}, {"action": "wait", "seconds": 0.4}])


def act(backend: Backend, action: str, selector: str | None = None) -> JsonObject:
    raw = backend.read("dialog")
    if raw["dialog_open"] is not True:
        raise ClientError("no_dialog", "当前没有已识别的NPC对话。")
    dialog: JsonObject = {"open": raw["dialog_open"], "choices": raw["choices"],
                          "buttons": [{**a, "action": BUTTONS.get(cast(int, a["control_id"]), str(a["control_id"]))}
                                      for a in cast(list[JsonObject], raw["buttons"])]}
    if selector and selector.startswith("@"):
        snapshot = collect(backend, all_entities=True)
        dialog = cast(JsonObject, snapshot["dialog"])
    if action == "select":
        target = choose(cast(list[JsonObject], dialog["choices"]), cast(str, selector))
    else:
        candidates = cast(list[JsonObject], dialog["buttons"])
        if action == "next" and dialog["choices"]:
            raise ClientError("choice_required", "当前需要选择菜单项，请使用 dialog select。", {"choices": dialog["choices"]})
        target = next((a for a in candidates if a["action"] == action), None)
        if target is None and action == "next":
            target = next((a for a in candidates if a["action"] == "confirm"), None)
        if target is None:
            raise ClientError("button_not_available", "当前页没有该按钮。", {"action": action, "buttons": candidates})
    click_rect(backend, cast(JsonObject | None, target["root_rect"]))
    return {"action": action, "target": target, "dialog": backend.read("dialog"), "state": backend.read("observe")}


def advance(backend: Backend, *, accept: bool = False, seconds: float = 20) -> JsonObject:
    deadline = time.monotonic() + seconds
    pages: list[JsonObject] = []
    while time.monotonic() < deadline:
        d = backend.read("dialog")
        if d["dialog_open"] is not True:
            return {"status": "closed", "pages": pages, "state": backend.read("observe")}
        if d["choices"]:
            return {"status": "choice_required", "pages": pages, "dialog": d}
        kind = d["dialog_type"]
        if kind == 1 and not accept:
            return {"status": "confirmation_required", "pages": pages, "dialog": d}
        if kind not in (0, 1):
            return {"status": "input_required", "pages": pages, "dialog": d}
        pages.append({"npc_id": d["npc_id"], "lines": d["lines"]})
        result = act(backend, "yes" if kind == 1 else "next")
        after = cast(JsonObject, result["dialog"])
        if [after["npc_id"], after["dialog_type"], after["lines"]] == [d["npc_id"], d["dialog_type"], d["lines"]]:
            return {"status": "unchanged", "pages": pages, "dialog": after}
    return {"status": "budget_reached", "pages": pages, "dialog": backend.read("dialog")}


def talk(backend: Backend, selector: str) -> JsonObject:
    state = collect(backend, all_entities=True)
    npc = choose(cast(list[JsonObject], state.get("npcs", [])), selector, "name")
    current = cast(JsonObject, state["dialog"])
    if current["open"]:
        if current["npc_id"] == npc["template_id"]:
            return {"status": "already_open", "dialog": current}
        raise ClientError("dialog_blocks_talk", "请先结束当前NPC对话。", {"dialog": current})
    existing_shop = backend.read("shop")
    if existing_shop.get("open"):
        if existing_shop.get("npc_id") == npc["template_id"]:
            return {"status": "already_open", "npc": npc, "shop": existing_shop}
        raise ClientError("shop_blocks_talk", "请先退出当前商店再与另一NPC交互。")
    d = backend.read("dialog")
    stage = backend.read("stage")
    viewport, geometry = (cast(JsonObject, v) for v in (d["camera_viewport"], stage["game_geometry"]))
    metadata = Catalog(backend.root).npc(cast(int, npc["template_id"]))
    bounds = cast(JsonObject | None, metadata["click_rect"])
    if bounds is None:
        raise ClientError("npc_hitbox_unavailable", "缺少这个NPC的可点击图形资料，请以当前小截图辅助定位。", {"npc": npc})
    offset_x = (cast(int, bounds["left"]) + cast(int, bounds["right"])) // 2
    offset_y = (cast(int, bounds["top"]) + cast(int, bounds["bottom"])) // 2
    x = cast(int, npc["x"]) + offset_x - cast(int, viewport["left"]) + cast(int, geometry["x"])
    y = cast(int, npc["y"]) + offset_y - cast(int, viewport["top"]) + cast(int, geometry["y"])
    if not (cast(int, geometry["x"]) <= x < cast(int, geometry["x"]) + cast(int, geometry["width"])
            and cast(int, geometry["y"]) <= y < cast(int, geometry["y"]) + cast(int, geometry["height"])):
        raise ClientError("npc_offscreen", "NPC在画外，请先按 snapshot 的坐标移动靠近。", {"npc": npc})
    backend.desktop([{"action": "double-click", "x": x, "y": y}, {"action": "wait", "seconds": 0.5}])
    d = backend.read("dialog")
    if d["npc_id"] != npc["template_id"]:
        shop = backend.read("shop")
        if shop.get("open") and shop.get("npc_id") == npc["template_id"]:
            return {"status": "shop_opened", "npc": npc, "shop": shop}
        raise ClientError("talk_not_confirmed", "未确认目标NPC对话，已停止点击。", {"npc": npc, "dialog": d})
    return {"status": "opened", "npc": npc, "dialog": d}
