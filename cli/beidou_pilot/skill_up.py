"""原生无窗口技能点分配；每次调用仅提交一个不可重放的请求。"""

import json
import os
import time
import uuid
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .bridge import BridgeClient
from .engines.character import CharacterSnapshot

BEGINNER_SKILLS = (1000, 1001, 1002, 10001000, 10001001, 10001002,
                   20001000, 20001001, 20001002, 20011000, 20011001, 20011002)


def _beginner_points(character: JsonObject, learned: CharacterSnapshot) -> int:
    level = character.get("level")
    if type(level) is not int or not 1 <= level <= 255:
        raise ClientError("skill_points_unavailable", "角色等级不可用。")
    levels = [learned["skills"][str(i)]["level"] for i in BEGINNER_SKILLS if str(i) in learned["skills"]]
    if any(type(value) is not int or value < 0 for value in levels):
        raise ClientError("skills_unavailable", "初学者技能等级不可用。")
    points = min(level, 7) - 1 - sum(levels)
    if points < 0:
        raise ClientError("skill_points_unavailable", "初学者技能点数据不一致。")
    return points


def _native_skill_request(backend: Backend, instance: str, run: str, scene: int,
                          character: int, skill: int, remaining: int) -> tuple[str, int]:
    """发布一次请求；返回只代表事件调用，不代表游戏状态已改变。"""
    request_id = uuid.uuid4().hex
    directory = backend.paths.bridge
    temporary = directory / ("skill-up-" + request_id + ".tmp")
    request = directory / "skill-up.txt"
    result = directory / ("skill-up-result-" + request_id + ".json")
    deadline_ms = int(time.time() * 1000) + 2000
    line = f"1 {instance} {run} {request_id} {scene} {character} {skill} {remaining} {deadline_ms}\n"
    try:
        with temporary.open("x", encoding="ascii") as handle:
            handle.write(line)
        os.link(temporary, request)
    except OSError as error:
        raise ClientError("skill_up_publish_failed", "原生加点请求未发布。",
                          {"request_id": request_id, "reason": str(error)}) from error
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    until = time.monotonic() + 2.0
    while True:
        try:
            raw = json.loads(result.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
        if isinstance(raw, dict) and raw.get("request_id") == request_id:
            if (type(raw.get("protocol")) is not int or raw["protocol"] != 1
                    or raw.get("status") not in ("invoked", "rejected")
                    or not isinstance(raw.get("reason"), str)):
                raise ClientError("skill_up_unknown", "原生加点结果无效，请观察后再决定。",
                                  {"request_id": request_id, "deadline_ms": deadline_ms})
            if raw["status"] == "rejected":
                raise ClientError(raw["reason"], "原生桥拒绝了加点请求。", {"request_id": request_id})
            return request_id, deadline_ms
        if time.monotonic() >= until:
            raise ClientError("skill_up_unknown", "原生加点结果超时；截止时间后观察，绝不自动重发。",
                              {"request_id": request_id, "deadline_ms": deadline_ms})
        time.sleep(0.02)


def preflight_skill_up(backend: Backend, skill_id: int, points: int, *, batch: bool = False) -> tuple:
    if backend.name != "beidou":
        raise ClientError("unsupported_capability", "该客户端不提供原生技能加点。")
    if not 0 < skill_id <= 0xffffffff or not 0 < points <= 0xffffffff:
        raise ClientError("usage", "技能 ID 和点数须为正整数。")
    supported = {100: {1000000, 1000001, 1000002, 1001003, 1001004, 1001005},
                 210: {2100000, 2101001, 2101002, 2101003, 2101004, 2101005}}
    beginner = skill_id in BEGINNER_SKILLS
    if beginner and skill_id != 1000:
        raise ClientError("skill_up_unsupported", "该初学者技能的职业映射尚未核实。", {"skill_id": skill_id})
    if not beginner and not any(skill_id in skills for skills in supported.values()):
        raise ClientError("skill_up_unsupported", "该技能尚不支持无窗口加点。", {"skill_id": skill_id})
    state = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
    character = state["character"]
    if not state["ready"] or character is None or character["id"] <= 0:
        raise ClientError("character_unavailable", "角色状态不可用。")
    if (beginner and character["job"] != 100) or (not beginner and skill_id not in supported.get(character["job"], set())):
        raise ClientError("skill_up_unsupported", "该职业和技能组合尚不支持无窗口加点。")
    learned = cast(CharacterSnapshot, backend.read("character"))
    if not learned["skills_complete"] or learned["character_id"] != character["id"]:
        raise ClientError("skills_unavailable", "技能记录不完整或角色身份不一致。")
    sp = _beginner_points(cast(JsonObject, character), learned) if beginner else character["skill_points"]
    if type(sp) is not int or sp < 0:
        raise ClientError("skill_points_unavailable", "剩余技能点不可用。")
    if sp < points:
        raise ClientError("insufficient_skill_points", "剩余技能点不足。")
    skill = learned["skills"].get(str(skill_id))
    level = skill["level"] if skill is not None else 0
    if type(level) is not int or level < 0:
        raise ClientError("skill_level_unavailable", "技能等级不可用。")
    beginner_state = (character["level"], character["job"],
                      tuple(learned["skills"].get(str(i)) for i in BEGINNER_SKILLS)) if beginner else (None, character["job"], None)
    return (state["instance_id"], state["run_id"], character["id"], sp, level,
            state["scene_generation"], points, beginner_state)


def skill_up_once(backend: Backend, skill_id: int, expected: tuple | None = None) -> JsonObject:
    before = preflight_skill_up(backend, skill_id, expected[6] if expected else 1)
    if expected is not None and before != expected:
        raise ClientError("skill_state_changed", "加点前角色状态发生变化。")
    instance, run, character, sp, level, scene, remaining, beginner_state = before
    request_id, deadline_ms = _native_skill_request(backend, instance, run, scene, character, skill_id, remaining)
    deadline = time.monotonic() + 2.0
    while True:
        try:
            state = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
            current = state["character"]
            learned = cast(CharacterSnapshot, backend.read("character"))
            if (current is None or not state["ready"] or
                    (state["instance_id"], state["run_id"], current["id"], state["scene_generation"]) !=
                    (instance, run, character, scene) or not learned["skills_complete"] or
                    learned["character_id"] != character):
                raise ClientError("skill_up_unknown", "原生事件已调用，但角色身份不可确认。",
                                  {"request_id": request_id, "deadline_ms": deadline_ms})
            updated = learned["skills"].get(str(skill_id))
            old_level, old_job, old_skills = beginner_state
            if current["job"] != old_job:
                raise ClientError("skill_up_unknown", "原生事件已调用，角色职业发生变化。",
                                  {"request_id": request_id, "deadline_ms": deadline_ms})
            if old_skills is not None:
                if (current["level"] != old_level or
                        any(learned["skills"].get(str(i)) != old_skills[index]
                            for index, i in enumerate(BEGINNER_SKILLS) if i != skill_id)):
                    raise ClientError("skill_up_unknown", "新手技能状态变化，无法确认本次结果。",
                                      {"request_id": request_id, "deadline_ms": deadline_ms})
                current_sp = _beginner_points(cast(JsonObject, current), learned)
            else:
                current_sp = current["skill_points"]
            if updated is not None and updated["level"] == level + 1 and current_sp == sp - 1:
                return {"skill_id": skill_id, "level_before": level, "level_after": level + 1,
                        "sp_before": sp, "sp_after": sp - 1}
        except ClientError as error:
            if error.code == "skill_up_unknown":
                raise
            raise ClientError("skill_up_unknown", "原生事件已调用，观察失败，请勿重发。",
                              {"cause": error.code, "request_id": request_id, "deadline_ms": deadline_ms}) from error
        if time.monotonic() >= deadline:
            raise ClientError("skill_up_unknown", "原生事件已调用但结果未确认，请勿重发。",
                              {"skill_id": skill_id, "request_id": request_id, "deadline_ms": deadline_ms})
        time.sleep(0.1)
