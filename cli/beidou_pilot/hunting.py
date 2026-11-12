"""为单一场景的连续狩猎装载参数和地形，实时决策由 Lua 执行。"""

import math
from typing import cast

from .backend import Backend
from .bridge import BridgeClient, BridgeSnapshot
from .catalog import Catalog
from .control_scripts import run_strategy
from .engines.character import LearnedSkill
from .errors import ClientError, JsonObject
from .hunt_terrain import load_hunt_terrain
from .observations import NativeObserver
from .rules import combat_stop_level


def hunt(
    backend: Backend,
    mob: str = "all",
    *,
    seconds: float | None = 60,
    skill_id: int | None = None,
    attack_range: float = 60,
    bounds: tuple[int, int] | None = None,
    stop_level: int | None = None,
    first_job: str | None = None,
    min_hp_ratio: float = 0.35,
    hp_item_id: int | None = None,
) -> JsonObject:
    if seconds is not None and (not math.isfinite(seconds) or not 0.05 <= seconds <= 600):
        raise ClientError("invalid_hunt_options", "狩猎期限须为0.05至600秒；持续狩猎使用--continuous。")
    if (
        not math.isfinite(attack_range)
        or not 1 <= attack_range <= 1000
        or not math.isfinite(min_hp_ratio)
        or not 0 < min_hp_ratio <= 1
        or bounds is not None
        and bounds[0] >= bounds[1]
        or stop_level is not None
        and stop_level < 1
    ):
        raise ClientError(
            "invalid_hunt_options", "攻击距离须为1至1000，HP下限须为大于0且不超过1，范围须递增，停级须为正数。"
        )
    if skill_id is not None:
        if not 1 <= skill_id <= 0x7FFFFFFF:
            raise ClientError("invalid_skill", "技能ID须为正32位整数。")
    if hp_item_id is not None and (
        not 1 <= hp_item_id <= 0x7FFFFFFF
        or hp_item_id // 10000 != 200
        and not (backend.name == "headless" and hp_item_id // 10000 == 201)
    ):
        raise ClientError("invalid_item", "狩猎回血品支持200类药品；无头端另支持201类食品。")
    if hp_item_id is not None:
        specification = cast(JsonObject, Catalog(backend.root).item(hp_item_id)["spec"])
        hp_values = (specification.get("hp"), specification.get("hpR"))
        if not any(type(value) in (int, float) and value > 0 for value in hp_values):
            known_hp = any(type(value) in (int, float) for value in hp_values)
            heals_mp = any(
                type(value) in (int, float) and value > 0
                for value in (specification.get("mp"), specification.get("mpR"))
            )
            raise ClientError(
                "invalid_hp_item" if known_hp or heals_mp else "healing_metadata_missing",
                "指定物品没有正HP恢复，未开始狩猎。"
                if known_hp or heals_mp
                else "本地资料未确认该物品恢复HP，未开始狩猎，也未消费。",
                {"item_id": hp_item_id, "spec": specification},
            )

    initial = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
    character, position = initial["character"], initial["position"]
    if not initial["ready"] or character is None or position is None or initial["map_id"] is None:
        raise ClientError("not_ready", "当前场景的角色、地图和位置尚未就绪，未开始狩猎。")
    if character["hp"] <= 0:
        raise ClientError("dead", "角色已死亡，请先恢复角色。")
    capabilities = initial.get("capabilities")
    if capabilities is None or capabilities.get("attack_move") is not True:
        raise ClientError("unsupported_capability", "当前原生客户端未声明移动攻击同窗能力，请更新对应构建。")
    if skill_id is not None:
        if capabilities.get("skill") is not True:
            raise ClientError("unsupported_capability", "当前原生客户端未声明支持技能调用，未开始狩猎。")
    stop_level, stop_level_source, milestone = combat_stop_level(
        cast(JsonObject, character), first_job=first_job, until_level=stop_level,
    )

    mob_id = None
    if mob != "all":
        if mob.isdecimal():
            mob_id = int(mob)
            if not 1 <= mob_id <= 0x7FFFFFFF:
                raise ClientError("invalid_mob", "怪物模板ID须为正32位整数。")
        else:
            monsters = initial.get("monsters")
            if monsters is None:
                raise ClientError("observation_unavailable", "怪物观察尚不可用，无法按名称选择目标。")
            catalog = Catalog(backend.root)
            matching = {
                m["template_id"]
                for m in monsters
                if m["template_id"] is not None and mob in (m["name"], catalog.monster_name(m["template_id"]))
            }
            if len(matching) != 1:
                raise ClientError("mob_not_found", "当前怪物名称未匹配唯一模板；请指定模板ID或all。", {"name": mob})
            mob_id = matching.pop()

    if skill_id is not None:
        observed = NativeObserver(backend.root, backend.name, backend.instance).observe("character")
        if (
            observed["instance_id"] != initial["instance_id"]
            or observed["scene_generation"] != initial["scene_generation"]
            or observed["character_id"] != character["id"]
        ):
            raise ClientError("hunt_context_changed", "技能核对期间角色或场景已变化，未开始狩猎。")
        if not observed["native_values_valid"] or not observed["skills_complete"]:
            raise ClientError("observation_unavailable", "当前已学技能记录未完成原生校验，未开始狩猎。")
        learned = cast(dict[str, LearnedSkill], observed["skills"]).get(str(skill_id))
        if learned is None or learned["level"] <= 0:
            raise ClientError("skill_not_learned", "当前角色未学会指定技能，未开始狩猎。", {"skill_id": skill_id})

    terrain = load_hunt_terrain(backend.root, initial["map_id"])
    footholds = cast(list[JsonObject], terrain["footholds"])
    min_x, max_x = (
        bounds
        if bounds is not None
        else (
            min(cast(int, f[key]) for f in footholds for key in ("x1", "x2")),
            max(cast(int, f[key]) for f in footholds for key in ("x1", "x2")),
        )
    )
    if not min_x <= position["x"] <= max_x:
        raise ClientError("outside_hunt_area", "角色当前不在指定狩猎范围内，未输入。")
    options: JsonObject = {
        "instance_id": initial["instance_id"],
        "character_id": character["id"],
        "map_id": initial["map_id"],
        "scene_generation": initial["scene_generation"],
        "mob_id": mob_id,
        "skill_id": skill_id,
        "seconds": seconds,
        "attack_range": attack_range,
        "stop_level": stop_level,
        "min_hp_ratio": min_hp_ratio,
        "hp_item_id": hp_item_id,
        "min_x": min_x,
        "max_x": max_x,
        "terrain": terrain,
    }
    report = run_strategy(backend, "combat/hunt", options, seconds)
    final = cast(BridgeSnapshot, report["last_state"])
    after = final["character"]
    gained = (
        after["experience"] - character["experience"]
        if (after is not None and after["id"] == character["id"] and after["level"] == character["level"])
        else None
    )
    return {
        **report,
        "action": "hunt",
        "scope": "same_scene",
        "target": {"mob_id": mob_id, "all_monsters": mob_id is None},
        "attack": {"mode": "skill" if skill_id is not None else "attack", "skill_id": skill_id, "range": attack_range},
        "terrain_source": terrain["source"],
        "bounds": [min_x, max_x],
        "requested_level": stop_level,
        "advancement": milestone,
        "stop_level_source": stop_level_source,
        "effect": "inspect_final_state",
        "experience_delta": gained,
        "before": {
            "map_id": initial["map_id"],
            "position": cast(JsonObject, position),
            "character": cast(JsonObject, character),
        },
        "after": {
            "map_id": final["map_id"],
            "position": cast(JsonObject | None, final["position"]),
            "character": cast(JsonObject | None, after),
        },
    }
