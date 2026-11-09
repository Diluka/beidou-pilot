#!/usr/bin/env python3
"""通过客户端原生 API 读取角色快照，可持续输出 NDJSON。"""

import argparse
import json
import time
from ..errors import JsonObject
from ..observations import NativeObserver


def read_observation(observer: NativeObserver) -> JsonObject:
    sampled = observer.snapshot()
    ready = sampled["ready"] is True
    # 北斗桥仅发布通过安全值校验的字段；无头端没有 TSecType 校验。
    native_checksums = observer.backend == "beidou"
    return {**observer.metadata(sampled), "read_seconds": 0,
            "bridge_instance_id": sampled["instance_id"],
            "map_id": sampled["map_id"],
            "map_checksum_valid": sampled["map_id"] is not None if native_checksums else None,
            "character": sampled["character"],
            "character_checksum_valid": sampled["character"] is not None if native_checksums else None,
            "native_values_valid": ready,
            "position": sampled["position"], "sample_seq": sampled["seq"],
            "held_keys": sampled["held_keys"], "bridge_command": sampled["command"],
            "unavailable": [] if ready else ["原生客户端尚未取得完整游戏角色状态。"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="一次核验后流式输出短时 NDJSON")
    parser.add_argument("--seconds", type=float, default=30, help="流式观察时长，0.1 至 600 秒")
    parser.add_argument("--interval", type=float, default=.1, help="快照间隔，0.05 至 1 秒")
    args = parser.parse_args()
    if not .1 <= args.seconds <= 600 or not .05 <= args.interval <= 1:
        parser.error("观察时长须为 0.1 至 600 秒，间隔须为 0.05 至 1 秒。")
    observer = NativeObserver()
    deadline = time.monotonic() + args.seconds
    while True:
        print(json.dumps(read_observation(observer), ensure_ascii=False), flush=True)
        if not args.watch or time.monotonic() >= deadline:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
