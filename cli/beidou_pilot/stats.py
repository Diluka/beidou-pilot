"""普通属性和技能窗口操作；用角色剩余点数核对每次分配。"""

import time
from typing import Literal, TypedDict, cast

from .backend import Backend, ClientError, JsonObject
from .engines.character import CharacterSnapshot as LearnedSnapshot
from .ui import click_control, click_window, open_window, read_ui


class Character(TypedDict):
    id: int
    level: int
    job: int
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    strength: int
    dexterity: int
    intelligence: int
    luck: int
    ability_points: int
    skill_points: int


class CharacterSnapshot(TypedDict):
    character: Character | None
    native_values_valid: bool
    unavailable: list[str]


Ability = Literal["strength", "dexterity", "intelligence", "luck"]
AP_BUTTONS: dict[Ability, int] = {
    "strength": 2002, "dexterity": 2003,
    "intelligence": 2004, "luck": 2005,
}


def read_character(backend: Backend) -> Character:
    snapshot = cast(CharacterSnapshot, backend.read("observe"))
    if snapshot["native_values_valid"] is not True or snapshot["character"] is None:
        raise ClientError("character_unavailable", "当前角色属性读数不可用。",
                          {"unavailable": snapshot["unavailable"]})
    return snapshot["character"]


def allocate_ap(backend: Backend, stat: Ability, count: int = 1) -> JsonObject:
    if stat not in AP_BUTTONS or not 1 <= count <= 100:
        raise ClientError("invalid_allocation", "选择基础属性，并指定 1 至 100 点。")
    before = read_character(backend)
    if before["ability_points"] < count:
        raise ClientError("insufficient_ap", "剩余 AP 不足。", {"available": before["ability_points"], "requested": count})
    current = before
    for allocated in range(count):
        window = open_window(backend, "stats")
        click_control(backend, window, AP_BUTTONS[stat])
        deadline = time.monotonic() + 1.2
        after = read_character(backend)
        while (after["ability_points"] != current["ability_points"] - 1 or after[stat] != current[stat] + 1) \
                and time.monotonic() < deadline:
            time.sleep(0.1)
            after = read_character(backend)
        if after["ability_points"] != current["ability_points"] - 1 or after[stat] != current[stat] + 1:
            raise ClientError("ap_not_confirmed", "本次 AP 分配未同时确认剩余点数与目标属性变化，已停止。",
                              {"stat": stat, "allocated": allocated, "ap_before": current["ability_points"],
                               "ap_after": after["ability_points"], "value_before": current[stat], "value_after": after[stat]})
        current = after
    return {"stat": stat, "allocated": count, "value_before": before[stat],
            "value_after": current[stat], "ap_before": before["ability_points"], "ap_after": current["ability_points"]}


def allocate_sp(backend: Backend, skill_id: int, count: int = 1) -> JsonObject:
    if not 1 <= count <= 100:
        raise ClientError("invalid_count", "单次技能加点须为 1 至 100。")
    before = read_character(backend)
    if before["skill_points"] < count:
        raise ClientError("insufficient_sp", "剩余 SP 不足。", {"available": before["skill_points"], "requested": count})
    learned = cast(LearnedSnapshot, backend.read("character"))
    if not learned["skills_complete"]:
        raise ClientError("skills_unavailable", "当前已学技能记录不完整，无法核对技能加点。")
    original_level = learned["skills"].get(str(skill_id), {"level": 0, "master_level": None})["level"]
    current = before
    current_level = original_level
    for allocated in range(count):
        window = open_window(backend, "skills")
        view = window["skills"]
        if view is None:
            raise ClientError("skills_ui_unavailable", "当前窗口没有可确认的技能列表。")
        if skill_id not in view["ids"]:
            tab_count = view["tab_count"]
            for tab in range(tab_count):
                if tab == view["selected_tab"]:
                    continue
                click_window(backend, window, 19 + tab * 35, 34)
                window = next(item for item in read_ui(backend)["windows"] if item["address"] == window["address"])
                view = window["skills"]
                if view is None:
                    raise ClientError("skills_ui_unavailable", "职业页切换后技能列表不可用。")
                if skill_id in view["ids"]:
                    break
        if skill_id not in view["ids"]:
            raise ClientError("skill_not_in_ui", "当前角色的技能页没有该技能。", {"skill_id": skill_id})
        index = view["ids"].index(skill_id)
        for _ in range(len(view["ids"])):
            if 0 <= index - view["first_index"] < 4:
                break
            direction = "down" if index >= view["first_index"] + 4 else "up"
            previous_first = view["first_index"]
            # 先把鼠标放到技能文字区，再滚动；加点前重新读取真实首索引。
            click_window(backend, window, 100, 130)
            backend.read("desktop", "scroll", direction, "--ticks", "1")
            window = next(item for item in read_ui(backend)["windows"] if item["address"] == window["address"])
            view = window["skills"]
            if view is None or view["first_index"] == previous_first:
                raise ClientError("skill_scroll_not_confirmed", "技能列表滚动未确认，已停止加点。")
            if skill_id not in view["ids"]:
                raise ClientError("skills_ui_changed", "滚动期间目标技能离开当前技能组。")
            index = view["ids"].index(skill_id)
        row = index - view["first_index"]
        if not 0 <= row < 4:
            raise ClientError("skill_not_visible", "目标技能尚未滚入可见行。", {"skill_id": skill_id})
        click_control(backend, window, 2010 + row)
        deadline = time.monotonic() + 1.2
        while True:
            after = read_character(backend)
            learned = cast(LearnedSnapshot, backend.read("character"))
            if not learned["skills_complete"]:
                raise ClientError("skills_unavailable", "技能加点后的已学技能读数不完整。")
            level = learned["skills"].get(str(skill_id), {"level": 0, "master_level": None})["level"]
            if ((after["skill_points"] == current["skill_points"] - 1 and level == current_level + 1)
                    or time.monotonic() >= deadline):
                break
            time.sleep(0.1)
        if after["skill_points"] != current["skill_points"] - 1 or level != current_level + 1:
            raise ClientError("sp_not_confirmed", "未同时确认剩余 SP 减少与目标技能等级增加，已停止。",
                              {"skill_id": skill_id, "allocated": allocated, "sp_before": current["skill_points"],
                               "sp_after": after["skill_points"], "level_before": current_level, "level_after": level})
        current, current_level = after, level
    return {"skill_id": skill_id, "allocated": count, "level_before": original_level,
            "level_after": current_level, "sp_before": before["skill_points"], "sp_after": current["skill_points"]}
