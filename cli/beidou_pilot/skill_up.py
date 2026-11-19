"""原版技能窗口的单次技能点分配。"""

import hashlib
import time

from .img_resources import ImgDirectory
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .engines.character import CharacterSnapshot
from .ui import click_control, click_window, open_window, read_ui


def preflight_skill_up(backend: Backend, skill_id: int, points: int, *, batch: bool = False) -> tuple | None:
    """在任何桌面输入前核对总量；未知技能上限时拒绝批次。"""
    if backend.name != "beidou":
        raise ClientError("unsupported_capability", "该客户端不提供原版技能窗口加点。")
    if skill_id <= 0 or points <= 0:
        raise ClientError("usage", "技能 ID 和点数必须为正整数。")
    observation = backend.read("observe")
    character = cast(JsonObject | None, observation.get("character"))
    if observation.get("native_values_valid") is not True or character is None:
        raise ClientError("character_unavailable", "角色状态不可用。")
    sp = character.get("skill_points")
    if not isinstance(sp, int) or isinstance(sp, bool):
        raise ClientError("skill_points_unavailable", "剩余技能点不可用。")
    if points > sp:
        raise ClientError("insufficient_skill_points", "剩余技能点不足。", {"requested": points, "available": sp})
    if points > 1 or batch:
        client = cast(JsonObject | None, observation.get("client"))
        if client is None or any(value is None for value in (observation.get("instance_id"), client.get("run_id"), character.get("id"))):
            raise ClientError("character_unavailable", "角色或实例身份不可用。")
        if character.get("job") != 210 or skill_id not in {2100000, 2101001, 2101002, 2101003, 2101004, 2101005}:
            raise ClientError("skill_limit_unavailable", "该职业或技能的批量上限尚未核实。")
        learned = cast(CharacterSnapshot, backend.read("character"))
        if not learned["skills_complete"] or learned["character_id"] != character.get("id"):
            raise ClientError("skills_unavailable", "技能记录不完整或角色身份不一致。")
        skill = learned["skills"].get(str(skill_id))
        level = skill["level"] if skill is not None else 0
        path = backend.root / "client" / "Data" / "Skill" / "210.img"
        try:
            with (backend.root / "client" / "BeiDou.exe").open("rb") as stream:
                executable_digest = hashlib.file_digest(stream, "sha256").hexdigest()
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        except OSError as error:
            raise ClientError("skill_limit_unavailable", "技能资源无法读取。") from error
        if (executable_digest != "1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df"
                or digest != "cc4db190d9fef0523fdfe440ae23a3d2fd61359cef6e327e246a86c6c955111e"):
            raise ClientError("skill_limit_unavailable", "技能资源版本未经核实。")
        tree, sources = ImgDirectory(path.parent).read_tree(("210.img", "skill", str(skill_id), "level"))
        names = [child.get("name") for child in tree] if tree is not None else []
        if ({source.resolve() for source in sources} != {path.resolve()} or not names
                or len(set(names)) != len(names) or set(names) != {str(i) for i in range(1, len(names) + 1)}):
            raise ClientError("skill_limit_unavailable", "技能等级资源缺失或不连续。")
        if level < 0 or level + points > len(names):
            raise ClientError("skill_limit_exceeded", "请求超过技能等级上限，未执行加点。",
                              {"skill_id": skill_id, "level": level, "limit": len(names), "requested": points})
        return (observation.get("instance_id"), client.get("run_id"), character.get("id"), sp, level)
    return None


def skill_up_once(backend: Backend, skill_id: int, expected: tuple | None = None) -> JsonObject:
    """只派发一次；无法确认时不重试。"""
    if backend.name != "beidou":
        raise ClientError("unsupported_capability", "该客户端不提供原版技能窗口加点。")
    if skill_id <= 0:
        raise ClientError("usage", "技能 ID 必须为正整数。")

    observation = backend.read("observe")
    character = cast(JsonObject | None, observation.get("character"))
    client = cast(JsonObject | None, observation.get("client"))
    if observation.get("native_values_valid") is not True or character is None or client is None:
        raise ClientError("character_unavailable", "角色状态不可用。")
    identity = (observation.get("instance_id"), client.get("run_id"), character.get("id"))
    if any(value is None for value in identity):
        raise ClientError("character_unavailable", "角色或实例身份不可用。")
    sp = character.get("skill_points")
    if not isinstance(sp, int) or isinstance(sp, bool):
        raise ClientError("skill_points_unavailable", "剩余技能点不可用。")
    if sp < 1:
        raise ClientError("insufficient_skill_points", "剩余技能点不足。")
    learned = cast(CharacterSnapshot, backend.read("character"))
    if not learned["skills_complete"] or learned["character_id"] != identity[2]:
        raise ClientError("skills_unavailable", "技能记录不完整或角色身份不一致。")
    skill = learned["skills"].get(str(skill_id))
    # 原版普通技能查询在等级映射没有记录时返回零；异常技能仍不推断。
    if skill is None and not (character.get("job") == 210 and skill_id // 10000 == 210):
        raise ClientError("skill_level_unavailable", "客户端没有该技能的等级记录，无法确认初始等级。", {"skill_id": skill_id})
    before = skill["level"] if skill is not None else 0
    if expected is not None and (*identity, sp, before) != expected:
        raise ClientError("skill_state_changed", "批量预检后角色状态发生变化，未执行加点。")
    window = open_window(backend, "skills")
    view = window["skills"]
    if view is None:
        raise ClientError("skills_ui_unavailable", "技能窗口列表不可用。")
    for tab in range(view["tab_count"]):
        if skill_id in view["ids"]:
            break
        if tab == view["selected_tab"]:
            continue
        click_window(backend, window, 19 + tab * 35, 34)
        matches = [entry for entry in read_ui(backend)["windows"]
                   if entry.get("instance_ref") == window.get("instance_ref") and window.get("instance_ref")]
        if len(matches) != 1:
            raise ClientError("skills_ui_unavailable", "技能窗口已消失或身份不唯一。")
        window = matches[0]
        view = window["skills"]
        if view is None or view["selected_tab"] != tab:
            raise ClientError("skill_tab_not_confirmed", "技能页切换未确认。")
    if skill_id not in view["ids"]:
        raise ClientError("skill_not_in_ui", "当前角色技能页未列出该技能。", {"skill_id": skill_id})
    if view["ids"].count(skill_id) != 1:
        raise ClientError("skill_ambiguous", "技能页包含重复技能 ID。", {"skill_id": skill_id})
    # 仅这一职业和技能页的通用 SP 对应关系经过真实 GUI 验证。
    if character.get("job") != 210 or view["selected_tab"] != 2:
        raise ClientError("skill_points_pool_unavailable", "该职业或技能页的技能点分册尚未核实。")
    index = view["ids"].index(skill_id)
    for _ in range(len(view["ids"])):
        if 0 <= index - view["first_index"] < 4:
            break
        direction = "down" if index >= view["first_index"] + 4 else "up"
        first = view["first_index"]
        click_window(backend, window, 100, 130)
        backend.read("desktop", "scroll", direction, "--ticks", "1")
        matches = [entry for entry in read_ui(backend)["windows"]
                   if entry.get("instance_ref") == window.get("instance_ref") and window.get("instance_ref")]
        if len(matches) != 1:
            raise ClientError("skills_ui_unavailable", "技能窗口已消失或身份不唯一。")
        window = matches[0]
        view = window["skills"]
        if (view is None or view["selected_tab"] != 2 or view["ids"].count(skill_id) != 1
                or (direction == "down" and view["first_index"] <= first)
                or (direction == "up" and view["first_index"] >= first)):
            raise ClientError("skill_scroll_not_confirmed", "技能列表滚动未确认。")
        index = view["ids"].index(skill_id)
    row = index - view["first_index"]
    if not 0 <= row < 4:
        raise ClientError("skill_not_visible", "目标技能未出现在可见行。")
    buttons = [button for button in window["buttons"] if button["control_id"] == 2010 + row]
    if len(buttons) != 1 or buttons[0].get("enabled") is not True:
        raise ClientError("skill_not_available", "原版技能窗口未启用该技能的加点按钮；具体原因未知。", {"skill_id": skill_id})

    current = backend.read("observe")
    current_character = cast(JsonObject | None, current.get("character"))
    current_client = cast(JsonObject | None, current.get("client"))
    current_skills = cast(CharacterSnapshot, backend.read("character"))
    if (current_character is None or current_client is None or current.get("native_values_valid") is not True
            or (current.get("instance_id"), current_client.get("run_id"), current_character.get("id")) != identity
            or current_character.get("skill_points") != sp or current_character.get("job") != character.get("job")
            or not current_skills["skills_complete"]
            or current_skills["character_id"] != identity[2]
            or current_skills["skills"].get(str(skill_id)) != skill):
        raise ClientError("skill_state_changed", "加点前角色状态发生变化，请重新观察。")
    latest = read_ui(backend)
    matches = [entry for entry in latest["windows"] if entry.get("instance_ref") == window.get("instance_ref")]
    if (not window.get("instance_ref") or len(matches) != 1 or matches[0]["skills"] != view
            or matches[0]["buttons"] != window["buttons"]
            or not latest["dialog"]["focused_window"]
            or latest["dialog"]["focused_window"]["address"] != window["address"]):
        raise ClientError("skill_state_changed", "加点前技能窗口发生变化，请重新观察。")
    window = matches[0]
    rect = window["root_rect"]
    if rect is None:
        raise ClientError("ui_unavailable", "技能窗口根坐标不可用。")
    button = buttons[0]
    x = rect["left"] + button["layout_x"] + button["width"] // 2
    y = rect["top"] + button["layout_y"] + button["height"] // 2
    for other in latest["windows"][latest["windows"].index(window) + 1:]:
        if other["vtables"][0] in {"0xb3f13c", "0xb37bbc", "0xb3ba80"}:
            continue
        other_rect = other["root_rect"]
        if other_rect is None:
            raise ClientError("ui_unavailable", "其他活动窗口的位置未知。")
        if other_rect["left"] <= x < other_rect["right"] and other_rect["top"] <= y < other_rect["bottom"]:
            raise ClientError("ui_target_occluded", "加点按钮被其他窗口遮挡。")
    try:
        click_control(backend, window, 2010 + row)
    except ClientError as error:
        raise ClientError("skill_up_unknown", "加点点击结果未知；请观察后再决定。",
                          {"skill_id": skill_id, "cause": error.code}) from error
    deadline = time.monotonic() + 2.0
    while True:
        try:
            after = backend.read("observe")
            after_skills = cast(CharacterSnapshot, backend.read("character"))
        except ClientError as error:
            raise ClientError("skill_up_unknown", "已点击加点，观察失败；请观察后再决定。",
                              {"skill_id": skill_id, "cause": error.code}) from error
        after_character = cast(JsonObject | None, after.get("character"))
        after_client = cast(JsonObject | None, after.get("client"))
        if (after_character is None or after_client is None or after.get("native_values_valid") is not True
                or (after.get("instance_id"), after_client.get("run_id"), after_character.get("id")) != identity
                or not after_skills["skills_complete"] or after_skills["character_id"] != identity[2]):
            raise ClientError("skill_up_unknown", "已点击加点，但角色状态不可确认；请观察后再决定。", {"skill_id": skill_id})
        updated = after_skills["skills"].get(str(skill_id))
        if updated is not None and updated["level"] == before + 1 and after_character.get("skill_points") == sp - 1:
            return {"skill_id": skill_id, "level_before": before, "level_after": before + 1,
                    "sp_before": sp, "sp_after": sp - 1}
        if time.monotonic() >= deadline:
            raise ClientError("skill_up_unknown", "已点击加点，但结果未确认；请观察后再决定。",
                              {"skill_id": skill_id, "level_before": before, "sp_before": sp,
                               "level_observed": updated["level"] if updated else None,
                               "sp_observed": after_character.get("skill_points")})
        time.sleep(0.1)
