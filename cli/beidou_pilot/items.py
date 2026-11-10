"""原生Lua执行普通恢复品，GUI处理其余支持物品，并核对结果。"""

import math
import time
from typing import TypedDict, cast

from .backend import Backend, ClientError, JsonObject
from .catalog import Catalog
from .engines.inventory import InventoryItem, InventorySnapshot
from .engines.ui import UIWindow
from .stats import Character, read_character
from .ui import click_window, close_window, focus_game, open_window, read_ui


# 以 CUIItem 原点为基准；已用普通开窗和现存截图校准。
BAG_EQUIP_TAB = (19, 34)
BAG_USE_TAB = (54, 34)


class _Position(TypedDict):
    x: int
    y: int


class _UseObservation(TypedDict):
    map_id: int | None
    position: _Position | None
    native_values_valid: bool
    character: Character | None


def _select_slot(backend: Backend, inventory_type: int, slot: int, *, window: UIWindow | None = None,
                 deadline: float | None = None) -> UIWindow | None:
    if deadline is not None and time.monotonic() >= deadline:
        return None
    if window is None:
        window = open_window(backend, "inventory")
        if deadline is not None and time.monotonic() >= deadline:
            return None
        click_window(backend, window, *(BAG_EQUIP_TAB if inventory_type == 1 else BAG_USE_TAB))
        window = next(item for item in read_ui(backend)["windows"] if item["address"] == window["address"])
    view = window["inventory"]
    if view is None or view["selected_type"] != inventory_type:
        raise ClientError("inventory_tab_not_confirmed", "未确认背包切换到目标类型。")
    if view["expanded"]:
        raise ClientError("inventory_layout_unverified", "当前是展开背包，请先切回普通背包。")
    while not view["first_slot"] <= slot < view["first_slot"] + 24:
        direction = "up" if slot < view["first_slot"] else "down"
        previous_first = view["first_slot"]
        if deadline is not None and time.monotonic() >= deadline:
            return None
        click_window(backend, window, 80, 90)
        if deadline is not None and time.monotonic() >= deadline:
            return None
        backend.read("desktop", "scroll", direction, "--ticks", "1")
        window = next(item for item in read_ui(backend)["windows"] if item["address"] == window["address"])
        view = window["inventory"]
        if (view is None or view["selected_type"] != inventory_type
                or (direction == "down" and view["first_slot"] <= previous_first)
                or (direction == "up" and view["first_slot"] >= previous_first)):
            raise ClientError("inventory_scroll_not_confirmed", "背包滚动未确认，已停止物品操作。")
    index = slot - view["first_slot"]
    if deadline is not None and time.monotonic() >= deadline:
        return None
    # 客户端自身的普通背包槽位命中矩形中心；不依赖桌面偏移。
    click_window(backend, window, 24 + index % 4 * 36, 66 + index // 4 * 34, double=True)
    return window


def read_inventory(backend: Backend, inventory_type: int, *, equipped: bool = False) -> InventorySnapshot:
    arguments = ["--type", str(inventory_type)]
    if equipped:
        arguments.append("--equipped")
    snapshot = cast(InventorySnapshot, backend.read("inventory", *arguments))
    if snapshot["native_values_valid"] is not True or snapshot["unavailable"]:
        raise ClientError("inventory_unavailable", "当前背包读数不可用。",
                          {"unavailable": snapshot["unavailable"]})
    return snapshot


def equip(backend: Backend, item_id: int) -> JsonObject:
    before = read_inventory(backend, 1, equipped=True)
    wearing = next((item for item in before["equipped"] if item["item_id"] == item_id), None)
    if wearing:
        return {"item_id": item_id, "equipped": True, "changed": False, "slot": wearing["slot"]}
    item = next((item for item in before["items"] if item["item_id"] == item_id), None)
    if item is None:
        raise ClientError("item_missing", "装备背包中没有该物品。", {"item_id": item_id})
    slot = item["slot"]
    _select_slot(backend, 1, slot)
    deadline = time.monotonic() + 1.2
    after = read_inventory(backend, 1, equipped=True)
    wearing = next((entry for entry in after["equipped"] if entry["item_id"] == item_id), None)
    while wearing is None and time.monotonic() < deadline:
        time.sleep(0.1)
        after = read_inventory(backend, 1, equipped=True)
        wearing = next((entry for entry in after["equipped"] if entry["item_id"] == item_id), None)
    if wearing is None:
        raise ClientError("equip_not_confirmed", "双击后未在已装备负槽位确认该物品。",
                          {"item_id": item_id, "bag_slot": slot,
                           "requirements": Catalog(backend.root).item(item_id)["requirements"]})
    return {"item_id": item_id, "equipped": True, "changed": True,
            "bag_slot": slot, "slot": wearing["slot"]}


def use(backend: Backend, item_id: int, count: int = 1, until_hp: int | None = None, *,
        until_mp: int | None = None, seconds: float | None = None, deadline: float | None = None) -> JsonObject:
    """期限停止后续用药；已派发动作仍完成读回与成功收尾，不重放未知效果。"""
    started = time.monotonic()
    if count < 1 or count > 100:
        raise ClientError("invalid_count", "单次使用数量须为 1 至 100。")
    if deadline is not None and not math.isfinite(deadline):
        raise ClientError("invalid_budget", "用药截止时间须为有限的 monotonic 时间。")
    if seconds is not None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ClientError("invalid_budget", "用药时限须为有限的非负秒数。")
        deadline = min(deadline, started + seconds) if deadline is not None else started + seconds
    before_character = read_character(backend)
    if until_hp is not None and not 1 <= until_hp <= before_character["max_hp"]:
        raise ClientError("invalid_hp_target", "目标 HP 须在 1 与当前最大 HP 之间。")
    if until_mp is not None and not 1 <= until_mp <= before_character["max_mp"]:
        raise ClientError("invalid_mp_target", "目标 MP 须在 1 与当前最大 MP 之间。")
    catalog = Catalog(backend.root)
    specification = cast(JsonObject, catalog.item(item_id)["spec"])
    hp_amount, hp_ratio = specification.get("hp", 0), specification.get("hpR", 0)
    mp_amount, mp_ratio = specification.get("mp", 0), specification.get("mpR", 0)
    heals_hp = any(isinstance(value, (int, float)) and value > 0 for value in (hp_amount, hp_ratio))
    heals_mp = any(isinstance(value, (int, float)) and value > 0 for value in (mp_amount, mp_ratio))
    move_to = specification.get("moveTo")
    teleports = type(move_to) is int and move_to > 0
    native_potion = item_id // 10000 == 200
    if backend.name == "headless" and not native_potion:
        raise ClientError("unsupported_capability", "无头端仅支持普通200类HP/MP药品。", {"item_id": item_id})
    if not heals_hp and not heals_mp and not teleports and not native_potion:
        raise ClientError("consumable_not_supported", "当前 use 支持 HP/MP 恢复药与 moveTo 回城/传送卷。",
                          {"item_id": item_id, "spec": specification})
    teleport_before = None
    teleport_after = None
    static_destination = None
    static_destination_source = None
    if teleports:
        if count != 1 or until_hp is not None or until_mp is not None:
            raise ClientError("invalid_teleport_options", "回城/传送卷每次使用 1 张，不接受 HP/MP 目标；抵达后重新观察。")
        observed = backend.read("observe")
        teleport_before = cast(_UseObservation, observed)
        if (teleport_before["native_values_valid"] is not True or teleport_before["map_id"] is None
                or teleport_before["position"] is None):
            raise ClientError("teleport_origin_unavailable", "使用传送卷前的地图或位置不可用，未派发输入。",
                              {"observed": observed})
        if move_to == 999999999:
            map_info = cast(JsonObject, catalog.map(teleport_before["map_id"]).get("info", {}))
            static_destination = map_info.get("returnMap")
            static_destination_source = "local-wz-map.returnMap"
        else:
            static_destination = move_to
            static_destination_source = "local-wz-item.spec.moveTo"
    if until_hp is not None and not heals_hp:
        raise ClientError("healing_metadata_missing", "本地 WZ 未说明该物品恢复 HP，无法按目标 HP 连续使用。")
    if until_mp is not None and not heals_mp:
        raise ClientError("healing_metadata_missing", "本地 WZ 未说明该物品恢复 MP，无法按目标 MP 连续使用。")
    if native_potion:
        from .control_scripts import run_strategy

        before_inventory = read_inventory(backend, 2)
        initial_quantities = [entry["quantity"] for entry in before_inventory["items"]
                              if entry["item_id"] == item_id]
        if any(value is None for value in initial_quantities):
            raise ClientError("inventory_unavailable", "该物品数量未知。", {"item_id": item_id})
        quantity_before = sum(cast(list[int], initial_quantities))
        budget = float(count * 2 + 2)
        if deadline is not None:
            budget = max(0, min(budget, deadline - time.monotonic()))
        game_focused = None
        if backend.name == "beidou":
            game_focused = False
            if budget > 0:
                focus_game(backend)
                game_focused = True
                if deadline is not None:
                    budget = max(0, min(budget, deadline - time.monotonic()))
        report = run_strategy(backend, "recovery/recover", {
            "item_id": item_id, "count": count, "seconds": budget,
            "target_hp": until_hp, "target_mp": until_mp,
            "heals_hp": heals_hp, "heals_mp": heals_mp,
            "healing_known": heals_hp or heals_mp,
        }, min(600, max(3, budget + 2)))
        final = cast(JsonObject, report["last_state"])
        after_character = cast(Character | None, final.get("character"))
        final_inventory = cast(list[InventoryItem] | None, final.get("inventory"))
        final_quantities = None if final_inventory is None else [
            entry["quantity"] for entry in final_inventory if entry["item_id"] == item_id]
        quantity_after = (sum(cast(list[int], final_quantities))
                          if final_quantities is not None and all(value is not None for value in final_quantities)
                          else None)
        consumed = None if quantity_after is None else quantity_before - quantity_after
        used = consumed if consumed is not None and 0 <= consumed <= count else None
        hp_after = after_character["hp"] if after_character is not None else None
        mp_after = after_character["mp"] if after_character is not None else None
        target_reached = ((until_hp is None or hp_after is not None and hp_after >= until_hp)
                          and (until_mp is None or mp_after is not None and mp_after >= until_mp)) \
            if until_hp is not None or until_mp is not None else None
        if report["status"] != "completed":
            reason = report.get("reason")
        elif target_reached:
            reason = "target_reached"
        elif after_character is not None and (
                ((heals_hp or heals_mp) and (not heals_hp or after_character["hp"] >= after_character["max_hp"])
                 and (not heals_mp or after_character["mp"] >= after_character["max_mp"]))
                or (not heals_hp and not heals_mp and after_character["hp"] >= after_character["max_hp"]
                    and after_character["mp"] >= after_character["max_mp"])):
            reason = "resources_full"
        elif used == count:
            reason = "count_reached"
        elif quantity_after == 0:
            reason = "stock_exhausted"
        else:
            reason = "time_budget"
        return {**report, "item_id": item_id, "used": used,
                "quantity_before": quantity_before, "quantity_after": quantity_after,
                "hp_before": before_character["hp"], "hp_after": hp_after,
                "mp_before": before_character["mp"], "mp_after": mp_after,
                "target_hp": until_hp, "target_mp": until_mp, "target_reached": target_reached,
                "reason": reason, "effect": "recovery",
                "effect_confirmed": used > 0 if report["status"] == "completed" and used is not None else None,
                "input_method": "native_lua", "key": None,
                "inventory_opened": False, "inventory_closed": False,
                "game_focused": game_focused,
                "cleanup_pending": None, "elapsed_seconds": round(time.monotonic() - started, 3)}
    character = before_character
    used = 0
    first_quantity = None
    final_quantity = None
    inventory = None
    window = None
    input_method = None
    inventory_was_open = None
    inventory_touched = False
    inventory_opened = False
    inventory_closed = False
    game_focused = None
    cleanup_pending = None
    reason = "count_reached"
    for _ in range(count):
        if (until_hp is not None or until_mp is not None) \
                and (until_hp is None or character["hp"] >= until_hp) \
                and (until_mp is None or character["mp"] >= until_mp):
            reason = "target_reached"
            break
        if (heals_hp or heals_mp) and (not heals_hp or character["hp"] >= character["max_hp"]) \
                and (not heals_mp or character["mp"] >= character["max_mp"]):
            reason = "resources_full"
            break
        if deadline is not None and time.monotonic() >= deadline:
            reason = "time_budget"
            break
        if inventory is None:
            inventory = read_inventory(backend, 2)
        matches = [item for item in inventory["items"] if item["item_id"] == item_id]
        if not matches:
            if used:
                reason = "stock_exhausted"
                break
            raise ClientError("item_missing", "消费背包中没有该物品。", {"item_id": item_id})
        quantities = [item["quantity"] for item in matches]
        if any(quantity is None for quantity in quantities):
            raise ClientError("inventory_unavailable", "该物品数量未知。", {"item_id": item_id})
        quantity = sum(cast(list[int], quantities))
        if first_quantity is None:
            first_quantity = quantity
            final_quantity = quantity
        item = matches[0]
        slot = item["slot"]
        if input_method is None:
            input_method = "inventory"
            inventory_was_open = any(entry["type_name"] == "CUIItem" for entry in read_ui(backend)["windows"])
        if deadline is not None and time.monotonic() >= deadline:
            reason = "time_budget"
            break
        hp_needed = heals_hp and character["hp"] < character["max_hp"] \
            and (until_hp is None or character["hp"] < until_hp)
        mp_needed = heals_mp and character["mp"] < character["max_mp"] \
            and (until_mp is None or character["mp"] < until_mp)
        inventory_touched = True
        game_focused = False
        window = _select_slot(backend, 2, slot, window=window, deadline=deadline)
        if window is None:
            reason = "time_budget"
            break
        inventory_opened = not inventory_was_open
        effect_context: JsonObject = {
            "input_method": input_method, "inventory_opened": inventory_opened,
            "inventory_closed": False, "game_focused": game_focused,
        }
        confirmation_deadline = time.monotonic() + (10 if teleports else 1.2)
        after_character = character
        quantity_available = False
        teleport_confirmed = False
        while True:
            if teleports:
                # 正常转场可能暂时清空角色引用；只等待读数恢复，不重放消费。
                after_inventory = cast(InventorySnapshot, backend.read("inventory", "--type", "2"))
            else:
                after_inventory = read_inventory(backend, 2)
            after_quantities = [entry["quantity"] for entry in after_inventory["items"]
                                if entry["item_id"] == item_id]
            quantities_known = (after_inventory["native_values_valid"] is True and not after_inventory["unavailable"]
                                and all(value is not None for value in after_quantities))
            if not quantities_known and not teleports:
                raise ClientError("inventory_unavailable", "使用后的物品数量未知。",
                                  {"item_id": item_id, "used": used, **effect_context})
            if quantities_known:
                final_quantity = sum(cast(list[int], after_quantities))
                quantity_available = True
            if teleports:
                after_observation = cast(_UseObservation, backend.read("observe"))
                if (after_observation["native_values_valid"] is True
                        and after_observation["map_id"] is not None and after_observation["position"] is not None
                        and after_observation["character"] is not None):
                    if after_observation["character"]["id"] != before_character["id"]:
                        raise ClientError("teleport_character_changed", "转场后的角色与使用传送卷的角色不符，已停止。",
                                          {"character_before": before_character["id"],
                                           "character_after": after_observation["character"]["id"], **effect_context})
                    teleport_after = after_observation
                    after_character = after_observation["character"]
                    teleport_confirmed = (after_observation["map_id"] != teleport_before["map_id"]
                                          or after_observation["position"] != teleport_before["position"])
            else:
                after_character = read_character(backend)
            hp_confirmed = not hp_needed or after_character["hp"] > character["hp"]
            mp_confirmed = not mp_needed or after_character["mp"] > character["mp"]
            if (quantity_available and final_quantity < quantity and hp_confirmed and mp_confirmed
                    and (not teleports or teleport_confirmed)) or time.monotonic() >= confirmation_deadline:
                break
            time.sleep(0.1)
        if final_quantity != quantity - 1:
            raise ClientError("use_not_confirmed", "使用后未确认物品数量减少 1。",
                              {"item_id": item_id, "quantity_before": quantity,
                               "quantity_after": final_quantity if quantity_available else None, "used": used,
                               "hp_before": character["hp"], "hp_after": after_character["hp"],
                               "map_after": teleport_after["map_id"] if teleport_after else None,
                               "position_after": cast(JsonObject, teleport_after["position"]) if teleport_after else None,
                               **effect_context})
        used += 1
        if teleports and not teleport_confirmed:
            raise ClientError("teleport_not_confirmed", "传送卷已消耗，但未确认实际地图或位置变化；保留现场，不重放。",
                              {"item_id": item_id, "used": used, "quantity_before": quantity,
                               "quantity_after": final_quantity, "map_before": teleport_before["map_id"],
                               "position_before": cast(JsonObject, teleport_before["position"]),
                               "map_after": teleport_after["map_id"] if teleport_after else None,
                               "position_after": cast(JsonObject, teleport_after["position"]) if teleport_after else None,
                               "move_to": move_to, "static_destination_map": static_destination, **effect_context})
        if hp_needed and after_character["hp"] <= character["hp"]:
            raise ClientError("healing_not_confirmed", "物品已经消耗，但 HP 未增长，已停止继续用药。",
                              {"item_id": item_id, "used": used, "hp_before": character["hp"],
                               "hp_after": after_character["hp"], "quantity_after": final_quantity, **effect_context})
        if mp_needed and after_character["mp"] <= character["mp"]:
            raise ClientError("healing_not_confirmed", "物品已经消耗，但 MP 未增长，已停止继续用药。",
                              {"item_id": item_id, "used": used, "mp_before": character["mp"],
                               "mp_after": after_character["mp"], "quantity_after": final_quantity, **effect_context})
        character = after_character
        inventory = after_inventory
        if teleports:
            reason = "teleport_confirmed"
            break
    if teleports and used:
        landing_ui = read_ui(backend)
        if inventory_opened and not any(entry["type_name"] == "CUIItem" for entry in landing_ui["windows"]):
            inventory_closed = True
        if any(landing_ui["dialog"][key] is not False for key in (
            "script_dialog_open", "focused_talk_dialog_open", "registered_talk_dialog_open",
        )):
            cleanup_pending = "landing_dialog"
            game_focused = False
    if cleanup_pending is None and ((input_method == "inventory" and inventory_touched) or (teleports and used)):
        if input_method == "inventory" and not inventory_was_open:
            inventory_opened = window is not None or any(
                entry["type_name"] == "CUIItem" for entry in read_ui(backend)["windows"])
        if inventory_opened and not inventory_closed:
            inventory_closed = bool(close_window(backend, "inventory")["closed"])
        focus_game(backend)
        game_focused = True
    target_reached = ((until_hp is None or character["hp"] >= until_hp)
                      and (until_mp is None or character["mp"] >= until_mp)) \
        if until_hp is not None or until_mp is not None else None
    if target_reached:
        reason = "target_reached"
    return {"item_id": item_id, "used": used, "quantity_before": first_quantity,
            "quantity_after": final_quantity, "hp_before": before_character["hp"],
            "hp_after": character["hp"], "mp_before": before_character["mp"],
            "mp_after": character["mp"], "target_hp": until_hp, "target_mp": until_mp,
            "target_reached": target_reached, "reason": reason,
            "effect": "teleport" if teleports else "recovery", "effect_confirmed": used > 0,
            "move_to": move_to,
            "static_destination_map": static_destination, "static_destination_runtime_authority": False,
            "static_destination_source": static_destination_source,
            "map_before": teleport_before["map_id"] if teleport_before else None,
            "position_before": cast(JsonObject, teleport_before["position"]) if teleport_before else None,
            "map_after": teleport_after["map_id"] if teleport_after else None,
            "position_after": cast(JsonObject, teleport_after["position"]) if teleport_after else None,
            "input_method": input_method, "key": None,
            "inventory_opened": inventory_opened, "inventory_closed": inventory_closed,
            "game_focused": game_focused, "cleanup_pending": cleanup_pending,
            "elapsed_seconds": round(time.monotonic() - started, 3)}
