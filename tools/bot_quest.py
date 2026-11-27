#!/usr/bin/env python3
"""按任务条件打怪：读取原版 Quest.wz 目标，驱动 headless 客户端执行任务狩猎。

子命令：
- `objectives WORKBENCH`：列出已开始任务的击杀目标（mob id/count）与 NPC。
- `progress WORKBENCH QUEST_ID`：读取当前任务进度。
- `hunt WORKBENCH QUEST_ID [--seconds N] [--count N] [--heal-item ID]`：
  写角色 `bot/quest.conf` 并运行 `bot/quest_hunt.lua`，达到目标数或超时后停止。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quest_data import QuestDataError, QuestImages, quest_definition  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEST_DIRECTORY = REPO_ROOT / "private/client-assets/client/BeiDou-Client/Data/Quest"


class QuestToolError(Exception):
    """工具执行失败。"""


def workbench(workbench_name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(REPO_ROOT / "workbenches/workbench"), workbench_name, *arguments],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def role_directory(workbench_name: str) -> Path:
    if not (workbench_name.startswith("live/") or workbench_name.startswith("dev/")):
        raise QuestToolError(f"工作台必须是 live/NAME 或 dev/NAME：{workbench_name}")
    return REPO_ROOT / "private/workbenches" / workbench_name


def inspect_quests(workbench_name: str) -> list[dict[str, object]]:
    result = workbench(workbench_name, "inspect", "quests")
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise QuestToolError(f"inspect quests 返回无效 JSON：{result.stdout[:300]}") from error
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get("quests"), list):
        raise QuestToolError(f"inspect quests 响应缺少任务列表：{result.stdout[:300]}")
    return [record for record in data["quests"] if isinstance(record, dict)]


def quest_progress(workbench_name: str, quest_id: int) -> dict[str, object]:
    for record in inspect_quests(workbench_name):
        if record.get("quest_id") == quest_id:
            return record
    return {"quest_id": quest_id, "state": "not_in_client_records", "progress": None}


def quest_conf_path(workbench_name: str) -> Path:
    return role_directory(workbench_name) / "bot/quest.conf"


def write_conf(
    workbench_name: str, quest_id: int, mob_ids: list[int], count: int, heal_item: int | None, seconds: int
) -> Path:
    path = quest_conf_path(workbench_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    mob_list = ", ".join(str(mob_id) for mob_id in mob_ids)
    heal = f"    heal_item = {heal_item},\n" if heal_item is not None else ""
    path.write_text(
        "return {\n"
        f"    quest_id = {quest_id},\n"
        f"    mob_ids = {{{mob_list}}},\n"
        f"    count = {count},\n"
        f"    seconds = {seconds},\n"
        f"{heal}"
        "}\n",
        encoding="utf-8",
    )
    return path


def run_hunt(workbench_name: str, seconds: int) -> None:
    result = workbench(workbench_name, "script", "run", "bot/quest_hunt.lua", "--seconds", str(seconds))
    if result.returncode != 0:
        raise QuestToolError(f"quest_hunt 执行失败：{result.stdout[-500:] or result.stderr[-500:]}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quest-directory", type=Path, default=DEFAULT_QUEST_DIRECTORY, help="原版 Data/Quest 目录")
    sub = parser.add_subparsers(dest="command", required=True)
    objectives = sub.add_parser("objectives", help="列出已开始任务的击杀目标")
    objectives.add_argument("workbench")
    progress = sub.add_parser("progress", help="读取任务进度")
    progress.add_argument("workbench")
    progress.add_argument("quest_id", type=int)
    hunt = sub.add_parser("hunt", help="按任务目标打怪")
    hunt.add_argument("workbench")
    hunt.add_argument("quest_id", type=int)
    hunt.add_argument("--count", type=int, help="覆盖目标击杀数（默认取任务资料）")
    hunt.add_argument("--heal-item", type=int, help="HP 恢复品物品 ID")
    hunt.add_argument("--seconds", type=int, default=240, help="客户端内脚本时限（秒）")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "objectives":
            images = QuestImages(args.quest_directory)
            started = [record for record in inspect_quests(args.workbench) if record.get("state") == "started"]
            definitions = []
            for record in started:
                try:
                    definition = quest_definition(images, int(record["quest_id"]))
                except QuestDataError as error:
                    definition = {"quest_id": record["quest_id"], "error": str(error)}
                definition["state"] = record.get("state")
                definition["progress"] = record.get("progress")
                definitions.append(definition)
            print(json.dumps(definitions, ensure_ascii=False, indent=2))
            return 0
        if args.command == "progress":
            print(json.dumps(quest_progress(args.workbench, args.quest_id), ensure_ascii=False))
            return 0
        if args.command == "hunt":
            images = QuestImages(args.quest_directory)
            definition = quest_definition(images, args.quest_id)
            objectives = definition.get("objectives") or []
            if not objectives:
                raise QuestToolError(f"任务 {args.quest_id} 没有可执行的击杀目标：{definition}")
            mob_ids = [int(objective["mob_id"]) for objective in objectives]
            count = args.count if args.count is not None else int(objectives[0]["count"])
            write_conf(args.workbench, args.quest_id, mob_ids, count, args.heal_item, args.seconds)
            run_hunt(args.workbench, args.seconds)
            print(
                json.dumps(
                    {
                        "quest_id": args.quest_id,
                        "count": count,
                        "mob_ids": mob_ids,
                        "progress": quest_progress(args.workbench, args.quest_id),
                    },
                    ensure_ascii=False,
                )
            )
            return 0
    except QuestToolError as error:
        print(f"任务打怪失败：{error}", file=sys.stderr)
        return 1
    parser.error("未知子命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
