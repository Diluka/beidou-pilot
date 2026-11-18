"""按明确请求完成本端正常复活，并核对同一角色恢复。"""

import time
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .bridge import BridgeClient
from .ui import click_control, read_ui
from .engines.ui import UIWindow


def revive(backend: Backend) -> JsonObject:
    """两端各提交一次普通复活动作，并核对同一角色恢复。"""
    before = backend.read("observe")
    character = cast(JsonObject | None, before["character"])
    if character is None or before["native_values_valid"] is not True:
        raise ClientError("character_unavailable", "尚无可用角色读数。")
    if cast(int, character["hp"]) > 0:
        return {"status": "already_alive", "changed": False, "state": before}
    if backend.name == "headless":
        bridge = BridgeClient(backend.root, backend.name, backend.instance)
        running = next(
            (script for script in bridge.snapshot().get("scripts", []) if script["status"] == "running"), None
        )
        if running is not None:
            raise ClientError("input_busy", "已有Lua脚本正在控制角色，未发送复活请求。", {"script_id": running["id"]})
        request = bridge.run_script(
            code="""local function main(context)
    local ok, reason = context.game.player.revive()
    if not ok then error(reason or "revive_request_rejected") end
    return "done"
end
return {main=main, context=__beidou_context}
""",
            seconds=6,
            timeout=9,
        )
        deadline = time.monotonic() + 6
        after = before
        while time.monotonic() < deadline:
            after = backend.read("observe")
            updated = cast(JsonObject | None, after["character"])
            if updated is not None and after["native_values_valid"] is True:
                if updated["id"] != character["id"]:
                    raise ClientError("character_changed", "确认期间角色已变化，停止操作。")
                if cast(int, updated["hp"]) > 0 and after["map_id"] is not None and after["position"] is not None:
                    return {"status": "revived", "changed": True, "before_map": before["map_id"], "state": after}
            time.sleep(0.15)
        raise ClientError(
            "revive_not_confirmed",
            "已提交一次无头复活请求，尚未观察到同角色恢复，不重复请求。",
            {"state": after, "request": request},
        )
    deadline = time.monotonic() + 3
    window = None
    while time.monotonic() < deadline:
        ui = read_ui(backend)
        matches = [w for w in cast(list[UIWindow], ui["windows"]) if w["vtables"][0] == "0xb3b1a8"]
        if len(matches) == 1:
            window = matches[0]
            break
        time.sleep(0.15)
    if window is None:
        raise ClientError("revive_dialog_unavailable", "角色已死亡，尚未出现已识别的复活确认窗口，未发送输入。")
    buttons = window["buttons"]
    confirm = next((b for b in buttons if b["control_id"] == 1), None)
    if len(buttons) != 1 or confirm is None or confirm.get("enabled") is not True:
        raise ClientError(
            "revive_layout_changed", "复活窗口控件未唯一启用或与已验布局不符，未发送输入。", {"window": window}
        )
    click_control(backend, window, 1)
    deadline = time.monotonic() + 6
    after = before
    while time.monotonic() < deadline:
        after = backend.read("observe")
        updated = cast(JsonObject | None, after["character"])
        if updated is not None and after["native_values_valid"] is True:
            if updated["id"] != character["id"]:
                raise ClientError("character_changed", "确认期间角色已变化，停止操作。")
            if cast(int, updated["hp"]) > 0 and after["map_id"] is not None and after["position"] is not None:
                ui_after = read_ui(backend)
                remaining = [window for window in ui_after["windows"] if window["vtables"][0] == "0xb3b1a8"]
                if not ui_after["unavailable"] and not remaining:
                    return {"status": "revived", "changed": True, "before_map": before["map_id"], "state": after}
        time.sleep(0.15)
    raise ClientError("revive_not_confirmed", "已点击一次复活确认，尚未观察到恢复，不重复点击。", {"state": after})
