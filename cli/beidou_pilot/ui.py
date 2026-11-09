"""游戏内部窗口定位与普通鼠键焦点恢复。"""

from dataclasses import dataclass
import time
from typing import Literal, cast

from .backend import Backend, ClientError, JsonObject
from .engines.ui import UISnapshot, UIWindow


WindowName = Literal["inventory", "stats", "skills"]


@dataclass(frozen=True)
class WindowSpec:
    key: str
    vtable: str
    width: int
    height: int


# 类型与尺寸由本客户端普通开窗后的活动 CWnd 差集校准。
WINDOWS: dict[WindowName, WindowSpec] = {
    "inventory": WindowSpec("i", "0xb39108", 175, 289),
    "stats": WindowSpec("s", "0xb3b908", 210, 348),
    "skills": WindowSpec("k", "0xb3b5cc", 175, 289),
}


def read_ui(backend: Backend) -> UISnapshot:
    snapshot = cast(UISnapshot, backend.read("ui"))
    if snapshot["unavailable"]:
        raise ClientError("ui_unavailable", "客户端窗口定位不可用。",
                          {"unavailable": snapshot["unavailable"]})
    return snapshot


def focus_game(backend: Backend) -> JsonObject:
    snapshot = read_ui(backend)
    dialog = snapshot["dialog"]
    if any(dialog[key] is not False for key in (
        "script_dialog_open", "focused_talk_dialog_open", "registered_talk_dialog_open",
    )):
        raise ClientError("dialog_open", "先处理当前 NPC 对话，再操作游戏。")
    if any(window["vtables"][0] == "0xafe110" for window in snapshot["windows"]):
        raise ClientError("shop_open", "普通商店仍打开，请先使用 shop close。", {"next_action": "shop close"})
    handler = dialog["keyboard_handler"]
    if handler and handler["type_name"] == "CWndMan::IUIMsgHandler":
        return {"focused": True, "changed": False}
    geometry = snapshot["game_geometry"]
    if geometry is None:
        raise ClientError("ui_unavailable", "游戏内容窗口几何位置不可用。")
    scene = backend.read("scene")
    camera = dialog["camera_viewport"]
    if camera is None or scene["pending_dynamic"]:
        raise ClientError("scene_unavailable", "当前场景尚不能用于寻找空白焦点位置。")
    npcs = cast(list[dict[str, int]], scene["npcs"])
    # 这三个常驻场景层不作为弹出窗口遮挡；其他活动 CWnd 均避开。
    scene_tables = {"0xb3f13c", "0xb37bbc", "0xb3ba80"}
    blockers = []
    for window in snapshot["windows"]:
        if window["vtables"][0] in scene_tables:
            continue
        rect = window["game_rect"]
        if rect is None:
            raise ClientError("ui_unavailable", "活动窗口位置未知，无法安全恢复游戏焦点。",
                              {"window": window["address"]})
        blockers.append(rect)
    target = None
    for y in (110, 190, 290, 390, 490):
        for x in (320, 480, 640, 800, 960, 1120):
            if x >= geometry["width"] - 20 or y >= geometry["height"] - 120:
                continue
            if any(rect["left"] - 8 <= x <= rect["right"] + 8
                   and rect["top"] - 8 <= y <= rect["bottom"] + 8 for rect in blockers):
                continue
            if any(abs(x - (npc["x"] - camera["left"])) <= 70
                   and npc["y"] - camera["top"] - 130 <= y <= npc["y"] - camera["top"] + 25
                   for npc in npcs):
                continue
            target = (x + geometry["x"], y + geometry["y"])
            break
        if target:
            break
    if target is None:
        raise ClientError("ui_blocked", "没有可确认的空白场景位置可恢复焦点。")
    backend.desktop([{"action": "click", "x": target[0], "y": target[1]},
                   {"action": "wait", "seconds": 0.1}])
    after = read_ui(backend)
    handler = after["dialog"]["keyboard_handler"]
    if not handler or handler["type_name"] != "CWndMan::IUIMsgHandler":
        raise ClientError("game_focus_blocked", "空白场景点击后，游戏键盘焦点仍未恢复。",
                          {"click_x": target[0], "click_y": target[1]})
    return {"focused": True, "changed": True, "click_x": target[0], "click_y": target[1]}


def open_window(backend: Backend, name: WindowName) -> UIWindow:
    spec = WINDOWS.get(name)
    if spec is None:
        raise ClientError("ui_layout_unverified", "该窗口尚未完成本客户端布局校准。", {"window": name})
    snapshot = read_ui(backend)
    if any(snapshot["dialog"][key] is not False for key in (
        "script_dialog_open", "focused_talk_dialog_open", "registered_talk_dialog_open",
    )):
        raise ClientError("dialog_open", "先处理当前 NPC 对话，再操作游戏窗口。")
    matches = [window for window in snapshot["windows"] if window["vtables"][0] == spec.vtable]
    if not matches:
        focus_game(backend)
        backend.desktop([{"action": "hold", "keys": [spec.key], "seconds": 0.1},
                         {"action": "wait", "seconds": 0.2}])
        snapshot = read_ui(backend)
        matches = [window for window in snapshot["windows"] if window["vtables"][0] == spec.vtable]
    if len(matches) != 1:
        raise ClientError("ui_window_missing", "未能唯一确认目标窗口。", {"window": name})
    window = matches[0]
    if (window["width"], window["height"]) != (spec.width, spec.height) or window["root_rect"] is None:
        raise ClientError("ui_layout_changed", "窗口布局与已校准版本不符。", {"window": name})
    # 在可见标题栏激活窗口，防止重叠窗口接收加点或物品双击。
    rect = window["root_rect"]
    above = snapshot["windows"][snapshot["windows"].index(window) + 1:]
    title_point = None
    for x in range(20, window["width"] - 30, 10):
        root_x, root_y = rect["left"] + x, rect["top"] + 12
        if all(not (other["root_rect"] and other["root_rect"]["left"] <= root_x <= other["root_rect"]["right"]
                    and other["root_rect"]["top"] <= root_y <= other["root_rect"]["bottom"]) for other in above):
            title_point = (x, 12)
            break
    if title_point is None:
        raise ClientError("ui_title_occluded", "目标窗口标题栏被其他窗口覆盖。", {"window": name})
    click_window(backend, window, *title_point)
    activated = read_ui(backend)
    focused = activated["dialog"]["focused_window"]
    if not focused or focused["address"] != window["address"]:
        raise ClientError("ui_activation_failed", "标题栏点击后未确认目标窗口取得焦点。", {"window": name})
    return next(current for current in activated["windows"] if current["address"] == window["address"])


def click_window(backend: Backend, window: UIWindow, x: int, y: int, *, double: bool = False) -> None:
    rect = window["root_rect"]
    if rect is None:
        raise ClientError("ui_unavailable", "窗口根坐标不可用。")
    if not (0 <= x < window["width"] and 0 <= y < window["height"]):
        raise ClientError("ui_target_outside", "点击目标不在当前窗口内。")
    backend.desktop([{"action": "double-click" if double else "click",
                    "x": rect["left"] + x, "y": rect["top"] + y},
                   {"action": "wait", "seconds": 0.2}])


def click_control(backend: Backend, window: UIWindow, control_id: int) -> None:
    buttons = [button for button in window["buttons"] if button["control_id"] == control_id]
    if len(buttons) != 1:
        raise ClientError("ui_control_missing", "未能唯一定位目标按钮。", {"control_id": control_id})
    button = buttons[0]
    click_window(backend, window, button["layout_x"] + button["width"] // 2,
                 button["layout_y"] + button["height"] // 2)


def close_window(backend: Backend, name: WindowName) -> JsonObject:
    spec = WINDOWS[name]
    snapshot = read_ui(backend)
    matches = [window for window in snapshot["windows"] if window["vtables"][0] == spec.vtable]
    if not matches:
        return {"window": name, "closed": True, "already_closed": True, "changed": False}
    if len(matches) != 1:
        raise ClientError("ui_window_ambiguous", "未能唯一确认需要关闭的窗口。", {"window": name})
    focus_game(backend)
    backend.desktop([{"action": "hold", "keys": [spec.key], "seconds": 0.1},
                         {"action": "wait", "seconds": 0.2}])
    deadline = time.monotonic() + 1.2
    snapshot = read_ui(backend)
    while any(window["vtables"][0] == spec.vtable for window in snapshot["windows"]):
        if time.monotonic() >= deadline:
            raise ClientError("ui_close_not_confirmed", "快捷键已发送，活动窗口仍未关闭。", {"window": name})
        time.sleep(0.1)
        snapshot = read_ui(backend)
    return {"window": name, "closed": True, "already_closed": False, "changed": True}
