#!/usr/bin/env python3
"""生成 bot 跨图寻路航点：调用客户端原生 world-map route，输出 JSON 航点表。

每个航点表示"在 map 地图走到 (x,y) 传送门并按上"。航点表写入角色的
`/work/bot/route.json`（宿主路径 `<workbench>/bot/route.json`），由
`bot/travel.lua` 执行。world-map 图不含出租车/船等脚本交通；遇到
`no_route` 时本工具返回非零并由调用方人工分段。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


class RouteError(Exception):
    """航点生成失败。"""


def workbench_command(workbench: str, *arguments: str) -> list[str]:
    return [str(Path(__file__).resolve().parents[1] / "workbenches/workbench"), workbench, *arguments]


def build_route(repo_root: Path, workbench: str, start: int, goal: int) -> list[dict[str, object]]:
    result = subprocess.run(
        workbench_command(workbench, "world-map", "route", str(start), str(goal)),
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RouteError(f"world-map 返回无效 JSON：{error}") from error
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict):
        raise RouteError(f"world-map 响应缺少 data：{result.stdout[:400]}")
    if data.get("status") != "ok" or not isinstance(data.get("legs"), list):
        raise RouteError(f"world-map 无可用路线：status={data.get('status')} error={data.get('error')}")
    waypoints: list[dict[str, object]] = []
    for leg in data["legs"]:
        if not isinstance(leg, dict):
            raise RouteError("world-map legs 中存在非对象项")
        portal_at = leg.get("portal_at")
        if not isinstance(portal_at, list) or not portal_at:
            raise RouteError(f"leg 缺少 portal_at：{leg}")
        x, y = portal_at[0]
        waypoints.append({"map": leg.get("from"), "portal": leg.get("portal"), "x": x, "y": y})
    return waypoints


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbench", help="live/NAME 或 dev/NAME")
    parser.add_argument("start", type=int, help="起点地图号")
    parser.add_argument("goal", type=int, help="终点地图号")
    parser.add_argument("--repo-root", type=Path, help="仓库根（默认按脚本位置推断）")
    parser.add_argument("--output", type=Path, help="输出 JSON 路径（默认打印）")
    args = parser.parse_args(argv)
    if not (args.workbench.startswith("live/") or args.workbench.startswith("dev/")):
        parser.error("workbench 必须是 live/NAME 或 dev/NAME")
    repo_root = args.repo_root or Path(__file__).resolve().parents[1]
    try:
        waypoints = build_route(repo_root, args.workbench, args.start, args.goal)
    except RouteError as error:
        print(f"路线生成失败：{error}", file=sys.stderr)
        return 1
    payload = {"from": args.start, "goal": args.goal, "legs": waypoints}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
