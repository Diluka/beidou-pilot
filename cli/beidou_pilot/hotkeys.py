"""读取真实快捷键绑定，并通过普通拖动绑定物品或技能。"""

import time
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .engines.character import CharacterSnapshot
from .engines.hotkeys import BindingKind, HotkeysSnapshot
from .ui import click_window, open_window, read_ui


BINDING_TYPES: dict[BindingKind, int] = {"skill": 1, "item": 2}


def read_hotkeys(backend: Backend) -> HotkeysSnapshot:
    snapshot = cast(HotkeysSnapshot, backend.read("hotkeys"))
    if snapshot["unavailable"]:
        raise ClientError("hotkeys_unavailable", "当前快捷键读数不可用。",
                          {"unavailable": snapshot["unavailable"]})
    return snapshot


def bind_item(backend: Backend, item_id: int, key: str) -> JsonObject:
    return _bind(backend, "item", item_id, key)


def bind_skill(backend: Backend, skill_id: int, key: str) -> JsonObject:
    return _bind(backend, "skill", skill_id, key)


def _bind(backend: Backend, kind: BindingKind, identifier: int, key: str) -> JsonObject:
    snapshot = read_hotkeys(backend)
    aliases = {"shift": "Shift_L", "ctrl": "Control_L", "control": "Control_L",
               "alt": "Alt_L", "pgup": "Prior", "pageup": "Prior",
               "pgdn": "Next", "pagedown": "Next", "ins": "Insert", "del": "Delete"}
    name = aliases.get(key.casefold(), key)
    target = next((slot for slot in snapshot["quickslots"]
                   if slot["key"] and slot["key"].casefold() == name.casefold()), None)
    if target is None:
        raise ClientError("hotkey_not_in_quickbar", "目标键尚未在当前快捷栏中定位。", {"key": key})
    previous = next(binding for binding in snapshot["bindings"] if binding["key_code"] == target["key_code"])
    if previous["type"] == BINDING_TYPES[kind] and previous["id"] == identifier:
        return {"kind": kind, "id": identifier, "key": target["key"],
                "key_code": target["key_code"], "bound": True, "changed": False}
    if snapshot["drag_object"] is not None:
        raise ClientError("hotkey_drag_pending", "鼠标仍持有上次拖起的对象，请先正常落下或取消。",
                          {"drag_object": snapshot["drag_object"]})
    if not snapshot["quickslots_open"]:
        raise ClientError("quickbar_closed", "当前快捷栏已经收起，请先展开快捷栏。")

    if kind == "item":
        from .items import read_inventory

        # CDraggableItem::MapFuncKey 原生白名单(0x4F3C59)，203回城卷会直接拒绝。
        if (identifier // 10000 not in {200, 201, 202, 205, 212, 221, 226, 227, 236, 238, 245}
                and identifier // 1000 != 2109 and identifier != 2100067):
            raise ClientError("native_item_not_bindable", "本客户端原生不允许将该物品映射到快捷键，请从背包使用。",
                              {"item_id": identifier, "category": identifier // 10000,
                               "rule": "CDraggableItem::MapFuncKey consumption whitelist"})
        inventory = read_inventory(backend, 2)
        item = next((entry for entry in inventory["items"] if entry["item_id"] == identifier), None)
        if item is None:
            raise ClientError("item_missing", "消费背包中没有该物品。", {"item_id": identifier})
        slot = item["slot"]
        window = open_window(backend, "inventory")
        click_window(backend, window, 54, 34)
        window = next(entry for entry in read_ui(backend)["windows"] if entry["address"] == window["address"])
        view = window["inventory"]
        if view is None or view["selected_type"] != 2 or view["expanded"]:
            raise ClientError("inventory_layout_unverified", "未确认普通消费背包布局，已停止绑定。")
        while not view["first_slot"] <= slot < view["first_slot"] + 24:
            direction = "up" if slot < view["first_slot"] else "down"
            first = view["first_slot"]
            click_window(backend, window, 80, 90)
            backend.read("desktop", "scroll", direction, "--ticks", "1")
            window = next(entry for entry in read_ui(backend)["windows"] if entry["address"] == window["address"])
            view = window["inventory"]
            if (view is None or view["selected_type"] != 2
                    or (direction == "down" and view["first_slot"] <= first)
                    or (direction == "up" and view["first_slot"] >= first)):
                raise ClientError("inventory_scroll_not_confirmed", "背包滚动未确认，已停止绑定。")
        index = slot - view["first_slot"]
        source_x, source_y = 24 + index % 4 * 36, 66 + index // 4 * 34
    else:
        # 已学技能列表由客户端记录校验，拖放是否允许仍由原生技能窗口决定。
        learned = cast(CharacterSnapshot, backend.read("character"))
        if not learned["skills_complete"]:
            raise ClientError("skills_unavailable", "当前已学技能记录不完整。")
        skill = learned["skills"].get(str(identifier))
        if skill is None or skill["level"] < 1:
            raise ClientError("skill_not_learned", "当前角色尚未学会该技能。", {"skill_id": identifier})
        window = open_window(backend, "skills")
        skills = window["skills"]
        if skills is None:
            raise ClientError("skills_ui_unavailable", "当前技能窗口列表不可用。")
        if identifier not in skills["ids"]:
            for tab in range(skills["tab_count"]):
                if tab == skills["selected_tab"]:
                    continue
                click_window(backend, window, 19 + tab * 35, 34)
                window = next(entry for entry in read_ui(backend)["windows"] if entry["address"] == window["address"])
                skills = window["skills"]
                if skills is None:
                    raise ClientError("skills_ui_unavailable", "技能页切换后列表不可用。")
                if identifier in skills["ids"]:
                    break
        if identifier not in skills["ids"]:
            raise ClientError("skill_not_in_ui", "当前角色技能页没有该技能。", {"skill_id": identifier})
        index = skills["ids"].index(identifier)
        for _ in range(len(skills["ids"])):
            if 0 <= index - skills["first_index"] < 4:
                break
            direction = "down" if index >= skills["first_index"] + 4 else "up"
            first = skills["first_index"]
            click_window(backend, window, 100, 130)
            backend.read("desktop", "scroll", direction, "--ticks", "1")
            window = next(entry for entry in read_ui(backend)["windows"] if entry["address"] == window["address"])
            skills = window["skills"]
            if skills is None or skills["first_index"] == first:
                raise ClientError("skill_scroll_not_confirmed", "技能列表滚动未确认，已停止绑定。")
        row = index - skills["first_index"]
        if not 0 <= row < 4:
            raise ClientError("skill_not_visible", "目标技能尚未滚入可见行。", {"skill_id": identifier})
        # CUISkill 原生严格图标命中矩形 (10,102)-(42,134)，每行下移40。
        source_x, source_y = 26, 118 + row * 40

    ui = read_ui(backend)
    status = next((entry for entry in ui["windows"] if entry["vtables"][0] == "0xb3ba80"), None)
    if status is None or status["root_rect"] is None or window["root_rect"] is None:
        raise ClientError("quickbar_position_unavailable", "当前快捷栏或来源窗口根坐标不可用。")
    source_rect, status_rect = window["root_rect"], status["root_rect"]
    target_x = status_rect["left"] + snapshot["origin_x"] + target["local_x"] + 16
    target_y = status_rect["top"] + snapshot["origin_y"] + target["local_y"] + 16
    backend.desktop([{"action": "drag", "from_x": source_rect["left"] + source_x,
                    "from_y": source_rect["top"] + source_y,
                    "to_x": target_x, "to_y": target_y},
                   {"action": "wait", "seconds": 0.2}])
    deadline = time.monotonic() + 1.2
    while True:
        after = read_hotkeys(backend)
        current = next(binding for binding in after["bindings"] if binding["key_code"] == target["key_code"])
        confirmed = (current["type"] == BINDING_TYPES[kind] and current["id"] == identifier
                     and after["drag_object"] is None)
        if confirmed or time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    if not confirmed:
        raise ClientError("hotkey_bind_not_confirmed", "普通拖动后未在客户端键位表确认目标绑定。",
                          {"kind": kind, "id": identifier, "key": target["key"],
                           "type_after": current["type"], "id_after": current["id"],
                           "drag_object": after["drag_object"],
                           "source": {"x": source_rect["left"] + source_x,
                                      "y": source_rect["top"] + source_y},
                           "target": {"x": target_x, "y": target_y}})
    return {"kind": kind, "id": identifier, "key": target["key"],
            "key_code": target["key_code"], "bound": True, "changed": True,
            "previous_type": previous["type"], "previous_id": previous["id"]}
