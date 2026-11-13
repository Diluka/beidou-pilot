"""重新生成 references/world-map.md。

用法（项目根执行，客户端资源路径取自 workbench 的 resources.json）：

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

from beidou_pilot.resources import load_resources  # noqa: E402
from beidou_pilot.world_map import index, region_section, regions_of, route_text, world_data  # noqa: E402

HEADER = """# 世界地图

北斗 V17 本地原版地图的全部场景与传送门，按地图号归组为区域。场景是节点，跨场景传送门是边；
每条边写着入口门户名与入口坐标、目的地图，以及落点门户的坐标。坐标为场景内世界坐标，与游戏内落点可能有偏差。

- 地图通常十张一组、编号连续，`200000000`～`200090510` 同属一个区域；`200010000`、`201000000` 这类编号是
  同一组的次一级街区，归入最近的够大的一组。组队任务、道场楼层等重复副本并入它前面够大的区域。
- 游戏里换大区主要靠港口乘船、地铁、任务脚本和时空通路，这些不在门户 graph 里。需要精确线路时用
  `tools/world_route.py <起点地图> <终点地图>`，它只串纯门户能走通的换场景，跨大区会直接说明。
- 查单张地图或当前地图的门户：`beidou-pilot inspect map [地图号]`；进门户：`beidou-pilot portal <门户名>`。

"""


def main() -> None:
    os.environ["MAPLE_RESOURCES_CONFIG"] = str(ROOT / "private/workbenches/resources.json")
    scenes = world_data(load_resources(ROOT).gui_client)
    regions = regions_of(scenes)
    body = [HEADER, "## 区域索引", "", index(regions), ""]
    for region in regions:
        body += [region_section(region, scenes), ""]
    body += ["## 线路示例", "",
             "```", route_text(scenes, 100000000, 104000000), "```", "",
             "```", route_text(scenes, 200000000, 230000000), "```", ""]
    (SKILL / "references/world-map.md").write_text("\n".join(body))
    print(json.dumps({"scenes": len(scenes), "regions": len(regions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
