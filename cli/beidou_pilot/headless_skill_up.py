"""无头技能点请求：每次发包后独立观察，不重放未知结果。"""

import time
from typing import cast

from .backend import Backend, ClientError, JsonObject
from .bridge import BridgeClient
from .engines.character import CharacterSnapshot


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
                if (not isinstance(beginner_ids, list) or any(type(item) is not int for item in beginner_ids)
                        or type(beginner_sp) is not int):
                    raise ClientError("skills_unavailable", "新手技能分册观察不可用。")
                beginner = skill_id in beginner_ids
                level = learned["skills"].get(str(skill_id), {"level": 0})["level"]
                sp = beginner_sp if beginner else character["skill_points"]
                request_id = bridge._publish(before, "skill-up", skill_id, [str(remaining)])
            except ClientError as error:
                raise ClientError(error.code, error.message, {**error.details, "confirmed": results}) from error
            try:
                bridge._wait(before, request_id, timeout)
                deadline = time.monotonic() + timeout
                while True:
                    state = bridge.snapshot()
                    current = state["character"]
                    if (state["instance_id"] != before["instance_id"] or state["run_id"] != before["run_id"]
                            or current is None or current["id"] != character["id"]):
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
                    if after == level + 1 and after_sp == sp - 1:
                        results.append({"level_before": level, "level_after": after,
                                        "sp_before": sp, "sp_after": after_sp})
                        break
                    if time.monotonic() >= deadline:
                        raise ClientError("bridge_timeout", "未观察到技能等级与技能点变化。")
                    time.sleep(0.05)
            except ClientError as error:
                if error.code == "bridge_command_rejected":
                    raise ClientError(error.code, error.message, {**error.details, "confirmed": results}) from error
                raise ClientError("skill_up_unknown", "加点请求已发布，结果未知；请重新观察，不要重试。",
                                  {"request_id": request_id, "confirmed": results, "cause": error.code}) from error
    return {"skill_id": skill_id, "confirmed_points": len(results), "allocations": results}
