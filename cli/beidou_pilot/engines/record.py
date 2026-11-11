#!/usr/bin/env python3
"""有界采集真实游戏窗口，保留原始帧及采集时间区间；不发送输入。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from ..runtime import load_runtime


CAPTURE = r'''
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

request = json.load(sys.stdin)
directory = Path(request["directory"])
directory.mkdir(mode=0o700)
cancel = Path(request["cancel_file"])
period = 1 / request["fps"]
started = time.monotonic()
deadline = started + request["seconds"]
next_slot = 0
frames = 0
previous_start = None
maximum_gap = 0.0
status = "completed"
failure = None

with (directory / "frames.jsonl").open("x") as journal:
    journal.write(json.dumps({"kind": "header", "source": "current_x11_root_pixels",
        "client": request["client"], "requested_seconds": request["seconds"],
        "requested_fps": request["fps"], "format": "png", "readonly": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "started_monotonic": started}) + "\n")
    journal.flush()
    while time.monotonic() < deadline:
        if cancel.exists():
            status = "cancelled"
            break
        scheduled = started + next_slot * period
        remaining = min(scheduled, deadline) - time.monotonic()
        if remaining > 0:
            time.sleep(min(remaining, 0.04))
            continue
        now = time.monotonic()
        if now >= deadline:
            break
        slot = max(next_slot, int((now - started) / period))
        capture_started = time.monotonic()
        began_at = datetime.now(timezone.utc).isoformat()
        filename = "frame-%06d.png" % frames
        try:
            tree = subprocess.check_output(["xwininfo", "-root", "-tree"], text=True, timeout=2)
            outer_indent = None
            outer_count = 0
            children = []
            for line in tree.splitlines():
                window = re.match(r"^(\s*)(0x[0-9a-f]+)\s+.*?\s+(\d+)x(\d+)[+-]\d+[+-]\d+\s+([+-]\d+)([+-]\d+)\s*$", line)
                if not window:
                    continue
                indent = len(window[1])
                if outer_indent is not None and indent <= outer_indent:
                    outer_indent = None
                width, height, x, y = map(int, window.group(3, 4, 5, 6))
                if '("beidou.exe" "beidou.exe")' in line and width > 1 and height > 1:
                    outer_count += 1
                    outer_indent = indent
                    outer_window = window[2]
                elif outer_indent is not None and width > 1 and height > 1:
                    children.append({"x": x, "y": y, "width": width, "height": height})
            if outer_count != 1 or not children:
                raise ValueError("未唯一确认当前北斗游戏内容窗口。")
            details = subprocess.check_output(["xwininfo", "-id", outer_window], text=True, timeout=2)
            if "Map State: IsViewable" not in details:
                raise ValueError("北斗游戏窗口当前不可见。")
            geometry = max(children, key=lambda child: child["width"] * child["height"])
            crop = "{width}x{height}{x:+d}{y:+d}".format(**geometry)
            subprocess.run(["import", "-silent", "-window", "root", "-crop", crop,
                            "-define", "png:compression-level=1", str(directory / filename)],
                           check=True, capture_output=True, text=True, timeout=3)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as error:
            status = "failed"
            error_output = getattr(error, "stderr", None)
            if isinstance(error_output, bytes):
                error_output = error_output.decode("utf-8", errors="replace")
            failure = {"kind": "error", "slot": slot, "started_at": began_at,
                       "started_monotonic": capture_started,
                       "finished_at": datetime.now(timezone.utc).isoformat(),
                       "file": filename, "message": str(error), "stderr": error_output}
            journal.write(json.dumps(failure) + "\n")
            journal.flush()
            break
        finished = time.monotonic()
        if previous_start is not None:
            maximum_gap = max(maximum_gap, capture_started - previous_start)
        previous_start = capture_started
        journal.write(json.dumps({"kind": "frame", "index": frames, "slot": slot,
            "file": filename, "started_at": began_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "started_monotonic": capture_started, "finished_monotonic": finished,
            "capture_seconds": finished - capture_started, "geometry": geometry}) + "\n")
        journal.flush()
        frames += 1
        next_slot = slot + 1
    ended = time.monotonic()
    planned_slots = math.ceil(min(request["seconds"], ended - started) * request["fps"])
    failed_frames = 1 if failure is not None else 0
    summary = {"kind": "end", "status": status, "frames": frames,
        "requested_fps": request["fps"], "requested_seconds": request["seconds"],
        "elapsed_seconds": ended - started, "actual_fps": frames / (ended - started),
        "planned_slots": planned_slots, "failed_frames": failed_frames,
        "skipped_slots": max(0, planned_slots - frames - failed_frames),
        "maximum_start_gap_seconds": maximum_gap,
        "finished_at": datetime.now(timezone.utc).isoformat(), "failure": failure}
    journal.write(json.dumps(summary) + "\n")
    journal.flush()
(directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--cancel-file", required=True)
    args = parser.parse_args()
    if not args.name.replace("-", "").replace("_", "").isalnum():
        parser.error("录制名只允许字母、数字、短横线和下划线。")
    if not 0.1 <= args.seconds <= 120 or not 1 <= args.fps <= 20:
        parser.error("录制时长须为0.1至120秒，目标帧率须为1至20。")
    if not args.cancel_file.replace("-", "").replace("_", "").isalnum():
        parser.error("取消标记名无效。")
    root = Path(os.environ.get("CLIENT_ROOT", "/work")).resolve()
    runtime = load_runtime(root, "beidou", os.environ.get("MAPLE_INSTANCE", "default"))
    if not runtime.running:
        raise SystemExit("本容器客户端已经退出，未录制。")
    directory = runtime.run_dir / ("record-" + args.name)
    if directory.exists():
        raise SystemExit("录制目录已存在，拒绝覆盖。")
    request = {"directory": str(directory),
               "cancel_file": str(runtime.run_dir / args.cancel_file),
               "seconds": args.seconds, "fps": args.fps,
               "client": {"container_id": runtime.container_id, "run_id": runtime.run_id}}
    result = subprocess.run([sys.executable, "-c", CAPTURE], input=json.dumps(request),
                            env=dict(os.environ, DISPLAY=":97"), text=True, capture_output=True, check=True)
    summary = json.loads(result.stdout)
    summary.update(directory=str(directory), journal=str(directory / "frames.jsonl"),
                   summary_file=str(directory / "summary.json"), readonly=True)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
