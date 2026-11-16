#!/usr/bin/env python3
"""离线比较两端本地角色物理末态校准记录，不做运动计算、插值或轨迹平移。"""

import argparse
import json
import math
from pathlib import Path
import sys
from typing import TypedDict

PREFIX = "BEIDOU_MOTION_CAL v1 "
DEFAULT_THRESHOLDS = {"trajectory_px": 1.0, "speed_px_s": 1.0, "contact_steps": 1}


class CompareError(Exception):
    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class EvidenceError(CompareError):
    """记录可读，但不足以按真实更新号对齐；输出证据不足并要求重采。"""


class Series(TypedDict):
    records: int
    unique_updates: int
    duplicates: int
    step_ms: int | None
    map_id: int | None
    scene_generation: int | None
    edge_update_id: int
    edge_input: str
    input_edges: list[dict[str, object]]
    edge_inputs: list[str]
    first_step: int
    last_step: int
    gaps: list[int]
    missing_physics: int
    ground_unknown: int
    takeoffs: list[int]
    landings: list[int]


def _number(value: object) -> float | None:
    if type(value) is int or type(value) is float:
        if math.isfinite(value):
            return float(value)
    return None


def _integer(value: object) -> int | None:
    return value if type(value) is int else None


def records_from_text(text: str) -> list[dict[str, object]]:
    """读取原始脚本事件日志或已抽取的 JSONL；只保留稳定前缀的校准记录。"""
    records: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        payload: str | None = None
        if stripped.startswith(PREFIX):
            payload = stripped
        elif stripped.startswith("{"):
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as error:
                raise CompareError(f"第 {number} 行不是有效 JSON。", {"line": number, "reason": error.msg}) from error
            if not isinstance(value, dict):
                continue
            text_value = value.get("text")
            if isinstance(text_value, str):
                payload = text_value.strip()
            elif "event" in value and "scenario" in value:
                # 已抽取的 JSONL 只含记录对象，同一稳定前缀语义。
                payload = PREFIX + stripped
        if payload is None or not payload.startswith(PREFIX):
            continue
        try:
            record = json.loads(payload[len(PREFIX) :])
        except json.JSONDecodeError as error:
            raise CompareError(f"第 {number} 行的校准记录不是有效 JSON。", {"line": number}) from error
        if not isinstance(record, dict):
            raise CompareError(f"第 {number} 行的校准记录不是对象。", {"line": number})
        records.append(record)
    if not records:
        raise CompareError("输入中没有校准记录。", {"prefix": PREFIX})
    return records


def load_records(path: Path) -> list[dict[str, object]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise CompareError("无法读取校准记录。", {"path": str(path), "reason": str(error)}) from error
    return records_from_text(text)


def _record_scene(record: dict[str, object]) -> tuple[int | None, int | None]:
    scene = record.get("scene")
    if not isinstance(scene, dict):
        return None, None
    return _integer(scene.get("map_id")), _integer(scene.get("scene_generation"))


def _physics(record: dict[str, object]) -> dict[str, object] | None:
    value = record.get("physics")
    return value if isinstance(value, dict) else None


def _pose(record: dict[str, object]) -> tuple[float, float] | None:
    physics = _physics(record)
    if physics is None:
        return None
    x, y = _number(physics.get("x")), _number(physics.get("y"))
    if x is None or y is None:
        return None
    return x, y


def _velocity(record: dict[str, object]) -> tuple[float, float] | None:
    physics = _physics(record)
    if physics is None:
        return None
    velocity = physics.get("velocity")
    if not isinstance(velocity, dict):
        return None
    x, y = _number(velocity.get("x")), _number(velocity.get("y"))
    if x is None or y is None:
        return None
    return x, y


def _ground(record: dict[str, object]) -> bool | None:
    physics = _physics(record)
    if physics is None:
        return None
    return physics.get("on_ground") if type(physics.get("on_ground")) is bool else None


def _require_single(records: list[dict[str, object]], field: str) -> object:
    values = {record.get(field) for record in records}
    if len(values) != 1:
        raise EvidenceError(f"一份记录内的 {field} 不一致。", {"field": field, "values": sorted(map(str, values))})
    return values.pop()


def _dedupe_series(
    records: list[dict[str, object]], side: str
) -> tuple[dict[int, dict[str, object]], dict[str, object]]:
    ticks = [record for record in records if record.get("event") == "tick"]
    if not ticks:
        raise CompareError(f"{side} 没有 tick 采样记录。", {"side": side})
    scenario = _require_single(ticks, "scenario")
    direction = _require_single(ticks, "direction")
    map_id = scene_generation = None
    samples: dict[int, dict[str, object]] = {}
    order: list[int] = []
    duplicates = 0
    gaps: list[int] = []
    missing_physics = 0
    last_update: int | None = None
    for record in ticks:
        record_map, record_generation = _record_scene(record)
        if record_map is not None:
            if map_id is not None and record_map != map_id:
                raise EvidenceError(f"{side} 记录跨越了地图。", {"side": side, "map_id": [map_id, record_map]})
            map_id = record_map
        if record_generation is not None:
            if scene_generation is not None and record_generation != scene_generation:
                raise EvidenceError(f"{side} 记录跨越了场景代次。", {"side": side})
            scene_generation = record_generation
        physics = _physics(record)
        update_id = _integer(physics.get("update_id")) if physics is not None else None
        if update_id is None:
            missing_physics += 1
            continue
        if update_id in samples:
            duplicates += 1
            previous = samples[update_id]
            if _physics(previous) != physics:
                raise EvidenceError(
                    f"{side} 在同一个 update_id 内出现了不同的物理样本。",
                    {"side": side, "update_id": update_id},
                )
            continue
        if last_update is not None and update_id < last_update:
            raise EvidenceError(f"{side} 的 update_id 回退。", {"side": side, "update_id": update_id})
        if last_update is not None and update_id > last_update + 1:
            gaps.extend(range(last_update + 1, update_id))
        last_update = update_id
        samples[update_id] = record
        order.append(update_id)
    step_ms_values = {_integer((_physics(samples[update]) or {}).get("step_ms")) for update in order}
    if len(step_ms_values) != 1 or None in step_ms_values:
        raise EvidenceError(f"{side} 的 step_ms 不唯一或未知。", {"side": side})
    edges = _edges(samples, order, side)
    edge_update = edges[0]
    prepared = {update: samples[update] for update in order if update >= edge_update}
    takeoffs, landings = _contacts(prepared)
    ground_unknown = sum(1 for record in prepared.values() if _ground(record) is None)
    series: Series = {
        "records": len(ticks),
        "unique_updates": len(order),
        "duplicates": duplicates,
        "step_ms": step_ms_values.pop(),
        "map_id": map_id,
        "scene_generation": scene_generation,
        "edge_update_id": edge_update,
        "edge_input": str(samples[edge_update].get("input")),
        "input_edges": [{"update_id": update, "input": str(samples[update].get("input"))} for update in edges],
        "first_step": 0,
        "last_step": order[-1] - edge_update,
        "gaps": gaps,
        "missing_physics": missing_physics,
        "ground_unknown": ground_unknown,
        "takeoffs": takeoffs,
        "landings": landings,
    }
    return prepared, {
        "scenario": scenario,
        "direction": direction,
        "series": series,
        "edges": edges,
    }


def _edges(samples: dict[int, dict[str, object]], order: list[int], side: str) -> list[int]:
    """实际输入消费边沿：每次意图变化后的第一份物理样本。"""
    edges = [update for update in order if samples[update].get("intent_edge") is True]
    if not edges:
        raise EvidenceError(f"{side} 没有输入意图边沿。", {"side": side})
    return edges


def _contacts(samples: dict[int, dict[str, object]]) -> tuple[list[int], list[int]]:
    """按去重后的物理步序号返回离地与落地边沿。"""
    order = sorted(samples)
    takeoffs: list[int] = []
    landings: list[int] = []
    previous: bool | None = None
    for update in order:
        ground = _ground(samples[update])
        if ground is None:
            previous = None
            continue
        if previous is not None and previous != ground:
            if ground:
                landings.append(update - order[0])
            else:
                takeoffs.append(update - order[0])
        previous = ground
    return takeoffs, landings


def _segments(samples: dict[int, dict[str, object]], edges: list[int]) -> list[dict[int, dict[str, object]]]:
    """按输入消费边沿切段，段内用相对物理步序号索引。"""
    segments: list[dict[int, dict[str, object]]] = []
    for index, start in enumerate(edges):
        end = edges[index + 1] if index + 1 < len(edges) else None
        segment = {
            update - start: record
            for update, record in sorted(samples.items())
            if update >= start and (end is None or update < end)
        }
        segments.append(segment)
    return segments


def _compare_metric(
    name: str,
    left: dict[int, dict[str, object]],
    right: dict[int, dict[str, object]],
    left_edges: list[int],
    right_edges: list[int],
    extract,
    limit: float,
) -> dict[str, object]:
    left_segments = _segments(left, left_edges)
    right_segments = _segments(right, right_edges)
    if len(left_segments) != len(right_segments):
        return {"status": "insufficient", "reason": "input_edges_mismatch"}
    value_limit = 0.0
    worst_step = 0
    worst_segment = 0
    samples = 0
    for index, (left_segment, right_segment) in enumerate(zip(left_segments, right_segments)):
        if 0 not in left_segment or 0 not in right_segment:
            return {"status": "insufficient", "reason": "edge_sample_missing", "segment": index}
        overlap_end = min(max(left_segment), max(right_segment))
        missing = [step for step in range(0, overlap_end + 1) if step not in left_segment or step not in right_segment]
        if missing:
            return {
                "status": "insufficient",
                "reason": "update_samples_missing",
                "missing_steps": missing[:32],
                "segment": index,
            }
        origin_left, origin_right = extract(left_segment[0]), extract(right_segment[0])
        if name == "trajectory" and (origin_left is None or origin_right is None):
            return {"status": "insufficient", "reason": "origin_unknown", "segment": index}
        if overlap_end < 1:
            return {"status": "insufficient", "reason": "overlap_too_small", "segment": index}
        for step in range(0, overlap_end + 1):
            left_value = extract(left_segment[step])
            right_value = extract(right_segment[step])
            if left_value is None or right_value is None:
                return {"status": "insufficient", "reason": "value_unknown", "segment": index, "step": step}
            if name == "trajectory":
                delta = math.hypot(
                    left_value[0] - origin_left[0] - (right_value[0] - origin_right[0]),
                    left_value[1] - origin_left[1] - (right_value[1] - origin_right[1]),
                )
            elif name == "velocity":
                delta = math.hypot(left_value[0] - right_value[0], left_value[1] - right_value[1])
            else:
                raise AssertionError(name)
            if delta > value_limit:
                value_limit = delta
                worst_step = step
                worst_segment = index
            samples += 1
    return {
        "status": "passed" if value_limit <= limit else "failed",
        "max_delta": value_limit,
        "limit": limit,
        "worst_step": worst_step,
        "worst_segment": worst_segment,
        "segments": len(left_segments),
        "samples": samples,
    }


def _compare_contacts(left: list[int], right: list[int], limit: int) -> dict[str, object]:
    if len(left) != len(right):
        return {"status": "failed", "reason": "contact_count_mismatch", "left": left, "right": right}
    worst = 0
    for left_step, right_step in zip(left, right):
        worst = max(worst, abs(left_step - right_step))
    return {
        "status": "passed" if worst <= limit else "failed",
        "max_delta": worst,
        "limit": limit,
        "left": left,
        "right": right,
    }


def compare(
    left_records: list[dict[str, object]],
    right_records: list[dict[str, object]],
    thresholds: dict[str, float] | None = None,
) -> dict[str, object]:
    """按输入消费边沿和物理 update_id 对齐两份校准记录。"""
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    result: dict[str, object] = {
        "status": "evidence_insufficient",
        "thresholds": limits,
        "comparisons": {},
        "failures": [],
        "evidence_issues": [],
    }
    try:
        left_samples, left_info = _dedupe_series(left_records, "left")
        right_samples, right_info = _dedupe_series(right_records, "right")
    except EvidenceError as error:
        result["status"] = "evidence_insufficient"
        result["evidence_issues"] = [{"code": "series_unusable", "message": error.message, **error.details}]
        return result
    except CompareError as error:
        result["status"] = "invalid_input"
        result["error"] = {"message": error.message, **error.details}
        return result
    result["scenario"] = left_info["scenario"]
    result["direction"] = left_info["direction"]
    result["left"] = left_info["series"]
    result["right"] = right_info["series"]
    issues: list[dict[str, object]] = result["evidence_issues"]  # type: ignore[assignment]
    failures: list[dict[str, object]] = result["failures"]  # type: ignore[assignment]
    comparisons: dict[str, object] = result["comparisons"]  # type: ignore[assignment]

    def issue(code: str, detail: dict[str, object] | None = None) -> None:
        issues.append({"code": code, **(detail or {})})

    if left_info["scenario"] != right_info["scenario"]:
        issue("scenario_mismatch", {"left": left_info["scenario"], "right": right_info["scenario"]})
    if left_info["direction"] != right_info["direction"]:
        issue("direction_mismatch", {"left": left_info["direction"], "right": right_info["direction"]})
    left_series: Series = left_info["series"]  # type: ignore[assignment]
    right_series: Series = right_info["series"]  # type: ignore[assignment]
    left_series["edge_inputs"] = [str(edge["input"]) for edge in left_series["input_edges"]]
    right_series["edge_inputs"] = [str(edge["input"]) for edge in right_series["input_edges"]]
    if left_series["edge_inputs"] != right_series["edge_inputs"]:
        issue(
            "input_edges_mismatch",
            {"left": left_series["edge_inputs"], "right": right_series["edge_inputs"]},
        )
    if left_series["map_id"] is None or right_series["map_id"] is None:
        issue("map_unknown")
    elif left_series["map_id"] != right_series["map_id"]:
        issue("map_mismatch", {"left": left_series["map_id"], "right": right_series["map_id"]})
    if left_series["step_ms"] != right_series["step_ms"]:
        issue(
            "step_ms_mismatch",
            {
                "left": left_series["step_ms"],
                "right": right_series["step_ms"],
                "note": "物理步长不同的两端不能按同一步序号对齐；#239 前 headless 为8ms。",
            },
        )
    for side, series in (("left", left_series), ("right", right_series)):
        if series["gaps"]:
            issue(
                "update_missing", {"side": side, "missing_updates": series["gaps"][:32], "note": "掉样不插值，需重采。"}
            )
        if series["missing_physics"]:
            issue("physics_sample_missing", {"side": side, "count": series["missing_physics"]})
        if series["ground_unknown"]:
            issue("ground_fact_missing", {"side": side, "count": series["ground_unknown"]})
    result["alignment"] = {
        "method": "consumed_input_edge_update_id",
        "edge_update_id": {"left": left_series["edge_update_id"], "right": right_series["edge_update_id"]},
        "step_index": "physics.update_id - edge_update_id",
        "edge_sample_may_include_one_update": True,
    }
    if issues:
        return result
    comparisons["trajectory"] = _compare_metric(
        "trajectory",
        left_samples,
        right_samples,
        left_info["edges"],
        right_info["edges"],
        _pose,
        limits["trajectory_px"],
    )
    comparisons["velocity"] = _compare_metric(
        "velocity",
        left_samples,
        right_samples,
        left_info["edges"],
        right_info["edges"],
        _velocity,
        limits["speed_px_s"],
    )
    comparisons["contacts"] = {
        "takeoffs": _compare_contacts(left_series["takeoffs"], right_series["takeoffs"], int(limits["contact_steps"])),
        "landings": _compare_contacts(left_series["landings"], right_series["landings"], int(limits["contact_steps"])),
    }
    for name in ("trajectory", "velocity"):
        comparison: dict[str, object] = comparisons[name]  # type: ignore[assignment]
        if comparison.get("status") == "insufficient":
            issue("comparison_evidence_insufficient", {"metric": name, **comparison})
        elif comparison.get("status") == "failed":
            failures.append({"metric": name, **comparison})
    contacts: dict[str, object] = comparisons["contacts"]  # type: ignore[assignment]
    for kind in ("takeoffs", "landings"):
        contact: dict[str, object] = contacts[kind]  # type: ignore[assignment]
        if contact.get("status") == "insufficient":
            issue("contact_evidence_insufficient", {"event": kind, **contact})
        elif contact.get("status") == "failed":
            failures.append({"metric": f"contact_{kind}", **contact})
    if issues:
        return result
    result["status"] = "failed" if failures else "comparable"
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", required=True, type=Path, help="一端导出的脚本事件日志或校准 JSONL")
    parser.add_argument("--right", required=True, type=Path, help="另一端导出的脚本事件日志或校准 JSONL")
    parser.add_argument(
        "--trajectory-px",
        type=float,
        default=DEFAULT_THRESHOLDS["trajectory_px"],
        help="同一物理步的相对轨迹差上限（地图像素，默认1）",
    )
    parser.add_argument(
        "--speed-px-s",
        type=float,
        default=DEFAULT_THRESHOLDS["speed_px_s"],
        help="同一物理步的速度差上限（px/s，默认1）",
    )
    parser.add_argument(
        "--contact-steps",
        type=int,
        default=DEFAULT_THRESHOLDS["contact_steps"],
        help="离地/落地事件允许相差的物理步数（默认1）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.trajectory_px <= 0 or arguments.speed_px_s <= 0 or arguments.contact_steps < 0:
        print(json.dumps({"status": "invalid_usage", "error": "门槛必须为正数。"}, ensure_ascii=False))
        return 2
    try:
        left = load_records(arguments.left)
        right = load_records(arguments.right)
    except CompareError as error:
        print(
            json.dumps(
                {"status": "invalid_input", "error": {"message": error.message, **error.details}}, ensure_ascii=False
            )
        )
        return 2
    result = compare(
        left,
        right,
        {
            "trajectory_px": arguments.trajectory_px,
            "speed_px_s": arguments.speed_px_s,
            "contact_steps": arguments.contact_steps,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "comparable":
        return 0
    if result["status"] == "failed":
        return 1
    return 3


if __name__ == "__main__":
    sys.exit(main())
