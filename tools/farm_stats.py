#!/usr/bin/env python3
"""Aggregate schema-1 farming observations without external dependencies.

Durations are seconds; rates are per minute. Missing and null measurements are
unknown, not zero. A group with an unknown contribution has an unknown total.
Only the named metrics snapshot is read: rotated snapshots may overlap, and
events cannot be reliably assigned to groups by this schema, so neither is merged.
"""

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


NUMBERS = ("kills", "kill_time_sum", "kill_time_samples", "exp", "hp_potions",
           "mp_potions", "arrows", "damage_taken", "deaths", "stuck_events",
           "dwell_time", "entries", "exp_unknown_kills")
DROPS = ("drops_seen", "drops_picked")
DIMENSIONS = ("map_id", "platform", "mob_template")


def aggregate(document, goal="balance"):
    """Return grouped raw counts and per-minute rates, without recommendations."""
    if not isinstance(document, dict) or type(document.get("schema")) is not int or document["schema"] != 1:
        raise ValueError("schema must be 1")
    records = document.get("records")
    if not isinstance(records, list):
        raise ValueError("records must be an array")
    if goal not in ("exp", "loot", "balance"):
        raise ValueError("invalid goal")

    def number(value, field):
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError(f"{field} must be a non-negative finite number or null")
        return value

    grouped = defaultdict(list)
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"records[{index}] must be an object")
        key = tuple(record.get(field) for field in DIMENSIONS)
        if any(value is not None and type(value) not in (str, int) for value in key):
            raise ValueError(f"records[{index}] dimensions must be strings, integers or null")
        values = {field: number(record.get(field, record.get("dwell_s") if field == "dwell_time" else None), field) for field in NUMBERS}
        complete = record.get("complete")
        if complete is not None and type(complete) is not bool:
            raise ValueError("complete must be a boolean or null")
        values["complete"] = complete
        values["window"] = {field: record.get(field) for field in ("sample_windows", "estimated", "window_start", "window_end", "scene_generation", "complete", "completeness_reason", "arrival_reason", "exit_reason", "visit_start", "visit_end", "collection_policy", "policy_seed", "entries")}
        for field in DROPS:
            drops = record.get(field)
            if drops is not None:
                if not isinstance(drops, dict):
                    raise ValueError(f"{field} must be an object or null")
                drops = {item: number(count, field) for item, count in drops.items()}
            values[field] = drops
        grouped[key].append(values)

    def sum_rows(rows):
        totals = {}
        for field in NUMBERS:
            values = [row[field] for row in rows]
            totals[field] = sum(values) if all(value is not None for value in values) else None
        for field in DROPS:
            if any(row[field] is None for row in rows):
                totals[field] = None
                continue
            items = set().union(*(row[field] for row in rows))
            totals[field] = {}
            for item in sorted(items):
                counts = [row[field].get(item, 0) for row in rows]
                totals[field][item] = sum(counts) if all(count is not None for count in counts) else None

        return totals

    groups = []
    for key, rows in grouped.items():
        raw_totals = sum_rows(rows)
        complete_rows = [row for row in rows if row["complete"] is True]
        totals = sum_rows(complete_rows) if complete_rows else {field: None for field in NUMBERS + DROPS}
        dwell = totals["dwell_time"]
        kills = totals["kills"]
        sufficient = kills is not None and kills >= 5 and dwell is not None and dwell >= 60
        rates = {}
        for field in ("kills", "exp", "hp_potions", "mp_potions", "arrows", "damage_taken", "deaths", "stuck_events"):
            value = totals[field]
            rates[field] = value * 60 / dwell if value is not None and sufficient else None
        for field in DROPS:
            values = totals[field]
            rates[field] = (None if values is None else {
                item: count * 60 / dwell if count is not None and sufficient else None
                for item, count in values.items()
            })
        samples = totals["kill_time_samples"]
        kill_time = totals["kill_time_sum"]
        average = kill_time / samples if kill_time is not None and samples is not None and samples > 0 else None
        pickup = totals["drops_picked"]
        loot_rate = (sum(pickup.values()) * 60 / dwell
                     if pickup is not None and all(value is not None for value in pickup.values())
                     and sufficient else None)
        reasons = []
        if dwell is None:
            reasons.append("dwell_time unknown")
        elif dwell < 60:
            reasons.append("insufficient dwell_time")
        if kills is None:
            reasons.append("kills unknown")
        elif kills < 5:
            reasons.append("insufficient kills")
        if len(complete_rows) != len(rows):
            reasons.append("incomplete or unknown windows excluded from rates")
        if samples is None or kill_time is None:
            reasons.append("kill time unknown")
        elif samples == 0:
            reasons.append("insufficient kill time samples")
        if rates["exp"] is None:
            reasons.append("exp rate unknown or insufficient dwell_time")
        if loot_rate is None:
            reasons.append("loot rate unknown or insufficient dwell_time")
        groups.append({**dict(zip(DIMENSIONS, key)), "records": len(rows), "totals": raw_totals,
                       "complete_totals": totals, "sample_windows": len(complete_rows),
                       "windows": [row["window"] for row in rows], "insufficient": not sufficient,
                       "rates_per_minute": rates, "average_kill_time": average,
                       "loot_per_minute": loot_rate, "notes": reasons})

    return {"schema": 1, "goal": goal, "groups": groups}


def input_path(value):
    """Resolve a dev role using the repository common git directory."""
    if not value.startswith("dev/"):
        return Path(value)
    name = value[4:]
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError("role must be dev/NAME without path separators")
    worktree = Path(__file__).resolve().parent.parent
    marker = worktree / ".git"
    if marker.is_dir():
        common = marker
    else:
        marker_text = marker.read_text(encoding="utf-8").strip()
        if not marker_text.startswith("gitdir: "):
            raise ValueError("invalid .git file")
        gitdir = (worktree / marker_text[8:]).resolve()
        common_file = gitdir / "commondir"
        common = (gitdir / common_file.read_text(encoding="utf-8").strip()).resolve() if common_file.exists() else gitdir
    roles = common.parent / "private" / "workbenches" / "dev"
    role = (roles / name).resolve()
    if role.parent != roles.resolve():
        raise ValueError("role must remain inside the dev workbenches directory")
    return role / "bot" / "metrics.json"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aggregate schema-1 farming metrics; durations are seconds")
    parser.add_argument("path", help="metrics.json path or dev/NAME role")
    parser.add_argument("--goal", choices=("exp", "loot", "balance"), default="balance",
                        help="label the report; does not change metrics or rank groups")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    args = parser.parse_args(argv)
    try:
        with input_path(args.path).open(encoding="utf-8") as source:
            result = aggregate(json.load(source), args.goal)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(f"Goal label: {args.goal}; groups are in input order, not ranked")
        for index, group in enumerate(result["groups"]):
            print(f"[{index}] map={group['map_id']} platform={group['platform']} mob={group['mob_template']}")
            print(f"  exp/minute: {group['rates_per_minute']['exp'] if group['rates_per_minute']['exp'] is not None else 'unknown'}; loot/minute: {group['loot_per_minute'] if group['loot_per_minute'] is not None else 'unknown'}")
            print(f"  average kill time: {group['average_kill_time'] if group['average_kill_time'] is not None else 'unknown'}; notes: {', '.join(group['notes']) or 'none'}")
            print(f"  raw totals: {json.dumps(group['totals'], ensure_ascii=False)}")
            print(f"  rates/minute: {json.dumps(group['rates_per_minute'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
