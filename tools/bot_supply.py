#!/usr/bin/env python3
"""养成补给与装备管理：按等级算缺口、就近商店补货、卖无用垃圾、装备建议。

子命令：
- `status WORKBENCH`：计算红药/蓝药/箭矢缺口，输出 JSON。
- `restock WORKBENCH [--dry-run]`：就近找药水商店并往返购买缺口（需要 GUI 后端）。
- `junk WORKBENCH [--dry-run|--apply] [--include-equipment]`：卖 etc 垃圾（默认只列举）。
- `gear WORKBENCH`：按等级输出武器/防具升级建议。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]

RED_POTION = 2000000
BLUE_POTION = 2000003
ARROW = 2060000

# 药水商店：map_id -> {npc 名称, 出售物品集合}
POTION_SHOPS: dict[int, dict[str, object]] = {
    100000102: {"npc": "卢娜", "items": {RED_POTION, BLUE_POTION}},
    1000003: {"npc": "露茜", "items": {RED_POTION, BLUE_POTION}},
}

# etc 类中绝不卖的物品（任务道具/任务卷轴），其余 etc 视为垃圾可卖
PROTECTED_ETC = {4000003, 4000004, 4000008, 4000010, 4000016, 4030000, 4161001}

# 任务/收藏装备不卖（可扩展）；已装备的由 equipped 动态排除
PROTECTED_EQUIPMENT: set[int] = set()

# 等级段补给目标：job_group -> [(min_level, max_level, red, blue, arrow)]
TARGETS: dict[int, list[tuple[int, int, int, int, int]]] = {
    3: [(10, 20, 25, 15, 600), (21, 40, 40, 30, 900), (41, 60, 60, 40, 1200)],
    4: [(10, 20, 20, 10, 0), (21, 40, 35, 20, 0), (41, 60, 50, 30, 0)],
}
DEFAULT_TARGETS = [(10, 20, 20, 10, 0), (21, 40, 35, 20, 0), (41, 60, 50, 30, 0)]

GEAR_TABLE: dict[int, list[tuple[int, str, str]]] = {
    3: [
        (15, "1452000 猎人弓 / 15 级弓", "武器店购买或任务"),
        (25, "1452001 战弓", "武器店购买"),
        (35, "1452002 火焰弓", "商店/任务"),
    ],
    4: [(20, "1332003 短剑", "武器店购买"), (30, "1332006 弯刀", "武器店购买")],
}
DEFAULT_GEAR = [(20, "20 级通用武器", "武器店购买"), (30, "30 级通用武器", "武器店购买")]


def workbench(workbench_name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REPO_ROOT / "workbenches/workbench"), workbench_name, *arguments],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def cli_json(workbench_name: str, *arguments: str) -> dict[str, object]:
    result = workbench(workbench_name, *arguments)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit(f"CLI 返回无效 JSON（{arguments}）：{result.stdout[:300]}") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise SystemExit(f"CLI 返回缺少 data（{arguments}）：{result.stdout[:300]}")
    return payload["data"]


def read_character(workbench_name: str) -> dict[str, int | str | None]:
    data = cli_json(workbench_name, "inspect", "character")
    character = data.get("character") if isinstance(data.get("character"), dict) else {}
    level = character.get("level")
    job = character.get("job")
    hp = character.get("hp")
    max_hp = character.get("max_hp")
    mp = character.get("mp")
    max_mp = character.get("max_mp")
    mesos = character.get("mesos")
    return {
        "level": level,
        "job": job,
        "hp": hp,
        "max_hp": max_hp,
        "mp": mp,
        "max_mp": max_mp,
        "mesos": mesos,
        "map_id": data.get("map_id"),
    }


def read_items(workbench_name: str) -> list[dict[str, object]]:
    data = cli_json(workbench_name, "inspect", "inventory")
    items = data.get("items")
    return items if isinstance(items, list) else []


def counted(items: list[dict[str, object]], item_id: int) -> int:
    total = 0
    for item in items:
        if item.get("item_id") == item_id:
            quantity = item.get("quantity")
            if isinstance(quantity, int):
                total += quantity
    return total


def targets_for(character: dict[str, int | str | None]) -> tuple[int, int, int]:
    level = character.get("level")
    job = character.get("job")
    if not isinstance(level, int) or not isinstance(job, int):
        raise SystemExit("角色等级/职业未知，无法计算补给目标")
    band = TARGETS.get(job // 100, DEFAULT_TARGETS)
    for minimum, maximum, red, blue, arrow in band:
        if level <= maximum:
            return red, blue, arrow
    last = band[-1]
    return last[2], last[3], last[4]


def supply_plan(workbench_name: str) -> dict[str, object]:
    character = read_character(workbench_name)
    items = read_items(workbench_name)
    red_goal, blue_goal, arrow_goal = targets_for(character)
    plan = {
        "level": character["level"],
        "job": character["job"],
        "hp": character["hp"],
        "mp": character["mp"],
        "mesos": character["mesos"],
        "map_id": character["map_id"],
        "items": {
            "red": {"have": counted(items, RED_POTION), "goal": red_goal},
            "blue": {"have": counted(items, BLUE_POTION), "goal": blue_goal},
            "arrow": {"have": counted(items, ARROW), "goal": arrow_goal},
        },
    }
    plan["gaps"] = {key: max(0, value["goal"] - value["have"]) for key, value in plan["items"].items()}
    plan["low"] = {
        "red": plan["items"]["red"]["have"] < 5,
        "blue": plan["items"]["blue"]["have"] < 3,
        "arrow": plan["items"]["arrow"]["have"] < 50,
    }
    plan["estimated_cost"] = plan["gaps"]["red"] * 50 + plan["gaps"]["blue"] * 100 + plan["gaps"]["arrow"] * 1
    return plan


def read_equipped(workbench_name: str) -> set[int]:
    data = cli_json(workbench_name, "inspect", "inventory")
    equipped = data.get("equipped")
    result: set[int] = set()
    for slot in equipped if isinstance(equipped, list) else []:
        item_id = slot.get("item_id") if isinstance(slot, dict) else None
        if isinstance(item_id, int):
            result.add(item_id)
    return result


def junk_list(workbench_name: str, include_equipment: bool = False) -> list[dict[str, object]]:
    """可卖清单：etc 垃圾 + 未装备的无用装备（任务/卷轴物品保护，已装备的绝不卖）。"""
    items = read_items(workbench_name)
    equipped = read_equipped(workbench_name) if include_equipment else set()
    result: list[dict[str, object]] = []
    for item in items:
        item_id = item.get("item_id")
        quantity = item.get("quantity")
        kind = item.get("inventory_type")
        if not isinstance(item_id, int) or not isinstance(quantity, int) or quantity <= 0:
            continue
        if kind == 4 and not is_protected(item_id):
            result.append({"item_id": item_id, "quantity": quantity})
        elif kind in (1, 3) and include_equipment and not is_protected(item_id) and item_id not in equipped:
            result.append({"item_id": item_id, "quantity": quantity, "equipment": True})
    return result


def is_protected(item_id: int) -> bool:
    """任务/卷轴/图鉴类保护；4000xxx 普通 etc 掉落不保护（除名单）。"""
    return item_id in PROTECTED_ETC or item_id in PROTECTED_EQUIPMENT or (4030000 <= item_id < 4100000)


def gear_advice(workbench_name: str) -> dict[str, object]:
    character = read_character(workbench_name)
    level = character.get("level")
    job = character.get("job")
    if not isinstance(level, int) or not isinstance(job, int):
        raise SystemExit("角色等级/职业未知，无法给出装备建议")
    rows = GEAR_TABLE.get(job // 100, DEFAULT_GEAR)
    suggestions = [{"level": row[0], "item": row[1], "source": row[2]} for row in rows if row[0] <= level + 5]
    return {"level": level, "job": job, "suggestions": suggestions}


def route_legs(workbench_name: str, start: int, goal: int) -> list[dict[str, object]]:
    data = cli_json(workbench_name, "world-map", "route", str(start), str(goal))
    if data.get("status") != "ok":
        raise SystemExit(f"world-map 无路线：{start} -> {goal}（{data.get('error')}）")
    legs = data.get("legs")
    return legs if isinstance(legs, list) else []


def nearest_potion_shop(workbench_name: str) -> tuple[int, dict[str, object]]:
    current = read_character(workbench_name).get("map_id")
    if not isinstance(current, int):
        raise SystemExit("当前地图未知")
    best: tuple[int, dict[str, object]] | None = None
    for shop_map, shop in POTION_SHOPS.items():
        if shop_map == current:
            return shop_map, shop
        try:
            legs = route_legs(workbench_name, current, shop_map)
        except SystemExit:
            continue
        if best is None or len(legs) < len(best[1]["legs"]):
            best = (shop_map, dict(shop, legs=legs))
    if best is None:
        raise SystemExit("当前地图没有可到达的药水商店")
    return best


def ensure_gui(workbench_name: str) -> None:
    role_directory = REPO_ROOT / "private/workbenches" / workbench_name
    workbench_file = role_directory / "workbench.json"
    config: dict[str, object] = {}
    if workbench_file.is_file():
        config = json.loads(workbench_file.read_text(encoding="utf-8"))
    if config.get("backend") == "beidou":
        return
    workbench(workbench_name, "close")
    config["backend"] = "beidou"
    workbench_file.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    workbench(workbench_name, "open")


def write_route(workbench_name: str, start: int, goal: int) -> Path:
    role_directory = REPO_ROOT / "private/workbenches" / workbench_name
    route_path = role_directory / "bot/route.json"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools/bot_route.py"),
            workbench_name,
            str(start),
            str(goal),
            "--output",
            str(route_path),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"生成航点失败：{result.stderr[-300:]}")
    return route_path


def travel(workbench_name: str, goal: int, timeout_seconds: int) -> None:
    write_route(workbench_name, read_character(workbench_name).get("map_id"), goal)
    result = workbench(workbench_name, "script", "run", "bot/travel.lua", "--seconds", str(timeout_seconds))
    if result.returncode != 0:
        raise SystemExit(f"跨图失败：{result.stdout[-400:]}")


def open_shop(workbench_name: str, npc_name: str) -> None:
    data = cli_json(workbench_name, "snapshot")
    npcs = data.get("npcs")
    for npc in npcs if isinstance(npcs, list) else []:
        if npc.get("name") == npc_name and npc.get("ref"):
            result = workbench(workbench_name, "click", str(npc["ref"]), "--double")
            if result.returncode != 0:
                raise SystemExit(f"打开商店失败：{result.stdout[-300:]}")
            return
    raise SystemExit(f"场景中未找到商店 NPC：{npc_name}")


def read_shop(workbench_name: str) -> dict[str, object]:
    return cli_json(workbench_name, "shop", "read")


def buy(workbench_name: str, item_id: int, count: int) -> dict[str, object]:
    return cli_json(workbench_name, "shop", "buy", str(item_id), "--count", str(count))


def sell(workbench_name: str, item_id: int, count: int) -> dict[str, object]:
    return cli_json(workbench_name, "shop", "sell", str(item_id), "--count", str(count))


def close_shop(workbench_name: str) -> None:
    workbench(workbench_name, "shop", "close")


def restock(workbench_name: str, dry_run: bool) -> dict[str, object]:
    plan = supply_plan(workbench_name)
    shop_map, shop = nearest_potion_shop(workbench_name)
    needs = {
        int(item_id): plan["gaps"][key]
        for item_id, key in ((RED_POTION, "red"), (BLUE_POTION, "blue"))
        if plan["gaps"][key] > 0
    }
    if needs.get(ARROW) is not None:
        needs.pop(ARROW, None)
    report: dict[str, object] = {
        "plan": plan,
        "shop_map": shop_map,
        "shop": shop.get("npc"),
        "buy": needs,
        "route_legs": len(shop.get("legs") or []),
    }
    if dry_run:
        report["dry_run"] = True
        return report
    ensure_gui(workbench_name)
    travel(workbench_name, shop_map, 240)
    open_shop(workbench_name, str(shop.get("npc")))
    shop_data = read_shop(workbench_name)
    available = {item.get("item_id") for item in shop_data.get("buy_items") or [] if isinstance(item, dict)}
    results = {}
    for item_id, count in needs.items():
        if item_id not in available:
            results[str(item_id)] = {"skipped": "not_sold_here"}
            continue
        try:
            results[str(item_id)] = buy(workbench_name, item_id, count)
        except SystemExit as error:
            results[str(item_id)] = {"error": str(error)}
    close_shop(workbench_name)
    travel(workbench_name, int(plan["map_id"]), 240) if isinstance(plan["map_id"], int) else None
    report["results"] = results
    report["after"] = supply_plan(workbench_name)
    return report


def do_junk(workbench_name: str, dry_run: bool, include_equipment: bool) -> dict[str, object]:
    candidates = junk_list(workbench_name, include_equipment)
    report: dict[str, object] = {"candidates": candidates, "dry_run": dry_run}
    if dry_run or not candidates:
        return report
    shop_map, shop = nearest_potion_shop(workbench_name)
    ensure_gui(workbench_name)
    travel(workbench_name, shop_map, 240)
    open_shop(workbench_name, str(shop.get("npc")))
    results = {}
    for candidate in candidates:
        try:
            results[str(candidate["item_id"])] = sell(
                workbench_name, int(candidate["item_id"]), int(candidate["quantity"])
            )
        except SystemExit as error:
            results[str(candidate["item_id"])] = {"error": str(error)}
    close_shop(workbench_name)
    report["results"] = results
    return report


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="计算补给缺口")
    status.add_argument("workbench")
    restock_parser = sub.add_parser("restock", help="就近买补给")
    restock_parser.add_argument("workbench")
    restock_parser.add_argument("--dry-run", action="store_true")
    junk_parser = sub.add_parser("junk", help="卖无用垃圾")
    junk_parser.add_argument("workbench")
    junk_parser.add_argument("--dry-run", action="store_true")
    junk_parser.add_argument("--apply", action="store_true")
    junk_parser.add_argument(
        "--include-equipment",
        action="store_true",
        help="仅人工确认时使用：把未装备的装备也列入清单/出售；自动化默认不卖装备",
    )
    gear = sub.add_parser("gear", help="装备升级建议")
    gear.add_argument("workbench")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "status":
            print(json.dumps(supply_plan(args.workbench), ensure_ascii=False, indent=2))
        elif args.command == "restock":
            print(json.dumps(restock(args.workbench, args.dry_run), ensure_ascii=False, indent=2))
        elif args.command == "junk":
            print(
                json.dumps(
                    do_junk(args.workbench, not args.apply, args.include_equipment), ensure_ascii=False, indent=2
                )
            )
        elif args.command == "gear":
            print(json.dumps(gear_advice(args.workbench), ensure_ascii=False, indent=2))
        return 0
    except SystemExit as error:
        print(f"补给工具失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
