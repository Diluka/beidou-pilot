"""为 tick Lua 策略提供初始场景身份；静态地形等场景事实由原生引擎按同一身份维护。"""

from .backend import JsonObject
from .bridge import BridgeSnapshot
from .errors import ClientError


def scene_context(state: BridgeSnapshot) -> JsonObject:
    map_id = state["map_id"]
    character = state["character"]
    if not state["ready"] or map_id is None or character is None:
        raise ClientError("strategy_scene_unavailable", "当前原生快照没有就绪的角色和地图，未启动策略。")
    return {
        "instance_id": state["instance_id"],
        "character_id": character["id"],
        "map_id": map_id,
        "scene_generation": state["scene_generation"],
    }
