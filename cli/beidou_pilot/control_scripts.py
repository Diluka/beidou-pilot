"""装载共享 Lua 策略；Python 只处理参数、生命周期和最终结果。"""

import math
from pathlib import Path
import tempfile
from typing import cast

from .backend import Backend
from .bridge import BridgeClient
from .errors import ClientError, JsonObject, JsonValue


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


def run_strategy(backend: Backend, name: str, options: JsonObject, seconds: float | None) -> JsonObject:
    directory = Path(__file__).resolve().parents[2] / "shared/scripts"
    path = directory / (name + ".lua")
    try:
        common = (directory / "travel/_common.lua").read_text(encoding="utf-8") if name.startswith("travel/") else ""
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ClientError(
            "strategy_script_unavailable",
            "无法装载共享Lua策略。",
            {"script": name, "path": str(path), "reason": str(error)},
        ) from error
    report = run_source(backend, "local options = " + _lua_literal(options) + "\n" + common + "\n" + source, seconds)
    return {**report, "strategy": name, "script_file": str(path)}


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
) -> JsonObject:
    if not math.isfinite(seconds) or not 0.001 <= seconds <= 30:
        raise ClientError("invalid_equipment_duration", "换装确认期限须为0.001至30秒。")
    name = "unequip" if unequip else "equip"
    source = ""
    if item_id is not None:
        source = (
            'local inventory = game.observe("inventory")\n'
            'assert(inventory.status == "ok", "inventory_unavailable")\n'
            "local selected\n"
            f"for _, item in ipairs(inventory.data.items) do if item.slot == {source_slot} "
            "and item.inventory_type == 1 then selected = item; break end end\n"
            f'assert(selected and selected.item_id == {item_id}, "equipment_source_changed")\n'
        )
    source += f"game.{name}({source_slot}, {destination_slot}, {_lua_literal(seconds)})\n"
    report = run_source(backend, source, seconds + 2)
    state = cast(JsonObject, report["last_state"])
    result = cast(JsonObject, state["action_result"])
    confirmed = report["status"] == "completed" and result["effect"] == "confirmed"
    projected: JsonObject = {
        **report,
        "action": name,
        "source_slot": source_slot,
        "destination_slot": destination_slot,
        "item_id": item_id,
        "action_result": result,
        "effect": result["effect"],
        "confirmed": confirmed,
    }
    if report["status"] == "completed" and not confirmed:
        raise ClientError("equipment_change_unconfirmed", "本次换装实际槽位变化未确认，未重试。", projected)
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
        "seconds": seconds,
        "y_tolerance": 45,
        "min_hp_ratio": 0,
        "instance_id": initial["instance_id"],
        "character_id": initial["character"]["id"],
        "map_id": initial["map_id"],
        "scene_generation": initial["scene_generation"],
    }
    report = run_strategy(backend, "travel/move_to", options, seconds + 1)
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


def fight(
    backend: Backend,
    *,
    mob_id: int,
    seconds: float,
    stop_level: int,
    floor_y: int,
    bounds: tuple[int, int],
    retreat_x: int,
    loot: bool,
) -> JsonObject:
    if (
        not math.isfinite(seconds)
        or not 5 <= seconds <= 300
        or bounds[0] >= bounds[1]
        or not bounds[0] <= retreat_x <= bounds[1]
    ):
        raise ClientError("invalid_fight_options", "战斗预算5至300秒，范围须递增且含撤退点。")
    report = run_strategy(
        backend,
        "combat/fight",
        {
            "mob_id": mob_id,
            "seconds": seconds,
            "stop_level": stop_level,
            "floor_y": floor_y,
            "min_x": bounds[0],
            "max_x": bounds[1],
            "retreat_x": retreat_x,
            "loot": loot,
        },
        seconds + 1,
    )
    return {
        **report,
        "action": "fight",
        "effect": "inspect_final_state",
        "requested_level": stop_level,
        "state": report["last_state"],
    }
