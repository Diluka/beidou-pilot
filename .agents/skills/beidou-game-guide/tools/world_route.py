"""给出两张地图之间的换场景线路，只走静态资料里的门户。

用法（项目根执行，客户端资源路径取自 workbench 的 resources.json）：

    PYTHONDONTWRITEBYTECODE=1 python3 .agents/skills/beidou-game-guide/tools/world_route.py 起点地图号 终点地图号

起点或终点可以是地图名（如「天空之城」），重名时列出候选地图号。
线路只包含普通门户；港口乘船、地铁、任务脚本等跨大区通路不在其中。

需要共享 IMG 解析库，CI 生成的库不会留在检出目录里，本地运行时显式给出：

    BEIDOU_IMG_LIBRARY=<检出>/headless/build/libbeidou-img.so \
        PYTHONDONTWRITEBYTECODE=1 python3 .agents/skills/beidou-game-guide/tools/world_route.py 101000000 103000000

跨区域逐条查边、看每个场景全部门户时，直接用 `beidou-pilot inspect map <地图号>`。
"""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "cli"))

from beidou_pilot.resources import load_resources  # noqa: E402
from beidou_pilot.world_map import route_text, world_data  # noqa: E402


def resolve(scenes: dict[int, "object"], value: str) -> int:
    if value.isdecimal():
        return int(value)
    matches = [map_id for map_id, scene in scenes.items() if scene.name == value]
    if len(matches) == 1:
        return matches[0]
    names = "、".join(f"{map_id} {scenes[map_id].name}" for map_id in sorted(matches)[:8])
    raise SystemExit(f"「{value}」对应 {len(matches)} 张地图：{names}" if matches else f"找不到地图「{value}」。")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__ or "用法: world_route.py 起点地图 终点地图")
    os.environ["MAPLE_RESOURCES_CONFIG"] = str(ROOT / "private/workbenches/resources.json")
    scenes = world_data(load_resources(ROOT).gui_client)
    start, goal = resolve(scenes, sys.argv[1]), resolve(scenes, sys.argv[2])
    report = route_text(scenes, start, goal)
    print(json.dumps({"start": start, "goal": goal, "start_name": scenes[start].name,
                      "goal_name": scenes[goal].name, "route": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
