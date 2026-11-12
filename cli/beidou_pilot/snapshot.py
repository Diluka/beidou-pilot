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
    dialog = None if backend.name == "headless" else backend.read("dialog")
    interaction = backend.read("interaction") if backend.name == "headless" else None
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
    scope = [client["container_id"], client["run_id"], observation["instance_id"], character["id"], map_id,
             stage.get("world_id"), stage.get("channel")]
    viewport = None if dialog is None else cast(JsonObject | None, dialog["camera_viewport"])

    def reference(kind: str, identity: JsonValue, target: JsonObject) -> str:
        digest = hashlib.sha256(json.dumps([scope, kind, identity], sort_keys=True).encode()).hexdigest()[:10]
        value = "@" + kind + digest
        refs[value] = target
        return value

    entities: dict[str, list[JsonObject]] = {"npcs": [], "monsters": [], "drops": []}
    groups = [("npcs", "n"), ("monsters", "m"), ("drops", "d")]
    if isinstance(scene.get("players"), list):
        entities["players"] = []
        groups.append(("players", "p"))
    for group, prefix in groups:
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
            elif group == "players":
                pass
            else:
                item_id = original.get("item_id")
                entity["name"] = catalog.item_name(cast(int, item_id)) if item_id else ("金币" if original.get("money") else None)
            entity["visible"] = visible
            entity["dx"] = x - cast(int | float, player["x"])
            entity["dy"] = y - cast(int | float, player["y"])
            if group == "npcs" and backend.name == "headless":
                entity["ref"] = original.get("ref")
            else:
                identity = (original.get("character_id") if group == "players" else original["object_id"])
                if group == "players" and identity is None:
                    identity = original.get("reference") or original.get("name")
                entity["ref"] = reference(prefix, identity, {"kind": group, **entity})
            entities[group].append(entity)
        entities[group].sort(key=lambda item: abs(cast(int | float, item["dx"])) + abs(cast(int | float, item["dy"])))

    offer: JsonObject = {"supported": dialog is not None, "open": None, "npc_id": None,
                         "type": None, "lines": [], "choices": [], "buttons": []}
    if dialog is not None:
        offer.update(open=dialog["dialog_open"], npc_id=dialog["npc_id"],
                     type=dialog["dialog_type"], lines=dialog["lines"])
        fingerprint: JsonValue = [dialog["npc_id"], dialog["dialog_type"], dialog["lines"]]
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
    result.update(observed_at=observation["observed_at"], map={"id": map_id, "name": catalog.map_name(map_id)},
                  character=character, position=player, facing=scene["player_facing"],
                  players_complete=scene.get("players_complete"),
                  advancement=advancement(character), viewport=viewport, **entities, inventory=items,
                  equipped=equipped, quests=quests["quests"],
                  quest_observation={key: quests[key] for key in ("data_source", "live_updates", "live_update_kinds", "not_covered") if key in quests},
                  refs=refs)
    if interaction is not None:
        result["interaction"] = {"page": interaction["page"],
                                 **{key: interaction[key] for key in ("unavailable", "not_covered") if key in interaction}}
    else:
        result["dialog"] = offer
    if debug:
        result["raw"] = {"stage": stage, "observation": observation, "scene": scene,
                         "dialog": dialog, "interaction": interaction, "inventory": inventory, "quests": quests, "character": character_data}
    return result


def format_snapshot(value: JsonObject, *, interactive_only: bool = False) -> str:
    if value["stage"] != "IN_GAME":
        return json.dumps(value, ensure_ascii=False, indent=2)
    c, p, m = (cast(JsonObject, value[k]) for k in ("character", "position", "map"))
    lines = [f"{c['name']} Lv{c['level']} {c['job_name']} | HP {c['hp']}/{c['max_hp']} MP {c['mp']}/{c['max_mp']}",
             f"{m['name']} ({m['id']}) | ({p['x']},{p['y']}) {value['facing']} | CH{value['channel']}",
             f"EXP {c['experience']} | 金币 {c['mesos']} | AP {c['ability_points']} SP {c['skill_points']}"]
    milestone = cast(JsonObject | None, value.get("advancement"))
    if milestone and milestone["level"] is None:
        lines.append("首转路线未知：魔法师8级，战士、弓箭手、飞侠、海盗10级；fight/hunt默认停在8级检查点，继续前用--first-job选择路线或--until-level明确目标。")
    elif milestone and milestone["due"]:
        lines.append(f"需要先完成 {milestone['level']} 级转职；连续战斗会在此节点停下。")
    if "interaction" in value:
        page = cast(JsonObject | None, cast(JsonObject, value["interaction"])["page"])
        if page is None:
            lines.append("当前没有交互页面。")
        else:
            lines.append(f"交互页面：{page['title']}")
            lines.append(cast(str, page["text"]) if page["text"] is not None else "交互正文：未知。")
            if page["controls"] is None:
                lines.append("交互控件：未知。")
            else:
                for control in cast(list[JsonObject], page["controls"]):
                    enabled = "可用" if control["enabled"] is True else "不可用" if control["enabled"] is False else "启用状态未知"
                    lines.append(f"  {control['ref']} [{control['role']}] {control['text']} ({enabled})")
    else:
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
    for group, label in (("npcs", "NPC"), ("monsters", "怪物"), ("drops", "掉落"), ("players", "玩家")):
        if interactive_only and group == "monsters":
            continue
        for a in cast(list[JsonObject], value.get(group) or []):
            suffix = " (可见性未知)" if a["visible"] is None else (" (画外)" if a["visible"] is False else "")
            target = a["ref"] if a["ref"] is not None else "引用未知"
            if group == "players":
                level = a.get("level")
                lines.append(f"  {target} {label} {a.get('name') or '未知'} Lv{level if level is not None else '?'} "
                             f"({a['x']},{a['y']}){suffix}")
            else:
                lines.append(f"  {target} {label} {a['name']} ({a['x']},{a['y']}){suffix}")
    return "\n".join(lines)
