"""提交一次自动加点，并以同角色实际属性确认结果。"""

import time
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .bridge import BridgeClient
from .strategies import compile_strategy
from .strategy_scene import scene_context


def auto_ap(backend: Backend) -> JsonObject:
    before = backend.read("observe")
    character = cast(JsonObject | None, before["character"])
    if character is None or before["native_values_valid"] is not True:
        raise ClientError("character_unavailable", "尚无可用角色读数。")
    fields = ("strength", "dexterity", "intelligence", "luck", "ability_points")
    initial = {field: character[field] for field in fields}
    if character["ability_points"] == 0:
        return {"status": "unchanged", "before": initial, "after": initial, "allocated": 0, "remaining_ap": 0}
    bridge = BridgeClient(backend.root, backend.name, backend.instance)
    snapshot = bridge.snapshot()
    running = next((s for s in snapshot.get("scripts", []) if s["status"] == "running"), None)
    if running is not None:
        raise ClientError("input_busy", "已有Lua脚本正在控制角色，未发送加点请求。", {"script_id": running["id"]})
    scene = scene_context(snapshot)
    if scene["character_id"] != character["id"]:
        raise ClientError("character_changed", "提交期间角色已变化，停止操作。")
    from .ui import open_window

    open_window(backend, "stats")
    if scene_context(bridge.snapshot()) != scene:
        raise ClientError("character_changed", "打开属性窗口期间角色或场景已变化，未发送加点请求。")
    script = '''local requested = false
local function main(context)
    if requested then
        local status = context.game.player.status()
        if status.dispatched then return "done" end
        if status.input_action ~= "auto_ap" then error(status.reason or "auto_ap_not_dispatched") end
        return
    end
    requested = true
    local ok, reason = context.game.player.auto_ap(context.auto_ap_anchor.instance_id, context.auto_ap_anchor.character_id, context.auto_ap_anchor.scene_generation)
    if not ok then
        if reason == "unsupported" then error("auto_ap_unsupported") end
        error(reason or "auto_ap_rejected")
    end
end
'''
    try:
        request = bridge.run_script(code=compile_strategy(script, {}, scene, extra={"auto_ap_anchor": scene}), seconds=6, timeout=9)
    except ClientError as error:
        script_result = error.details.get("script")
        message = str(script_result.get("error", "")) if isinstance(script_result, dict) else ""
        if "input_busy" in message or "auto_ap_input_busy" in message:
            raise ClientError("input_busy", "已有其他脚本占用角色动作，未发送加点请求。", error.details) from error
        if any(reason in message for reason in ("auto_ap_job", "unsupported_capability", "auto_ap_unsupported")):
            raise ClientError("unsupported_capability", "当前客户端不支持该角色的自动加点。", error.details) from error
        raise ClientError("unknown", "自动加点结果未知，请观察角色属性，切勿重试。", error.details) from error
    deadline = time.monotonic() + 6
    after = before
    while time.monotonic() < deadline:
        try:
            after = backend.read("observe")
        except ClientError as error:
            raise ClientError("unknown", "加点后读取失败，结果未知，请观察角色属性，切勿重试。",
                              {"request": request, "observation_error": {"code": error.code,
                               "message": error.message, "details": error.details}}) from error
        updated = cast(JsonObject | None, after["character"])
        if updated is not None and after["native_values_valid"] is True:
            if updated["id"] != character["id"]:
                raise ClientError("character_changed", "确认期间角色已变化，停止操作。")
            increments = [cast(int, updated[f]) - cast(int, character[f]) for f in fields[:-1]]
            if (updated["ability_points"] == 0 and all(delta >= 0 for delta in increments)
                    and sum(increments) == character["ability_points"]):
                final = {field: updated[field] for field in fields}
                return {"status": "allocated", "before": initial, "after": final,
                        "allocated": character["ability_points"], "remaining_ap": 0}
        time.sleep(0.15)
    raise ClientError("unknown", "未确认实际加点结果，请观察角色属性，切勿重试。", {"state": after, "request": request})
