"""为 Lua 策略提供带身份和来源的当前地图静态地形。"""

from pathlib import Path

from .backend import JsonObject
from .bridge import BridgeSnapshot
from .errors import ClientError
from .hunt_terrain import load_hunt_terrain


def scene_context(client_root: Path, state: BridgeSnapshot) -> JsonObject:
    map_id = state["map_id"]
    if not state["ready"] or map_id is None:
        raise ClientError("strategy_scene_unavailable", "当前原生快照没有就绪的角色和地图，未启动策略。")
    scene: JsonObject = {"map_id": map_id, "scene_generation": state["scene_generation"]}
    try:
        terrain = load_hunt_terrain(client_root, map_id)
    except ClientError as error:
        if error.code not in {"hunt_terrain_unavailable", "hunt_terrain_unsupported"}:
            raise
        scene["terrain"] = {
            "status": "unsupported" if error.code == "hunt_terrain_unsupported" else "unavailable",
            "error": error.code,
            "message": error.message,
            "details": error.details,
        }
    else:
        scene["terrain"] = {
            "status": "available",
            "source": terrain["source"],
            "footholds": terrain["footholds"],
            "ropes": terrain["ropes"],
        }
    return scene
