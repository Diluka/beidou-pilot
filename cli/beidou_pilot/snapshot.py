"""将客户端只读结果投影为代理可使用的短快照和当前引用。"""

import hashlib
import json
from typing import cast

from .backend import Backend, JsonObject, JsonValue
from .catalog import Catalog
from .rules import advancement, job_name


BUTTONS = {1: "confirm", 2: "end", 6: "yes", 7: "no", 8192: "back", 8193: "next"}


def collect(backend: Backend, *, all_entities: bool = False, debug: bool = False) -> JsonObject:
    stage = backend.read("stage")
    result: JsonObject = {"stage": stage["stage"], "running": stage["running"],
                          "channel": stage.get("channel"), "dead": None, "revive_requestable": None, "refs": {}}
    if stage["stage"] != "IN_GAME":
        result["login"] = stage.get("login")
        result["unavailable"] = stage.get("unavailable", [])
        if debug:
            result["raw"] = {"stage": stage}
        return result
    observation = backend.read("observe")
    if (observation["native_values_valid"] is not True
            or observation["character"] is None or observation["position"] is None):
        result.update(stage="TRANSITION", unavailable=observation["unavailable"])
        return result
    scene = backend.read("scene")
    dialog = backend.read("dialog")
    inventory = backend.read("inventory", "--type", "1", "--type", "2", "--type", "3", "--type", "4", "--type", "5", "--equipped")
    quests = backend.read("quests")
    character_data = backend.read("character")
    catalog = Catalog(backend.root)
    result.update(dead=observation.get("dead"), revive_requestable=observation.get("revive_requestable"))
    character = cast(JsonObject, observation["character"])
    player = cast(JsonObject, observation["position"])
    map_id = cast(int, observation["map_id"])
    if scene["map_id"] != map_id:
        result.update(stage="TRANSITION", unavailable=["采样期间场景变化，请重新 snapshot。"])
        return result
    character = dict(character)
    character["job_name"] = job_name(cast(int, character["job"]))
    character["mesos"] = character_data.get("mesos")
    character["skills"] = character_data.get("skills", {})
    refs: JsonObject = {}
    client = cast(JsonObject, observation["client"])
    scope = [client["container_id"], client["run_id"], observation["instance_id"], observation["scene_generation"], character["id"], map_id,
             stage.get("world_id"), stage.get("channel")]
    viewport = cast(JsonObject | None, dialog["camera_viewport"])

    def reference(kind: str, identity: JsonValue, target: JsonObject) -> str:
        digest = hashlib.sha256(json.dumps([scope, kind, identity], sort_keys=True).encode()).hexdigest()[:10]
        value = "@" + kind + digest
        refs[value] = target
        return value

    entities: dict[str, list[JsonObject]] = {"npcs": [], "monsters": [], "drops": []}
    for group, prefix in (("npcs", "n"), ("monsters", "m"), ("drops", "d")):
        for original in cast(list[JsonObject], scene.get(group, [])):
            x, y = cast(int | float, original["x"]), cast(int | float, original["y"])
            visible = None if viewport is None else (
                cast(int, viewport["left"]) <= x < cast(int, viewport["right"])
                and cast(int, viewport["top"]) <= y < cast(int, viewport["bottom"]))
            if not all_entities and visible is False:
                continue
            entity: JsonObject = {k: v for k, v in original.items() if k != "address"}
            template = original.get("template_id")
            if group == "npcs":
                entity["name"] = original.get("name") or (
                    catalog.npc_name(cast(int, template)) or str(template) if template is not None else None)
            elif group == "monsters":
                entity["name"] = original.get("name") or (
                    catalog.monster_name(cast(int, template)) or str(template) if template is not None else None)
            else:
                item_id = original.get("item_id")
                entity["name"] = catalog.item_name(cast(int, item_id)) if item_id else ("金币" if original.get("money") else None)
            entity["visible"] = visible
            entity["dx"] = x - cast(int | float, player["x"])
            entity["dy"] = y - cast(int | float, player["y"])
            entity["ref"] = reference(prefix, original["object_id"], {"kind": group, **entity})
            entities[group].append(entity)
        entities[group].sort(key=lambda item: abs(cast(int | float, item["dx"])) + abs(cast(int | float, item["dy"])))

    offer: JsonObject = {"supported": True, "open": None, "npc_id": None,
                         "type": None, "lines": [], "choices": [], "buttons": []}
    offer.update(open=dialog["dialog_open"], npc_id=dialog["npc_id"],
                 npc_object_id=dialog.get("npc_object_id"), reference=dialog.get("dialog_reference"),
                 page_revision=dialog.get("page_revision"), response_pending=dialog.get("response_pending"),
                 closed_by=dialog.get("closed_by"), type=dialog["dialog_type"], lines=dialog["lines"])
    fingerprint: JsonValue = [dialog.get("dialog_reference"), dialog["npc_id"], dialog["dialog_type"], dialog["lines"]]
    for original in cast(list[JsonObject], dialog["choices"]):
        value = dict(original)
        value["ref"] = reference("c", [fingerprint, value["link_id"]], {"kind": "choice", **value})
        cast(list[JsonObject], offer["choices"]).append(value)
    for original in cast(list[JsonObject], dialog["buttons"]):
        value: JsonObject = {"control_id": original["control_id"], "root_rect": original.get("root_rect"),
                             "action": BUTTONS.get(cast(int, original["control_id"]), str(original["control_id"]))}
        value["ref"] = reference("b", [fingerprint, value["control_id"]], {"kind": "button", **value})
        cast(list[JsonObject], offer["buttons"]).append(value)
    items = cast(list[JsonObject], inventory["items"])
    for item in items:
        item["name"] = catalog.item_name(cast(int, item["item_id"]))
        item["ref"] = reference("i", [item["inventory_type"], item["slot"], item["item_id"]], {"kind": "item", **item})
    equipped = cast(list[JsonObject], inventory.get("equipped", []))
    for item in equipped:
        item["name"] = catalog.item_name(cast(int, item["item_id"]))
    result.update(observed_at=observation["observed_at"], scene_generation=observation["scene_generation"],
                  map={"id": map_id, "name": catalog.map_name(map_id)},
                  character=character, position=player, facing=scene["player_facing"],
                  advancement=advancement(character), dialog=offer, viewport=viewport, **entities, inventory=items,
                  equipped=equipped, quests=quests["quests"],
                  quest_observation={key: quests[key] for key in ("data_source", "live_updates", "live_update_kinds", "not_covered") if key in quests},
                  refs=refs)
    if debug:
        result["raw"] = {"stage": stage, "observation": observation, "scene": scene,
                         "dialog": dialog, "inventory": inventory, "quests": quests, "character": character_data}
    return result


def format_snapshot(value: JsonObject, *, interactive_only: bool = False) -> str:
    if value["stage"] != "IN_GAME":
        return json.dumps(value, ensure_ascii=False, indent=2)
    c, p, m = (cast(JsonObject, value[k]) for k in ("character", "position", "map"))
    lines = [f"{c['name']} Lv{c['level']} {c['job_name']} | HP {c['hp']}/{c['max_hp']} MP {c['mp']}/{c['max_mp']}",
             f"{m['name']} ({m['id']}) | ({p['x']},{p['y']}) {value['facing']} | CH{value['channel']}",
             f"EXP {c['experience']} | 金币 {c['mesos']} | AP {c['ability_points']} SP {c['skill_points']}"]
    milestone = cast(JsonObject | None, value.get("advancement"))
    if milestone and milestone["due"]:
        lines.append(f"需要先完成 {milestone['level']} 级转职；连续战斗会在此节点停下。")
    dialog = cast(JsonObject, value["dialog"])
    if dialog["supported"] is False:
        lines.append("对话状态：客户端不支持观察。")
    elif dialog["open"] is None:
        lines.append("对话状态：未知。")
    elif dialog["open"]:
        lines.append(f"对话 NPC {dialog['npc_id']} (type {dialog['type']})")
        lines += [str(line) for line in cast(list[JsonValue], dialog["lines"])]
        lines += [f"  {a['ref']} {a['text']}" for a in cast(list[JsonObject], dialog["choices"])]
        lines += [f"  {a['ref']} [{a['action']}]" for a in cast(list[JsonObject], dialog["buttons"])]
    for group, label in (("npcs", "NPC"), ("monsters", "怪物"), ("drops", "掉落")):
        if interactive_only and group == "monsters":
            continue
        for a in cast(list[JsonObject], value[group]):
            suffix = " (可见性未知)" if a["visible"] is None else (" (画外)" if a["visible"] is False else "")
            lines.append(f"  {a['ref']} {label} {a['name']} ({a['x']},{a['y']}){suffix}")
    return "\n".join(lines)
