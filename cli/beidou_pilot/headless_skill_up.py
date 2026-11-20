"""无头技能点请求：每次发包后独立观察，不重放未知结果。"""

import re
import time
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .bridge import BridgeClient
from .engines.character import CharacterSnapshot


_BEGINNER_GROUPS = {
    **dict.fromkeys((0, 100, 110, 111, 112, 120, 121, 122, 130, 131, 132, 200, 210, 211, 212,
                     220, 221, 222, 230, 231, 232, 300, 310, 311, 312, 320, 321, 322, 400,
                     410, 411, 412, 420, 421, 422, 500, 510, 511, 512, 520, 521, 522), 0),
    **dict.fromkeys((1000, 1100, 1110, 1111, 1112, 1200, 1210, 1211, 1212, 1300, 1310, 1311,
                     1312, 1400, 1410, 1411, 1412, 1500, 1510, 1511, 1512), 1000),
    **dict.fromkeys((2000, 2100, 2110, 2111, 2112), 2000),
}


def reconcile_skill_up(backend: Backend, skill_id: int, original_id: str) -> JsonObject:
    """只查询当前运行的原生记录，绝不发布命令。"""
    if not 0 < skill_id <= 0x7fffffff or not re.fullmatch(r"[0-9a-f]{32}", original_id):
        raise ClientError("usage", "技能 ID 或原请求 ID 无效。")
    state = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
    character = state["character"]
    if not state["ready"] or character is None or character["id"] <= 0:
        raise ClientError("character_unavailable", "角色状态不可用。")
    records = state.get("skill_up_records", [])
    confirmed = isinstance(records, list) and any(
        isinstance(record, dict) and record.get("request_id") == original_id
        and record.get("run_id") == state["run_id"] and record.get("instance_id") == state["instance_id"]
        and record.get("character_id") == character["id"] and record.get("skill_id") == skill_id
        and record.get("job") == character["job"] and record.get("status") == "confirmed" for record in records)
    return {"original_request_id": original_id, "skill_id": skill_id,
            "status": "confirmed" if confirmed else "unresolved",
            "reason": "native_observed" if confirmed else "native_record_unresolved"}


def skill_up(backend: Backend, skill_id: int, points: int, timeout: float = 3.0) -> JsonObject:
    bridge = BridgeClient(backend.root, backend.name, backend.instance)
    results: list[JsonObject] = []
    with bridge._control():
        identity = None
        for remaining in range(points, 0, -1):
            try:
                before = bridge._ready_state()
                character = before["character"]
                current_identity = (before["instance_id"], before["run_id"], character["id"] if character else None)
                if identity is not None and current_identity != identity:
                    raise ClientError("bridge_identity_changed", "角色或实例身份发生变化。")
                identity = current_identity
                learned = cast(CharacterSnapshot, backend.read("character"))
                if character is None or not learned["skills_complete"] or learned["character_id"] != character["id"]:
                    raise ClientError("skills_unavailable", "角色技能观察不完整。")
                beginner_ids = learned.get("beginner_skill_ids")
                beginner_sp = learned.get("beginner_skill_points")
                group = _BEGINNER_GROUPS.get(character.get("job"))
                if (group is None or not isinstance(beginner_ids, list)
                        or any(type(item) is not int for item in beginner_ids)
                        or not all(group * 10000 + 1000 + i in beginner_ids for i in range(3))
                        or type(beginner_sp) is not int):
                    raise ClientError("skills_unavailable", "新手技能分册观察不可用。")
                beginner = skill_id in beginner_ids
                level = learned["skills"].get(str(skill_id), {"level": 0})["level"]
                sp = beginner_sp if beginner else character["skill_points"]
                request_id = bridge._publish(before, "skill-up", skill_id,
                                             [str(remaining), before["run_id"], str(character["id"])])
            except ClientError as error:
                raise ClientError(error.code, error.message, {**error.details, "confirmed": results}) from error
            try:
                bridge._wait(before, request_id, timeout)
                deadline = time.monotonic() + timeout
                while True:
                    state = bridge.snapshot()
                    current = state["character"]
                    if (not state["ready"] or state["scene_generation"] != before["scene_generation"]
                            or state["instance_id"] != before["instance_id"] or state["run_id"] != before["run_id"]
                            or current is None or current["id"] != character["id"]
                            or current.get("job") != character.get("job")):
                        raise ClientError("bridge_identity_changed", "角色或实例身份发生变化。")
                    observed = cast(CharacterSnapshot, backend.read("character"))
                    if not observed["skills_complete"] or observed["character_id"] != character["id"]:
                        raise ClientError("skills_unavailable", "角色技能观察不完整。")
                    if observed.get("beginner_skill_ids") != beginner_ids:
                        raise ClientError("skills_unavailable", "新手技能分册观察发生变化。")
                    after_sp = observed.get("beginner_skill_points") if beginner else current["skill_points"]
                    if type(after_sp) is not int:
                        raise ClientError("skills_unavailable", "技能点观察不可用。")
                    after = observed["skills"].get(str(skill_id), {"level": 0})["level"]
                    records = state.get("skill_up_records", [])
                    record = next((item for item in records if isinstance(item, dict)
                                   and item.get("request_id") == request_id
                                   and item.get("run_id") == before["run_id"]
                                   and item.get("instance_id") == before["instance_id"]
                                   and item.get("character_id") == character["id"]
                                   and item.get("skill_id") == skill_id), None) if isinstance(records, list) else None
                    if record is not None and record.get("status") == "unresolved":
                        raise ClientError("skill_record_unresolved", "原生加点记录已失效。")
                    if (record is not None and record.get("status") == "confirmed"
                            and record.get("level_before") == level and record.get("sp_before") == sp
                            and after == level + 1 and after_sp == sp - 1):
                        results.append({"level_before": level, "level_after": after,
                                        "sp_before": sp, "sp_after": after_sp,
                                        "request_id": request_id, "run_id": before["run_id"]})
                        break
                    if time.monotonic() >= deadline:
                        raise ClientError("bridge_timeout", "未观察到技能等级与技能点变化。")
                    time.sleep(0.05)
            except ClientError as error:
                if error.code == "bridge_command_rejected":
                    raise ClientError(error.code, error.message, {**error.details, "confirmed": results}) from error
                raise ClientError("skill_up_unknown", "加点请求已发布，结果未知；请重新观察，不要重试。",
                                  {"request_id": request_id, "run_id": before["run_id"], "skill_id": skill_id,
                                   "confirmed": results, "cause": error.code}) from error
    return {"skill_id": skill_id, "confirmed_points": len(results), "allocations": results}
