"""狩猎复用统一 Catalog 的静态地形，路线与实时控制留在 Lua。"""

from pathlib import Path
from typing import cast

from .catalog import Catalog
from .errors import ClientError, JsonObject


def load_hunt_terrain(client_root: Path, map_id: int) -> JsonObject:
    metadata = Catalog(client_root).map(map_id)
    source = metadata["geometry_source"]
    footholds, ropes = metadata["footholds"], metadata["ropes"]
    link = cast(JsonObject, metadata["info"]).get("link")
    if not footholds:
        raise ClientError(
            "hunt_terrain_unsupported" if link is not None else "hunt_terrain_unavailable",
            "地图没有可用的自身地形；不推断链接地图或空地形。",
            {"map_id": map_id, "source": source, "link": link},
        )
    for entries, required in ((footholds, ("id", "x1", "x2", "y1", "y2", "prev", "next")),
                              (ropes, ("index", "x", "y1", "y2"))):
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) or any(type(entry.get(field)) is not int for field in required)
            for entry in entries
        ):
            raise ClientError("hunt_terrain_invalid", "地图地形坐标或连接字段不完整。",
                              {"map_id": map_id, "source": source})
    return {"map_id": map_id, "footholds": footholds, "ropes": ropes, "source": source}
