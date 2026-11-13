"""装载共享 Lua 策略；Python 只处理参数、生命周期和最终结果。"""

import math
from pathlib import Path
import tempfile
from typing import cast

from .backend import Backend
from .bridge import BridgeClient, BridgeSnapshot
from .errors import ClientError, JsonObject, JsonValue
from .strategies import compile_strategy, parse_options, read_strategy_file
from .strategy_scene import scene_context


def _lua_literal(value: JsonValue) -> str:
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        escaped = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
        return (
            '"' + "".join(escaped.get(char, f"\\{ord(char):03d}" if ord(char) < 32 else char) for char in value) + '"'
        )
    if isinstance(value, list):
        return "{" + ",".join(_lua_literal(item) for item in value) + "}"
    if isinstance(value, dict):
        return "{" + ",".join("[" + _lua_literal(key) + "]=" + _lua_literal(item) for key, item in value.items()) + "}"
    return repr(value)


def run_source(backend: Backend, source: str, seconds: float | None) -> JsonObject:
    if seconds is not None and (not math.isfinite(seconds) or not 0.05 <= seconds <= 600):
        raise ClientError("invalid_control_budget", "Lua控制预算须为0.05至600秒。")
    directory = backend.paths.state_directory
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".lua", prefix="control-", dir=directory, encoding="utf-8"
    ) as stream:
        stream.write(source)
        stream.flush()
        return BridgeClient(backend.root, backend.name, backend.instance).run_script(Path(stream.name), seconds=seconds)


def run_strategy(
    backend: Backend,
    name: str,
    options: JsonObject,
    seconds: float | None,
    *,
    context_state: BridgeSnapshot | None = None,
    context_extra: JsonObject | None = None,
) -> JsonObject:
    directory = Path(__file__).resolve().parents[2] / "shared/scripts"
    path = directory / (name + ".lua")
    source, metadata = read_strategy_file(path)
    if metadata is None:
        raise ClientError(
            "strategy_metadata_missing", "共享Lua文件未声明main(context)策略入口。", {"script": name, "path": str(path)}
        )
    declared = {option.name: option for option in metadata.options}
    unknown = options.keys() - declared.keys()
    if unknown:
        raise ClientError(
            "invalid_strategy_option", "共享Lua策略调用传入了未声明参数。", {"script": name, "options": sorted(unknown)}
        )
    arguments: list[str] = []
    for option in metadata.options:
        value = options.get(option.name)
        if value is None:
            continue
        if option.type == "boolean":
            if type(value) is not bool:
                raise ClientError("invalid_strategy_option", f"共享Lua策略布尔参数 {option.flag} 必须为布尔值。")
            arguments.append(option.flag if value else "--no-" + option.name.replace("_", "-"))
        else:
            if option.type == "int" and type(value) is not int:
                raise ClientError("invalid_strategy_option", f"共享Lua策略整数参数 {option.flag} 必须为整数。")
            if option.type == "number" and type(value) not in (int, float):
                raise ClientError("invalid_strategy_option", f"共享Lua策略数值参数 {option.flag} 必须为数字。")
            if option.type == "string" and not isinstance(value, str):
                raise ClientError("invalid_strategy_option", f"共享Lua策略文本参数 {option.flag} 必须为字符串。")
            arguments.extend((option.flag, str(value)))
    strategy_options = parse_options(metadata, arguments)
    state = (
        context_state
        if context_state is not None
        else BridgeClient(backend.root, backend.name, backend.instance).snapshot()
    )
    scene = scene_context(backend.root, state)
    report = run_source(backend, compile_strategy(source, strategy_options, scene, context_extra), seconds)
    return {**report, "strategy": name, "script_file": str(path)}


def _session_result(report: JsonObject) -> JsonObject | None:
    state = cast(JsonObject, report["last_state"])
    result = cast(JsonObject | None, state.get("action_result"))
    session = report.get("script_id")
    return result if result is not None and session is not None and result.get("session_id") == session else None


def action(
    backend: Backend, name: str, *, direction: str | None = None, seconds: float = 0.3, item_id: int | None = None
) -> JsonObject:
    if direction is not None and direction not in {"left", "right", "up", "down"}:
        raise ClientError("invalid_direction", "方向须为left/right/up/down。")
    if name == "face" and direction not in {"left", "right"}:
        raise ClientError("invalid_direction", "朝向须为left或right。")
    if not math.isfinite(seconds) or not 0.001 <= seconds <= 30:
        raise ClientError("invalid_action_duration", "单次动作时间须为0.001至30秒。")
    if name == "use_item" and (
        item_id is None
        or not 1 <= item_id <= 0x7FFFFFFF
        or item_id // 10000 != 200
        and not (backend.name == "headless" and item_id // 10000 == 201)
    ):
        raise ClientError("invalid_item", "原生用物支持200类药品；无头端另支持201类食品。")
    if name not in {"move", "face", "jump", "attack", "pickup", "use_item", "stop"}:
        raise ClientError("unsupported_capability", "当前没有这个共同动作。")
    if name == "move":
        arguments = _lua_literal(direction) + ", " + _lua_literal(seconds)
    elif name == "face":
        arguments = _lua_literal(direction)
    elif name == "use_item":
        arguments = _lua_literal(item_id)
    else:
        arguments = ""
    report = run_source(backend, "game." + name + "(" + arguments + ")\n", max(3, seconds + 2))
    state = cast(JsonObject, report["last_state"])
    return {**report, "action": name, "action_result": state.get("action_result"), "effect": "unknown"}


def press_keys(backend: Backend, keys: list[str], *, seconds: float = 0.15) -> JsonObject:
    if backend.name != "beidou":
        raise ClientError("unsupported_capability", "该客户端不提供原始按键接口；请使用语义动作。")
    if not keys or len(keys) > 16 or not math.isfinite(seconds) or not 0.001 <= seconds <= 30:
        raise ClientError("invalid_key_options", "按键须为1至16个，按住时间须为0.001至30秒。")
    report = run_source(backend, "game.press(" + _lua_literal(keys) + ", " + _lua_literal(seconds) + ")\n", seconds + 2)
    return {**report, "action": "key", "keys": keys, "effect": "unknown"}


def change_equipment(
    backend: Backend,
    source_slot: int,
    destination_slot: int,
    *,
    unequip: bool = False,
    item_id: int | None = None,
    seconds: float = 3,
    reference: str | None = None,
) -> JsonObject:
    if not math.isfinite(seconds) or not 0.001 <= seconds <= 30:
        raise ClientError("invalid_equipment_duration", "换装确认期限须为0.001至30秒。")
    name = "unequip" if unequip else "equip"
    if reference is not None and (not reference or len(reference.encode("utf-8")) > 128 or "\0" in reference):
        raise ClientError("invalid_equipment_reference", "装备对象引用须为1至128字节，且不含NUL。")
    source = ""
    if item_id is not None or reference is not None:
        inventory_list = "equipped" if unequip else "items"
        source = (
            'local inventory = game.observe("inventory")\n'
            'assert(inventory.status == "ok", "inventory_unavailable")\n'
            "local selected\n"
            f"for _, item in ipairs(inventory.data.{inventory_list}) do if item.slot == {source_slot} "
            "and item.inventory_type == 1 then selected = item; break end end\n"
        )
        if item_id is not None:
            source += f'assert(selected and selected.item_id == {item_id}, "equipment_source_changed")\n'
    if reference is not None:
        source += (
            "assert(selected and selected.equipment and selected.equipment.object_ref == "
            + _lua_literal(reference)
            + ', "equipment_reference_expired")\n'
        )
    arguments = f"{source_slot}, {destination_slot}, {_lua_literal(seconds)}"
    if reference is not None:
        arguments += ", " + _lua_literal(reference)
    source += f"game.{name}({arguments})\n"
    report = run_source(backend, source, seconds + 2)
    state = cast(JsonObject, report["last_state"])
    result = _session_result(report)
    confirmed = report["status"] == "completed" and result is not None and result.get("effect") == "confirmed"
    projected: JsonObject = {
        **report,
        "action": name,
        "source_slot": source_slot,
        "destination_slot": destination_slot,
        "item_id": item_id,
        "action_result": result,
        "effect": result.get("effect", "unknown") if result else "unknown",
        "confirmed": confirmed,
    }
    if report["status"] == "completed" and not confirmed:
        raise ClientError("equipment_change_unconfirmed", "本次换装实际槽位变化未确认，未重试。", projected)
    return projected


def window(backend: Backend, name: str, opened: bool = True) -> JsonObject:
    if backend.name != "beidou" or name not in {"inventory", "stats", "skills", "game"}:
        raise ClientError("unsupported_capability", "仅GUI提供已识别窗口与游戏焦点入口。")
    source = "game.focus()\n" if name == "game" else f"game.window({_lua_literal(name)}, {_lua_literal(opened)})\n"
    report = run_source(backend, source, 5)
    state = cast(JsonObject, report["last_state"])
    result = _session_result(report)
    observed = cast(JsonObject | None, result.get("ui")) if result else None
    confirmed = (
        report["status"] == "completed"
        and result is not None
        and result.get("effect") == "confirmed"
        and observed is not None
        and observed.get("window") == name
        and (observed.get("game_focused") is True if name == "game" else observed.get("open") is opened)
    )
    projected: JsonObject = {**report, "action_result": result, "confirmed": confirmed, "ui": observed}
    if report["status"] == "completed" and not confirmed:
        raise ClientError("ui_not_confirmed", "窗口或焦点未确认，未重复发送输入。", projected)
    if confirmed and name == "game":
        projected.update(focused=True, changed=bool(result and result.get("dispatched")))
    elif confirmed and not opened:
        projected.update(
            window=name,
            closed=True,
            already_closed=not observed.get("instance_ref"),
            changed=bool(result and result.get("dispatched")),
        )
    elif confirmed:
        observed_ui = backend.read("ui")
        matches = [
            entry
            for entry in cast(list[JsonObject], observed_ui["windows"])
            if entry.get("instance_ref") == observed.get("instance_ref")
        ]
        if len(matches) != 1:
            raise ClientError("ui_window_changed", "窗口已变化，不能返回旧对象。", projected)
        projected.update(matches[0])
    return projected


def allocate(backend: Backend, target: str | int, count: int) -> JsonObject:
    skill = isinstance(target, int)
    if (
        not 1 <= count <= 100
        or (skill and not 1 <= target <= 0x7FFFFFFF)
        or (not skill and target not in {"strength", "dexterity", "intelligence", "luck"})
    ):
        raise ClientError("invalid_allocation", "指定基础属性或正32位技能ID，以及1至100点。")
    name = "allocate_sp" if skill else "allocate_ap"
    report = run_source(
        backend,
        f"game.{name}({_lua_literal(target)}, {count})\n",
        min(600, count * 1.2 + (10 if backend.name == "beidou" else 3)),
    )
    state = cast(JsonObject, report["last_state"])
    result = _session_result(report)
    allocation = cast(JsonObject | None, result.get("allocation")) if result else None
    matches = (
        allocation is not None
        and allocation.get("kind") == ("sp" if skill else "ap")
        and allocation.get("requested") == count
        and allocation.get("skill_id" if skill else "stat") == target
    )
    confirmed = (
        report["status"] == "completed"
        and matches
        and result is not None
        and result.get("effect") == "confirmed"
        and allocation is not None
        and allocation.get("allocated") == count
    )
    projected: JsonObject = {
        **report,
        "action": name,
        "allocation": allocation,
        "confirmed": confirmed,
        "action_result": result,
    }
    if report["status"] == "completed" and not confirmed:
        raise ClientError("allocation_unconfirmed", "分配未全部确认，已停止；先观察实际点数与目标，不重试。", projected)
    return projected


def skill(backend: Backend, skill_id: int) -> JsonObject:
    if not 1 <= skill_id <= 0x7FFFFFFF:
        raise ClientError("invalid_skill", "技能ID须为正32位整数。")
    capabilities = BridgeClient(backend.root, backend.name, backend.instance).snapshot().get("capabilities")
    if capabilities is None or capabilities.get("skill") is not True:
        raise ClientError("unsupported_capability", "当前原生客户端未声明支持技能调用。")
    report = run_source(backend, "game.skill(" + str(skill_id) + ")\n", 3)
    state = cast(JsonObject, report["last_state"])
    observed = cast(JsonObject | None, state.get("last_skill"))
    if report["status"] == "completed" and (observed is None or observed["skill_id"] != skill_id):
        raise ClientError("native_skill_result_unavailable", "Lua已返回，但未确认本次技能的原生返回值。", report)
    result = observed if report["status"] == "completed" else None
    return {
        **report,
        "skill_id": skill_id,
        "native_result": result["native_result"] if result is not None else None,
        "dispatched": result.get("dispatched") if result is not None else None,
        "skill_reason": result.get("reason") if result is not None else None,
        "effect": "unknown",
    }


def move_to_x(backend: Backend, x: int, *, seconds: float = 20, tolerance: int = 8) -> JsonObject:
    if not math.isfinite(seconds) or not 1 <= seconds <= 60 or not 1 <= tolerance <= 50:
        raise ClientError("invalid_travel_options", "移动预算须为1至60秒，容差须为1至50。")
    initial = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
    if not initial["ready"] or initial["position"] is None or initial["character"] is None:
        raise ClientError("not_ready", "角色状态尚未就绪，未开始移动。")
    options: JsonObject = {
        "x": x,
        "tolerance": tolerance,
        "budget_seconds": seconds,
        "y_tolerance": 45,
        "min_hp_ratio": 0,
    }
    report = run_strategy(backend, "travel/move_to", options, seconds + 1, context_state=initial)
    final = cast(JsonObject, report["last_state"])
    if report["status"] == "completed":
        position = cast(JsonObject | None, final["position"])
        character = cast(JsonObject | None, final["character"])
        if (
            final["instance_id"] != initial["instance_id"]
            or final["map_id"] != initial["map_id"]
            or final["scene_generation"] != initial["scene_generation"]
            or character is None
            or character["id"] != initial["character"]["id"]
            or position is None
            or abs(cast(float, position["x"]) - x) > tolerance
        ):
            raise ClientError("travel_not_confirmed", "Lua已返回，但最终位置或场景未确认到达。", {"after": final})
    return {
        **report,
        "status": "arrived" if report["status"] == "completed" else report["status"],
        "action": "move",
        "target_x": x,
        "tolerance": tolerance,
        "before": {"map_id": initial["map_id"], "position": initial["position"]},
        "after": final,
    }
