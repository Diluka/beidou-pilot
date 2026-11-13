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

北斗 V17 本地原版地图静态资源：场景是节点，传送门是有方向的候选边，并逐条列出名称、类型、坐标、目标和脚本字段；其他资源字段未收录。
坐标为场景世界坐标，未知字段保留 `None`。脚本门户、任务限制、地图内地形以及当前服配置可能改变实际通行结果。
`link` 仅记录引用，不推断其门户；实际能否走通尚未逐条实测。

- 区域是按地图号启发式分组的索引，不代表游戏官方区域划分；编号范围内未必每个 ID 都存在。
- `tools/world_route.py <起点地图> <终点地图>` 搜索已收录的静态有向门户候选路线，
  不覆盖 NPC、船、地铁和动态脚本。搜索结果不是实际可达保证；未找到不等于不可达。
- 查单张地图或当前地图的门户：`beidou-pilot inspect map [地图号]`；进门户：`beidou-pilot portal <门户名>`。
- 金银岛出租车、区域出租车及飞艇费用、NPC 和条件见路线工具的快捷候选；它们参考
  [BeiDou-Server 固定版本 00422c2](https://github.com/BeiDouMS/BeiDou-Server/tree/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc)，
  为源码静态推断，并非当前服已实测结果。

"""


def main() -> None:
    local_config = ROOT / "private/workbenches/resources.json"
    if "MAPLE_RESOURCES_CONFIG" not in os.environ and local_config.is_file():
        os.environ["MAPLE_RESOURCES_CONFIG"] = str(local_config)
    scenes = world_data(load_resources(Path(os.environ.get("CLIENT_ROOT", ROOT))).gui_client)
    regions = regions_of(scenes)
    body = [HEADER, "## 区域索引", "", index(regions), ""]
    region_dir = SKILL / "references/world-map"
    region_dir.mkdir(exist_ok=True)
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
