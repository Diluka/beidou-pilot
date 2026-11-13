"""给出两张地图之间的换场景线路，只走静态资料里的门户。

用法（项目根执行，客户端资源路径取自 workbench 的 resources.json）：

    PYTHONDONTWRITEBYTECODE=1 python3 .agents/skills/beidou-game-guide/tools/world_route.py 起点地图号 终点地图号

起点或终点可以是地图名（如「天空之城」），重名时列出候选地图号。
输出普通门户路线与已核实交通脚本的静态候选；实际通行、券和航班条件需现场核实。

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
if (ROOT / "cli").is_dir():
    sys.path.insert(0, str(ROOT / "cli"))

from beidou_pilot.resources import load_resources  # noqa: E402
from beidou_pilot.world_map import route_text, world_data  # noqa: E402
from beidou_pilot.world_transport import paid_route  # noqa: E402


def resolve(scenes: dict[int, "object"], value: str) -> int:
    if value.isdecimal():
        map_id = int(value)
        if map_id not in scenes:
            raise SystemExit(f"地图 {map_id} 没有门户数据，不在世界地图 graph 里。")
        return map_id
    matches = [map_id for map_id, scene in scenes.items() if scene.name == value]
    if len(matches) == 1:
        return matches[0]
    names = "、".join(f"{map_id} {scenes[map_id].name}" for map_id in sorted(matches)[:8])
    raise SystemExit(f"「{value}」对应 {len(matches)} 张地图：{names}" if matches else f"找不到地图「{value}」。")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__ or "用法: world_route.py 起点地图 终点地图")
    local_config = ROOT / "private/workbenches/resources.json"
    if "MAPLE_RESOURCES_CONFIG" not in os.environ and local_config.is_file():
        os.environ["MAPLE_RESOURCES_CONFIG"] = str(local_config)
    scenes = world_data(load_resources(Path(os.environ.get("CLIENT_ROOT", ROOT))).gui_client)
    start, goal = resolve(scenes, sys.argv[1]), resolve(scenes, sys.argv[2])
    report = route_text(scenes, start, goal)
    print(json.dumps({"start": start, "goal": goal, "start_name": scenes[start].name,
                      "goal_name": scenes[goal].name, "route": report,
                      "paid_candidates": {"lowest_listed_fare": paid_route(scenes, start, goal, 'cost'),
                                          "fewest_planning_legs": paid_route(scenes, start, goal, 'changes')},
                      "notice": "均为静态候选，不保证可达；费用假设无票、无折扣及无优惠券，持票或券会改变费用及路线。规划段数不是实际换图次数，飞艇一段包含候船和航行，售票到检票的通行未验证；实际服脚本、条件与运行状态未知。已有免费候选时，只列规划段数更少的付费方案；空结果不代表没有其他捷径。",
                      "source": "BeiDouMS/BeiDou-Server 00422c2 gms-server scripts-zh-CN/npc 与 scripts/event/Boats.js"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
