"""重新生成 references/world-map.md。

维护者重新生成时，通过 MAPLE_RESOURCES_CONFIG 显式指定资源配置；日常路线查询不需要资源：

    PYTHONDONTWRITEBYTECODE=1 python3 .agents/skills/beidou-game-guide/tools/world_map.py

读取本地原版 IMG 里每张地图的门户（名称、坐标、类型、目的地图与目的门户），按地图号归组为区域，
输出纯文本 graph：场景是节点，跨场景传送门是带坐标的边。

需要共享 IMG 解析库，CI 生成的库不会留在检出目录里，本地运行时显式给出：

    BEIDOU_IMG_LIBRARY=<检出>/headless/build/libbeidou-img.so \
        PYTHONDONTWRITEBYTECODE=1 python3 .agents/skills/beidou-game-guide/tools/world_map.py
"""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli"))

from beidou_pilot.world_map import display_regions, edges_of, index, region_section, regions_of, route_text, world_data  # noqa: E402

HEADER = """# 世界地图

北斗 V17 本地原版地图静态资源：场景是节点，传送门是有方向的候选边，并逐条列出名称、类型、坐标、目标和脚本字段；其他资源字段未收录。
坐标为场景世界坐标，未知字段保留 `None`。脚本门户、任务限制、地图内地形以及当前服配置可能改变实际通行结果。
`link` 仅记录引用，不推断其门户；实际能否走通尚未逐条实测。

- 世界地图展示索引取自客户端 `WorldMap*.img`；单一地图可能出现在多张图中，未展示的场景不推断归属。
  地图号分册是启发式索引，不代表官方区域划分；编号范围内未必每个 ID 都存在。
- `tools/world_route.py <起点地图> <终点地图>` 比较已收录的静态有向门户及部分出租车、飞艇候选；
  未覆盖的 NPC、地铁和动态脚本保留未知。搜索结果不是实际可达保证；未找到不等于不可达。
- 查单张地图或当前地图的门户：`beidou-pilot inspect map [地图号]`；进门户：`beidou-pilot portal <门户名>`。
- 金银岛出租车、区域出租车及飞艇费用、NPC 和条件见路线工具的快捷候选；它们参考
  [BeiDou-Server 固定版本 00422c2](https://github.com/BeiDouMS/BeiDou-Server/tree/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc)，
  为源码静态推断，单条出租车实测与限制见 [交通攻略](transport.md)。

"""


def main() -> None:
    resource_root = Path(os.environ.get("CLIENT_ROOT", ROOT))
    scenes = world_data(resource_root)
    display = display_regions(resource_root)
    if not scenes or not display:
        raise SystemExit("地图或世界地图资源不可用，未覆盖现有攻略。")
    regions = regions_of(scenes)
    graph = {"version": 1, "source": "北斗 V17 客户端静态地图资源，未经逐条实测", "maps": []}
    for map_id, scene in sorted(scenes.items()):
        graph["maps"].append({"id": map_id, "name": scene.name, "link": scene.link,
                              "edges": [{"name": edge.name, "target": edge.target,
                                         "target_name": edge.target_name, "script": edge.script,
                                         "sources": edge.sources, "receivers": edge.receivers}
                                        for edge in edges_of(scene, scenes)]})
    (SKILL / "references/world-graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    body = [HEADER, "## 客户端世界地图展示索引", "", "同一场景可在多张世界地图展示，不代表唯一归属。", ""]
    for name, ids in display.items():
        body.append(f"- [{name}](world-map/{name}.md)（{len(ids)} 个地图号）")
    body += ["", "## 地图号启发式分册（未归类备选）", "", index(regions), ""]
    region_dir = SKILL / "references/world-map"
    region_dir.mkdir(exist_ok=True)
    volume_of = {map_id: region.entity for region in regions for map_id in region.map_ids}
    for name, ids in display.items():
        lines = ["[返回世界地图索引](../world-map.md)", "", f"# {name}", "",
                 "客户端展示关系，不代表唯一归属；链接指向地图号分册，按地图号检索节点。", ""]
        for map_id in sorted(ids):
            if map_id in scenes:
                lines.append(f"- `{map_id}` {scenes[map_id].name} → [门户分册]({volume_of[map_id]:05d}.md)")
            else:
                lines.append(f"- `{map_id}`（客户端世界地图列出，但未找到对应场景文件）")
        (region_dir / f"{name}.md").write_text("\n".join(lines))
    for region in regions:
        (region_dir / f"{region.entity:05d}.md").write_text(
            "[返回世界地图索引](../world-map.md)\n\n" + region_section(region, scenes))
    body += ["## 线路示例", "",
             "```", route_text(scenes, 100000000, 104000000), "```", "",
             "```", route_text(scenes, 200000000, 230000000), "```", ""]
    (SKILL / "references/world-map.md").write_text("\n".join(body))
    print(json.dumps({"scenes": len(scenes), "regions": len(regions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
