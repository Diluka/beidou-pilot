#!/usr/bin/env python3
"""同一 host 时钟同时采样两个客户端实例的桥状态，用于跨客户端观察一致性验收。

工具只读两个工作台最新 run 的桥状态文件（不发输入、不写角色数据），输出 JSONL
并给出可读摘要：入图位置差、移动中观察端单帧跳变、停止后速度残留、最终位置差。
默认用于 headless 与 GUI 各作为观察端核对另一端，也可用于任意两个后端。
"""

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import TypedDict

DEFAULT_INTERVAL = 0.03
RESOLVE_INTERVAL = 0.5
STATE_CANDIDATES = ("runtime/headless/bridge/state.json", "runtime/bridge/state.json")


class ObserverError(Exception):
    def __init__(self, message: str, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class Velocity(TypedDict, total=False):
    x: float
    y: float


class SelfView(TypedDict, total=False):
    x: float
    y: float
    vx: float
    vy: float
    on_ground: bool


class EntityView(TypedDict, total=False):
    name: str
    character_id: int
    x: float
    y: float
    vx: float
    vy: float
    facing: str


class SideSample(TypedDict, total=False):
    state_path: str
    observed_at_ms: int
    character_id: int
    map_id: int
    self_view: SelfView
    view_of_other: EntityView | None


class DirectionSummary(TypedDict, total=False):
    samples: int
    initial_offset_px: float | None
    final_offset_px: float | None
    max_offset_px: float | None
    max_observer_jump_px: float | None
    max_self_speed_px_s: float | None
    residual_velocity_samples: int


class Summary(TypedDict, total=False):
    seconds: float
    interval: float
    samples: int
    first_to_second: DirectionSummary
    second_to_first: DirectionSummary
    warnings: list[str]
    output: str


def main_worktree(repo_root: Path) -> Path:
    """用 `git worktree list --porcelain` 取主检出；工作台账号与运行目录都在主检出。"""
    try:
        listing = subprocess.check_output(["git", "-C", str(repo_root), "worktree", "list", "--porcelain"], text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ObserverError(f"无法读取 git worktree 列表：{error}") from error
    for line in listing.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree ") :])
    raise ObserverError("git worktree 列表为空")


def resolve_workbench(repo_root: Path, selector: str) -> Path:
    path = Path(selector)
    if path.is_dir():
        return path.resolve()
    candidate = main_worktree(repo_root) / "private/workbenches" / selector
    if candidate.is_dir():
        return candidate.resolve()
    raise ObserverError(f"工作台不存在：{selector}（尝试过 {candidate}）")


def latest_run(workbench: Path) -> Path:
    base = workbench / "runtime/default"
    if not base.is_dir():
        raise ObserverError(f"工作台没有运行目录：{base}")
    runs = sorted((entry for entry in base.iterdir() if entry.is_dir()), key=lambda entry: entry.name)
    if not runs:
        raise ObserverError(f"工作台没有可用的 run 目录：{base}")
    return runs[-1]


def bridge_state_path(workbench: Path) -> Path:
    run = latest_run(workbench)
    for relative in STATE_CANDIDATES:
        path = run / relative
        if path.is_file():
            return path
    raise ObserverError(f"未找到桥状态文件：{run}")


def read_state(path: Path) -> dict[str, object] | None:
    try:
        with path.open("rb") as handle:
            return json.loads(handle.read())
    except (OSError, ValueError):
        return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _character_id(state: dict[str, object]) -> int | None:
    character = state.get("character")
    if not isinstance(character, dict):
        return None
    value = character.get("id")
    return value if isinstance(value, int) else None


def self_view(state: dict[str, object]) -> SelfView:
    character = state.get("character")
    if not isinstance(character, dict):
        return {}
    physics = character.get("physics")
    physics = physics if isinstance(physics, dict) else {}
    velocity = physics.get("velocity")
    velocity = velocity if isinstance(velocity, dict) else {}
    view: SelfView = {}
    for name, value in (
        ("x", character.get("x")),
        ("y", character.get("y")),
        ("vx", velocity.get("x")),
        ("vy", velocity.get("y")),
    ):
        number = _number(value)
        if number is not None:
            view[name] = number
    on_ground = physics.get("on_ground")
    if isinstance(on_ground, bool):
        view["on_ground"] = on_ground
    return view


def view_of(state: dict[str, object], character_id: int | None) -> EntityView | None:
    if character_id is None:
        return None
    players = state.get("players")
    if not isinstance(players, list):
        return None
    for player in players:
        if not isinstance(player, dict):
            continue
        if player.get("character_id") != character_id:
            continue
        velocity = player.get("velocity")
        velocity = velocity if isinstance(velocity, dict) else {}
        entity: EntityView = {}
        name = player.get("name")
        if isinstance(name, str):
            entity["name"] = name
        entity["character_id"] = character_id
        for target, value in (
            ("x", player.get("x")),
            ("y", player.get("y")),
            ("vx", velocity.get("x")),
            ("vy", velocity.get("y")),
        ):
            number = _number(value)
            if number is not None:
                entity[target] = number
        facing = player.get("facing")
        if isinstance(facing, str):
            entity["facing"] = facing
        return entity
    return None


def side_sample(state: dict[str, object], path: Path, other_id: int | None) -> SideSample:
    sample: SideSample = {"state_path": str(path)}
    observed = state.get("observed_at_ms")
    if isinstance(observed, int):
        sample["observed_at_ms"] = observed
    character_id = _character_id(state)
    if character_id is not None:
        sample["character_id"] = character_id
    map_id = state.get("map_id")
    if isinstance(map_id, int):
        sample["map_id"] = map_id
    sample["self_view"] = self_view(state)
    sample["view_of_other"] = view_of(state, other_id)
    return sample


def _offset(self_view: SelfView, other_view: EntityView | None) -> float | None:
    if other_view is None:
        return None
    x1, y1 = self_view.get("x"), self_view.get("y")
    x2, y2 = other_view.get("x"), other_view.get("y")
    if None in (x1, y1, x2, y2):
        return None
    return math.hypot(float(x2) - float(x1), float(y2) - float(y1))


def _speed(view: SelfView | EntityView) -> float | None:
    vx, vy = view.get("vx"), view.get("vy")
    if vx is None or vy is None:
        return None
    return math.hypot(float(vx), float(vy))


class DirectionTracker:
    """一个方向（自己的角色被对方观察）的摘要统计。"""

    def __init__(self) -> None:
        self.samples = 0
        self.initial: float | None = None
        self.final: float | None = None
        self.maximum: float | None = None
        self.max_jump: float | None = None
        self.max_self_speed: float | None = None
        self.residual = 0
        self._previous_view: EntityView | None = None

    def add(self, sample: SideSample) -> None:
        other = sample.get("view_of_other")
        own = sample.get("self_view") or {}
        offset = _offset(own, other)
        if offset is not None:
            self.samples += 1
            if self.initial is None:
                self.initial = offset
            self.final = offset
            self.maximum = offset if self.maximum is None else max(self.maximum, offset)
        self_speed = _speed(own)
        if self_speed is not None:
            self.max_self_speed = self_speed if self.max_self_speed is None else max(self.max_self_speed, self_speed)
        if other is not None and self._previous_view is not None:
            previous = self._previous_view
            if None not in (previous.get("x"), previous.get("y"), other.get("x"), other.get("y")):
                jump = math.hypot(float(other["x"]) - float(previous["x"]), float(other["y"]) - float(previous["y"]))
                self.max_jump = jump if self.max_jump is None else max(self.max_jump, jump)
        if other is not None and self_speed is not None and self_speed < 1 and other.get("vx") is not None:
            if abs(float(other["vx"])) > 1:
                self.residual += 1
        self._previous_view = other

    def summary(self) -> DirectionSummary:
        return {
            "samples": self.samples,
            "initial_offset_px": self.initial,
            "final_offset_px": self.final,
            "max_offset_px": self.maximum,
            "max_observer_jump_px": self.max_jump,
            "max_self_speed_px_s": self.max_self_speed,
            "residual_velocity_samples": self.residual,
        }


def observe(first: Path, second: Path, *, seconds: float, interval: float, output: Path) -> Summary:
    warnings: list[str] = []
    first_state = bridge_state_path(first)
    second_state = bridge_state_path(second)
    deadline = time.monotonic() + seconds
    next_resolve = 0.0
    samples = 0
    first_tracker = DirectionTracker()
    second_tracker = DirectionTracker()
    with output.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"event": "start", "first": str(first_state), "second": str(second_state), "interval": interval})
            + "\n"
        )
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_resolve:
                try:
                    first_state = bridge_state_path(first)
                    second_state = bridge_state_path(second)
                except ObserverError as error:
                    warnings.append(error.message)
                next_resolve = now + RESOLVE_INTERVAL
            first_data = read_state(first_state)
            second_data = read_state(second_state)
            if first_data is None or second_data is None:
                time.sleep(interval)
                continue
            first_id = _character_id(first_data)
            second_id = _character_id(second_data)
            record = {
                "t": round(time.monotonic() - (deadline - seconds), 4),
                "first": {
                    "state_path": str(first_state),
                    "observed_at_ms": first_data.get("observed_at_ms"),
                    "character_id": first_id,
                    "map_id": first_data.get("map_id"),
                    "self_view": self_view(first_data),
                    "view_of_second": view_of(first_data, second_id),
                },
                "second": {
                    "state_path": str(second_state),
                    "observed_at_ms": second_data.get("observed_at_ms"),
                    "character_id": second_id,
                    "map_id": second_data.get("map_id"),
                    "self_view": self_view(second_data),
                    "view_of_other": view_of(second_data, first_id),
                },
            }
            handle.write(json.dumps(record) + "\n")
            first_tracker.add(side_sample(first_data, first_state, second_id))
            second_tracker.add(side_sample(second_data, second_state, first_id))
            samples += 1
            time.sleep(interval)
        handle.write(json.dumps({"event": "stop", "samples": samples}) + "\n")
    first_map = None
    second_map = None
    first_data = read_state(first_state)
    second_data = read_state(second_state)
    if first_data is not None:
        first_map = first_data.get("map_id")
    if second_data is not None:
        second_map = second_data.get("map_id")
    if first_map != second_map:
        warnings.append(f"两端地图不同：first={first_map} second={second_map}")
    return {
        "seconds": round(seconds, 3),
        "interval": interval,
        "samples": samples,
        "first_to_second": first_tracker.summary(),
        "second_to_first": second_tracker.summary(),
        "warnings": warnings,
        "output": str(output),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", help="第一个工作台：live/NAME、dev/NAME 或绝对路径")
    parser.add_argument("second", help="第二个工作台：live/NAME、dev/NAME 或绝对路径")
    parser.add_argument("--seconds", type=float, required=True, help="采样时长（秒）")
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL, help=f"采样间隔（秒，默认 {DEFAULT_INTERVAL}）"
    )
    parser.add_argument("--output", type=Path, required=True, help="JSONL 输出路径")
    parser.add_argument("--summary", type=Path, help="可选的摘要 JSON 输出路径")
    parser.add_argument("--repo-root", type=Path, help="仓库根（默认按脚本位置推断）")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.seconds <= 0:
        parser.error("--seconds 必须为正数")
    if not 0.01 <= args.interval <= 1:
        parser.error("--interval 必须在 0.01 到 1 秒之间")
    repo_root = args.repo_root or Path(__file__).resolve().parents[2]
    try:
        first = resolve_workbench(repo_root, args.first)
        second = resolve_workbench(repo_root, args.second)
        summary = observe(first, second, seconds=args.seconds, interval=args.interval, output=args.output)
    except ObserverError as error:
        print(json.dumps({"ok": False, "error": error.message, "details": error.details}), file=sys.stderr)
        return 2
    if args.summary:
        args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
