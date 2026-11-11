"""容器内无头客户端的状态与入图确认。"""

from pathlib import Path
import time
from typing import cast

from .bridge import BridgeClient
from .errors import ClientError, JsonObject
from .profile import LoginProfile
from .runtime import load_runtime


def status(root: Path, instance: str = "default") -> JsonObject:
    runtime = load_runtime(root, "headless", instance)
    result: JsonObject = {"backend": "headless", "instance": instance,
                          "stage": "STOPPED", "running": runtime.running,
                          "channel": None, "character": None, "unavailable": [],
                          "run_id": runtime.run_id, "run_dir": str(runtime.run_dir),
                          "image": runtime.image, "source_revision": runtime.source_revision}
    if not runtime.running:
        return result
    try:
        state = BridgeClient(root, "headless", instance).snapshot()
    except ClientError as error:
        if error.code not in {"bridge_unavailable", "bridge_session_mismatch", "stale_bridge_state"}:
            raise
        result.update(stage="STARTING", unavailable=[error.message])
        return result
    result.update(stage="IN_GAME" if state["ready"] else "STARTING", channel=runtime.channel + 1,
                  character=state["character"], map_id=state["map_id"], position=state["position"],
                  unavailable=[] if state["ready"] else ["无头客户端尚未进入可操作场景。"],
                  state=cast(JsonObject, state))
    return result


def open_game(root: Path, *, profile: LoginProfile, server: Path | None = None,
              timeout: float = 90, instance: str = "default") -> JsonObject:
    if not 5 <= timeout <= 180:
        raise ClientError("invalid_open_options", "启动等待期限须为 5 至 180 秒。")
    runtime = load_runtime(root, "headless", instance)
    runtime.verify_request(profile, server)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observed = status(root, instance)
        if observed["running"] is False:
            raise ClientError("headless_start_failed", "本容器原生客户端已退出，请从工作台入口核对退出日志。")
        if observed["stage"] == "IN_GAME":
            character = cast(JsonObject, observed["character"])
            if character["id"] != profile.character_id:
                raise ClientError("character_mismatch", "实际入图角色与账号配置不符，保留本容器。")
            return {**observed, "ready": True, "started": False, "resumed": True}
        time.sleep(.1)
    raise ClientError("headless_open_timeout", "无头客户端未在期限内入图，保留现场。",
                      {"run_dir": str(runtime.run_dir)})
