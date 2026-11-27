#!/usr/bin/env python3
"""养成补给与装备管理：按等级算缺口、就近商店补货、卖无用垃圾、装备建议。

子命令：
- `status WORKBENCH`：计算红药/蓝药/箭矢缺口，输出 JSON。
- `restock WORKBENCH [--apply]`：默认预览；执行时售卖未保护 etc 并按上限购买（需要 GUI）。
- `junk WORKBENCH [--dry-run|--apply] [--include-equipment]`：卖 etc 垃圾（默认只列举）。
- `gear WORKBENCH`：按等级输出武器/防具升级建议。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import re

import os

WORKTREE = Path(__file__).resolve().parents[1]
REPO_ROOT = (
    Path(os.environ["BOT_SUPPLY_ROOT"])
    if "BOT_SUPPLY_ROOT" in os.environ
    else Path(
        subprocess.check_output(
            ["git", "-C", str(WORKTREE), "rev-parse", "--path-format=absolute", "--git-common-dir"], text=True
        ).strip()
    ).parent
)

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
    if result.returncode != 0:
        raise SystemExit(f"CLI 命令失败（{arguments}）：{result.stderr or result.stdout}")
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
    route_path = role_directory / "bot/route.supply.json"
    route_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            str(WORKTREE / "tools/bot_route.py"),
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
    result = workbench(workbench_name, "script", "run", "bot/supply_travel.lua", "--seconds", str(timeout_seconds))
    if result.returncode != 0:
        raise SystemExit(
            f"跨图失败，尚未购买；请先核对会话终态和当前位置，勿盲目重试。\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    if read_character(workbench_name).get("map_id") != goal:
        raise SystemExit("跨图终态未确认到达目标，尚未购买；请核对会话和当前位置，勿盲目重试。")


def open_shop(workbench_name: str, npc_name: str) -> None:
    if read_character(workbench_name).get("map_id") == 100000102 and npc_name == "卢娜":
        result = cli_json(workbench_name, "script", "run", "bot/shop_approach.lua", "--seconds", "40")
        script = result.get("script")
        if (
            result.get("status") != "completed"
            or not isinstance(script, dict)
            or script.get("control_released") is not True
        ):
            raise SystemExit(f"同平台接近未确认完成与放键，尚未购买；请核对位置和会话：{result}")
    cli_json(workbench_name, "talk", npc_name)
    if read_shop(workbench_name).get("open") is not True:
        raise SystemExit("商店打开未确认，尚未购买；请核对窗口和位置")


def read_shop(workbench_name: str) -> dict[str, object]:
    return cli_json(workbench_name, "shop", "read")


def buy(workbench_name: str, item_id: int, count: int) -> dict[str, object]:
    return cli_json(workbench_name, "shop", "buy", str(item_id), "--count", str(count))


def sell(workbench_name: str, item_id: int, count: int) -> dict[str, object]:
    return cli_json(workbench_name, "shop", "sell", str(item_id), "--count", str(count))


def close_shop(workbench_name: str) -> None:
    result = workbench(workbench_name, "shop", "close")
    if result.returncode != 0:
        raise SystemExit(f"关闭商店失败，保持停手并核对现场，交易可能已发生：{result.stdout} {result.stderr}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SystemExit("商店关闭结果不可读，保持停手并核对现场；交易可能已发生") from error
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("data"), dict)
        or payload["data"].get("closed") is not True
    ):
        raise SystemExit("商店关闭未确认，保持停手并核对现场；交易可能已发生")


def restock(
    workbench_name: str,
    dry_run: bool = True,
    max_cost: int = 5000,
    max_count: int = 1000,
    sell_etc: tuple[int, ...] = (),
    town_only: int | None = None,
) -> dict[str, object]:
    if max_cost < 0 or max_count < 1:
        raise SystemExit("金额上限须非负，数量上限须为正")
    plan = supply_plan(workbench_name)
    shop_map, shop = nearest_potion_shop(workbench_name)
    needs = {
        item_id: plan["gaps"][key]
        for item_id, key in ((RED_POTION, "red"), (BLUE_POTION, "blue"), (ARROW, "arrow"))
        if plan["gaps"][key] > 0
    }
    candidates = [item for item in junk_list(workbench_name) if item["item_id"] in sell_etc]
    report = {
        "plan": plan,
        "shop_map": shop_map,
        "shop": shop.get("npc"),
        "buy": needs,
        "sell_candidates": candidates,
        "max_cost": max_cost,
        "max_count": max_count,
        "dry_run": dry_run,
    }
    if town_only is not None and (plan["map_id"] != town_only or shop_map != town_only):
        raise SystemExit("当前位置或商店不在批准的安全城镇，未购买")
    if dry_run or not needs:
        return report
    if plan["map_id"] != shop_map:
        travel(workbench_name, shop_map, 240)
    try:
        open_shop(workbench_name, str(shop.get("npc")))
    except SystemExit as error:
        raise SystemExit(f"打开商店失败，尚未购买；请核对当前位置、脚本终态和窗口：{error}") from error
    results = {"sell": [], "buy": []}
    report["results"] = results
    try:
        for candidate in candidates:
            # 多堆同一物品时 CLI 会拒绝歧义；不猜测槽位或重试交易。
            results["sell"].append(
                sell(workbench_name, int(candidate["item_id"]), min(int(candidate["quantity"]), 1000))
            )
        wallet = read_character(workbench_name).get("mesos")
        if not isinstance(wallet, int) or wallet < 0:
            raise SystemExit("金币读数不可用")
        budget = min(max_cost, wallet)
        quantity_left = max_count
        shop_data = read_shop(workbench_name)
        for item_id, needed in needs.items():
            matches = [item for item in shop_data.get("buy_items", []) if item.get("item_id") == item_id]
            if len(matches) != 1:
                raise SystemExit(f"商店未提供唯一商品：{item_id}")
            item = matches[0]
            price = item.get("unit_price")
            if not isinstance(price, int) or price < 0 or item.get("bundle_quantity") != 1:
                raise SystemExit(f"商品价格或数量不受支持：{item_id}")
            count = min(needed, quantity_left, 1000, budget // price if price else quantity_left)
            if count <= 0:
                raise SystemExit(f"预算或数量上限不足：{item_id}")
            transaction = buy(workbench_name, item_id, count)
            before, after = transaction.get("quantity_before"), transaction.get("quantity_after")
            money_before, money_after = transaction.get("mesos_before"), transaction.get("mesos_after")
            if (
                transaction.get("completed") is not True
                or type(before) is not int
                or type(after) is not int
                or type(money_before) is not int
                or type(money_after) is not int
                or after - before != count
                or money_before - money_after != price * count
            ):
                raise SystemExit(f"购买结果未确认，可能已交易，请勿重放：{transaction}")
            results["buy"].append(transaction)
            budget -= price * count
            quantity_left -= count
            if count < needed:
                raise SystemExit(f"预算或数量上限不足：{item_id}")
        after = supply_plan(workbench_name)
        report["after"] = after
        if any(after["gaps"][key] for key in ("red", "blue", "arrow")):
            raise SystemExit("补货后库存仍有缺口")
    finally:
        close_shop(workbench_name)
    # 自动回图留给后续闭环编排；失败时绝不离开商店。
    return report


def supply_cycle(workbench_name: str, session_id: str, apply: bool, watch_seconds: int) -> dict[str, object]:
    """仅在明确授权的城镇交易，逐段验证回图路线；一次会话最多执行一次。"""
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", session_id):
        raise SystemExit("会话 ID 无效")
    if not re.fullmatch(r"(?:live|dev)/[a-zA-Z0-9_-]+", workbench_name):
        raise SystemExit("工作台名称无效")
    if watch_seconds < 0:
        raise SystemExit("等待时间须非负")
    bot_dir = REPO_ROOT / "private/workbenches" / workbench_name / "bot"
    config_path = bot_dir / "supply_host.json"
    if not config_path.is_file():
        raise SystemExit("未配置安全城镇和路线白名单；未移动、未购买")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    towns, allowed = config.get("safe_towns"), config.get("allowed_legs")
    if (
        not isinstance(towns, list)
        or not towns
        or any(type(x) is not int for x in towns)
        or not isinstance(allowed, list)
    ):
        raise SystemExit("安全城镇或路线白名单无效；未移动、未购买")
    for leg in allowed:
        if (
            not isinstance(leg, dict)
            or type(leg.get("from")) is not int
            or type(leg.get("to")) is not int
            or not isinstance(leg.get("portal"), str)
        ):
            raise SystemExit("路线白名单无效；未移动、未购买")
    deadline = time.monotonic() + watch_seconds
    while True:
        event = None
        for path in (bot_dir / "events.1.jsonl", bot_dir / "events.jsonl"):
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(entry, dict)
                    and entry.get("type") == "supply/low"
                    and isinstance(entry.get("data"), dict)
                    and entry["data"].get("session_id") == session_id
                ):
                    event = entry["data"]
        if event:
            break
        if time.monotonic() >= deadline:
            raise SystemExit("未发现指定会话的低补给事件；未移动、未购买")
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    if event.get("reason") != "low":
        raise SystemExit(f"补给观察或配置异常：{event.get('reason')}；未移动、未购买")
    low_items = event.get("items")
    if (
        not isinstance(low_items, list)
        or not low_items
        or any(
            not isinstance(item, dict)
            or type(item.get("item_id")) is not int
            or type(item.get("threshold")) is not int
            or item["threshold"] <= 0
            for item in low_items
        )
    ):
        raise SystemExit("低补给事件缺少有效阈值；未移动、未购买")
    while True:
        status = cli_json(workbench_name, "script", "status", "--session", session_id)
        script = status.get("script")
        if (
            isinstance(script, dict)
            and script.get("id") == session_id
            and script.get("status") == "completed"
            and script.get("control_released") is True
        ):
            break
        if time.monotonic() >= deadline:
            raise SystemExit("低补给会话尚未正常结束并确认放键；未移动、未购买")
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    scripts = status.get("scripts")
    if not isinstance(scripts, list) or any(not isinstance(s, dict) or s.get("status") == "running" for s in scripts):
        raise SystemExit("仍有活动脚本或脚本状态不完整；未移动、未购买")
    character = read_character(workbench_name)
    town = character.get("map_id")
    if type(town) is not int or town not in towns:
        raise SystemExit("角色不在白名单安全城镇；未移动、未购买")
    shop_map, _ = nearest_potion_shop(workbench_name)
    if shop_map != town:
        raise SystemExit("安全城镇内没有已配置的商店；未移动、未购买")
    plan_path = bot_dir / "plan.conf"
    plan_text = plan_path.read_text(encoding="utf-8") if plan_path.is_file() else ""
    matches = re.findall(r"^\s*hunt_map\s*=\s*(\d+)\s*$", plan_text, re.MULTILINE)
    if len(matches) != 1:
        raise SystemExit("狩猎地图绑定缺失或不唯一；未移动、未购买")
    hunt_map = int(matches[0])
    receipt = bot_dir / ("supply-cycle-" + session_id + ".json")
    if receipt.exists():
        raise SystemExit("此会话已有补给记录；请核对现场，勿重放")
    report = {"session_id": session_id, "town": town, "hunt_map": hunt_map, "dry_run": not apply}
    if not apply:
        report["restock"] = restock(workbench_name, town_only=town)
        return report
    # 写入不可覆盖的开始记录；崩溃或部分交易后不自动重放。
    try:
        with receipt.open("x", encoding="utf-8") as file:
            json.dump({"status": "started", **report}, file, ensure_ascii=False)
    except FileExistsError as error:
        raise SystemExit("此会话已被处理，禁止重放") from error
    report["restock"] = restock(workbench_name, dry_run=False, town_only=town)
    items = read_items(workbench_name)
    if any(counted(items, item["item_id"]) < item["threshold"] for item in low_items):
        raise SystemExit("补货后仍低于事件阈值，保持停手")
    if read_character(workbench_name).get("map_id") != town:
        raise SystemExit("交易后位置已变化；停止回图")
    command = [sys.executable, str(WORKTREE / "tools/botctl")]
    result = subprocess.run(
        [*command, "plan", workbench_name, "--hunt-map", str(hunt_map)], text=True, capture_output=True
    )
    if result.returncode:
        raise SystemExit(f"补货后生成回图路线失败，保持停手：{result.stdout} {result.stderr}")
    route = json.loads((bot_dir / "route.json").read_text(encoding="utf-8"))
    legs = route.get("legs")
    if route.get("from") != town or route.get("goal") != hunt_map or not isinstance(legs, list):
        raise SystemExit("回图路线身份不匹配，保持停手")
    if (town != hunt_map and not legs) or (legs and (not isinstance(legs[0], dict) or legs[0].get("map") != town)):
        raise SystemExit("回图路线为空或起点不匹配，保持停手")
    if any(not isinstance(leg, dict) for leg in legs):
        raise SystemExit("回图路线无效，保持停手")
    for index, leg in enumerate(legs):
        destination = legs[index + 1].get("map") if index + 1 < len(legs) else hunt_map
        if {"from": leg.get("map"), "to": destination, "portal": leg.get("portal")} not in allowed:
            raise SystemExit("回图路线包含未授权地图或传送门，保持停手")
    for args in (("start", workbench_name), ("send", workbench_name, "--kind", "hunt")):
        result = subprocess.run([*command, *args], text=True, capture_output=True)
        if result.returncode:
            raise SystemExit(f"补货后恢复失败；请核对机器人会话：{result.stdout} {result.stderr}")
    report["status"] = "resume_requested"
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    mode = restock_parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    restock_parser.add_argument("--max-cost", type=int, default=5000)
    restock_parser.add_argument("--max-count", type=int, default=1000)
    restock_parser.add_argument(
        "--sell-etc", type=int, action="append", default=[], help="人工确认可出售的 etc 物品 ID，可重复"
    )
    cycle = sub.add_parser("cycle", help="等待低补给事件并按白名单补货回图")
    cycle.add_argument("workbench")
    cycle.add_argument("--session", required=True)
    cycle.add_argument("--apply", action="store_true")
    cycle.add_argument("--watch-seconds", type=int, default=0)
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
            print(
                json.dumps(
                    restock(args.workbench, not args.apply, args.max_cost, args.max_count, tuple(args.sell_etc)),
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command == "cycle":
            print(
                json.dumps(
                    supply_cycle(args.workbench, args.session, args.apply, args.watch_seconds),
                    ensure_ascii=False,
                    indent=2,
                )
            )
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
