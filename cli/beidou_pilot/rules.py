"""角色成长节点，供命令提示和连续战斗使用。"""

from .backend import JsonObject


def advancement(character: JsonObject) -> JsonObject | None:
    job, level = int(character["job"]), int(character["level"])
    if job == 0:
        required = 10
    elif job in (100, 200, 300, 400, 500):
        required = 30
    elif job in (110, 120, 130, 210, 220, 230, 310, 320, 410, 420, 510, 520):
        required = 70
    elif job in (111, 121, 131, 211, 221, 231, 311, 321, 411, 421, 511, 521):
        required = 120
    else:
        return None
    return {"level": required, "due": level >= required, "job": job}


def job_name(job: int) -> str:
    return {0: "新手", 100: "战士", 110: "剑客", 120: "准骑士", 130: "枪战士",
            111: "勇士", 121: "骑士", 131: "龙骑士", 112: "英雄", 122: "圣骑士",
            132: "黑骑士", 200: "魔法师", 300: "弓箭手", 400: "飞侠", 500: "海盗"}.get(job, str(job))
