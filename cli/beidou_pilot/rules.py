"""角色成长节点，供命令提示和连续战斗使用。"""

from typing import cast

from .backend import JsonObject
from .errors import ClientError


FIRST_JOB_LEVELS = {"magician": 8, "warrior": 10, "bowman": 10, "thief": 10, "pirate": 10}


def advancement(character: JsonObject, first_job: str | None = None) -> JsonObject | None:
    job, level = int(character["job"]), int(character["level"])
    if job == 0:
        if first_job is None:
            return {"level": None, "due": None, "job": job, "first_job": None,
                    "candidates": [{"first_job": name, "level": required}
                                   for name, required in FIRST_JOB_LEVELS.items()]}
        if first_job not in FIRST_JOB_LEVELS:
            raise ClientError("invalid_first_job", "请选择已支持的冒险家首转路线。")
        required = FIRST_JOB_LEVELS[first_job]
        return {"level": required, "due": level >= required, "job": job, "first_job": first_job}
    elif job in (100, 200, 300, 400, 500):
        required = 30
    elif job in (110, 120, 130, 210, 220, 230, 310, 320, 410, 420, 510, 520):
        required = 70
    elif job in (111, 121, 131, 211, 221, 231, 311, 321, 411, 421, 511, 521):
        required = 120
    else:
        return None
    return {"level": required, "due": level >= required, "job": job}


def combat_stop_level(
    character: JsonObject, *, first_job: str | None = None, until_level: int | None = None,
    default_level: int | None = None,
) -> tuple[int | None, str, JsonObject | None]:
    """解析本次停级参数；未知路线的早期检查点不代表已选职业。"""
    if until_level is not None and until_level < 1:
        raise ClientError("invalid_until_level", "停级须为正数。")
    milestone = advancement(character, first_job)
    if milestone and milestone["due"]:
        raise ClientError("advancement_due", "先完成当前阶段转职，再继续战斗或狩猎。", milestone)
    if milestone and milestone["level"] is not None:
        required = cast(int, milestone["level"])
        if until_level is not None and until_level <= required:
            return until_level, "until_level", milestone
        return required, "advancement", milestone
    if until_level is not None:
        return until_level, "until_level", milestone
    if milestone:
        checkpoint = min(FIRST_JOB_LEVELS.values())
        if int(character["level"]) >= checkpoint:
            raise ClientError(
                "advancement_route_required",
                "已到首个转职检查点；请用--first-job选择路线，或用--until-level明确本次目标。", milestone,
            )
        return checkpoint, "first_job_checkpoint", milestone
    return default_level, "next_level" if default_level is not None else "none", None


def job_name(job: int) -> str:
    return {0: "新手", 100: "战士", 110: "剑客", 120: "准骑士", 130: "枪战士",
            111: "勇士", 121: "骑士", 131: "龙骑士", 112: "英雄", 122: "圣骑士",
            132: "黑骑士", 200: "魔法师", 300: "弓箭手", 400: "飞侠", 500: "海盗"}.get(job, str(job))
