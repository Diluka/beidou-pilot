#!/usr/bin/env python3
"""通过原生观察API读取任务记录，保留进度原文与未知状态。"""

import argparse
import json
from typing import Literal, TypedDict, cast

from ..observations import observe_domain


class QuestRecord(TypedDict):
    quest_id: int
    state: Literal["started", "completed", "unknown", "not_in_client_records"]
    progress: str | None


class QuestSnapshot(TypedDict):
    observed_at: str
    source: str
    readonly: bool
    quests: list[QuestRecord]
    unavailable: list[str]
    not_covered: list[str]
    read_seconds: float


def read_quests(quest_ids: list[int] | None = None) -> QuestSnapshot:
    report = cast(QuestSnapshot, observe_domain("quests"))
    if quest_ids:
        records = {record["quest_id"]: record for record in report["quests"]}
        report["quests"] = [records.get(quest_id, {
            "quest_id": quest_id,
            "state": "unknown" if report["unavailable"] else "not_in_client_records",
            "progress": None,
        }) for quest_id in quest_ids]
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quest-id", type=int, action="append", help="只查询指定任务，可重复")
    args = parser.parse_args()
    if args.quest_id and any(not 1 <= quest_id <= 65535 for quest_id in args.quest_id):
        parser.error("任务ID须为1至65535。")
    print(json.dumps(read_quests(args.quest_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
