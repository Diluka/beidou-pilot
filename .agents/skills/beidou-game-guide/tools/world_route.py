"""读取技能内的版本化世界图，输出免费和收费静态路线候选。"""
import json
from pathlib import Path
import sys

from route_graph import Edge, Scene, paid_route, route_text


def load_world(path: Path) -> dict[int, Scene]:
    """读取 v1 图：maps 含 id、name、link、edges；边含目标、脚本及坐标。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["version"] != 1:
        raise ValueError(f"不支持的世界图版本：{data['version']}")
    return {item["id"]: Scene(item["name"], item["link"], [
        Edge(edge["name"], edge["target"], edge["target_name"], edge["script"],
             edge["sources"], edge["receivers"]) for edge in item["edges"]
    ]) for item in data["maps"]}


def resolve(scenes: dict[int, Scene], value: str) -> int:
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
        raise SystemExit("用法: world_route.py 起点地图 终点地图")
    scenes = load_world(Path(__file__).resolve().parent.parent / "references/world-graph.json")
    start, goal = resolve(scenes, sys.argv[1]), resolve(scenes, sys.argv[2])
    print(json.dumps({"start": start, "goal": goal, "start_name": scenes[start].name,
                      "goal_name": scenes[goal].name, "route": route_text(scenes, start, goal),
                      "paid_candidates": {"lowest_listed_fare": paid_route(scenes, start, goal, 'cost'),
                                          "fewest_planning_legs": paid_route(scenes, start, goal, 'changes')},
                      "notice": "均为静态候选，不保证可达；费用假设无票、无折扣及无优惠券，持票或券会改变费用及路线。规划段数不是实际换图次数，飞艇一段包含候船和航行，售票到检票的通行未验证；实际服脚本、条件与运行状态未知。已有免费候选时，只列规划段数更少的付费方案；空结果不代表没有其他捷径。",
                      "source": "BeiDouMS/BeiDou-Server 00422c2 gms-server scripts-zh-CN/npc 与 scripts/event/Boats.js"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
