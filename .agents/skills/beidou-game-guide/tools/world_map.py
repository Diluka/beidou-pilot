"""重新生成技能内静态世界图资料：references/world-map.md、world-graph.json 与分册。

维护者重新生成时，通过 MAPLE_RESOURCES_CONFIG 或 CLIENT_ROOT 显式指定客户端资源；
日常浏览与路线查询不需要这些步骤：

    PYTHONDONTWRITEBYTECODE=1 python3 .agents/skills/beidou-game-guide/tools/world_map.py

读取本地原版 IMG 里每张地图的门户（名称、坐标、类型、目的地图与目的门户），按地图号归组为区域，
输出纯文本 graph：场景是节点，跨场景传送门是带坐标的边。

生成器只依赖本目录的 world_map_data.py，不导入 beidou_pilot 包，也不读取客户端运行状态。
需要共享 IMG 解析库，CI 生成的库不会留在检出目录里，本地运行时显式给出：

    BEIDOU_IMG_LIBRARY=<检出>/headless/build/libbeidou-img.so \
        MAPLE_RESOURCES_CONFIG=<检出>/private/workbenches/resources.json \
        PYTHONDONTWRITEBYTECODE=1 python3 .agents/skills/beidou-game-guide/tools/world_map.py

跨图路线只由客户端原生 `beidou-pilot world-map route START GOAL` 提供；本技能不包含路线计算。
"""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from world_map_data import display_regions, edges_of, game_data_root, index, region_section, regions_of, world_data  # noqa: E402

HEADER = """# 世界地图

北斗 V17 本地原版地图静态资源：场景是节点，传送门是有方向的候选边，并逐条列出名称、类型、坐标、目标和脚本字段；其他资源字段未收录。
坐标为场景世界坐标，未知字段保留 `None`。脚本门户、任务限制、地图内地形以及当前服配置可能改变实际通行结果。
`link` 仅记录引用，不推断其门户；实际能否走通尚未逐条实测。

- 世界地图展示索引取自客户端 `WorldMap*.img`；单一地图可能出现在多张图中，未展示的场景不推断归属。
  地图号分册是启发式索引，不代表官方区域划分；编号范围内未必每个 ID 都存在。
- 跨图路线只由客户端原生实现查询：`beidou-pilot world-map route <起点地图号> <终点地图号>`；
  该命令需要同目录已有运行中的客户端提供只读观察通道。本技能只有离线静态资料，不包含路线计算工具或付费交通候选。
- 查单张地图或当前地图的门户：`beidou-pilot inspect map [地图号]`。当前没有 CLI 进门户命令；进入门户要写用户 tick Lua，用 `player.move("up")` 等原生输入靠近并触发，再核对地图与落点。
- 金银岛出租车、区域出租车及飞艇的静态费用、NPC 和条件见 [交通攻略](transport.md)；它们参考
  [BeiDou-Server 固定版本 00422c2](https://github.com/BeiDouMS/BeiDou-Server/tree/00422c2ec4ccd915f71bbeaf6e38549dbe14efda/gms-server/scripts-zh-CN/npc)，
  为源码静态推断，单条出租车实测与限制也记录在该文。

"""


def main() -> None:
    game_data = game_data_root(Path(os.environ.get("CLIENT_ROOT", ROOT)))
    scenes = world_data(game_data)
    display = display_regions(game_data)
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
    (SKILL / "references/world-map.md").write_text("\n".join(body))
    print(json.dumps({"scenes": len(scenes), "regions": len(regions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
