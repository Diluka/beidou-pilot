"""幂等打开客户端并用普通 GUI 完成已有角色登录。"""

import json
from pathlib import Path
import time
from typing import cast
import uuid

from .backend import Backend, JsonObject
from .errors import ClientError
from .profile import LoginProfile


def open_game(backend: Backend, *, profile: LoginProfile,
              server: Path | None = None,
              timeout: float = 90) -> JsonObject:
    """使用本镜像的正常 GUI 流程登录并核对本容器角色。"""
    channel = profile.channel + 1
    if not 1 <= channel <= 20 or not 5 <= timeout <= 180:
        raise ClientError("invalid_open_options", "频道须为 1 至 20，等待时间须为 5 至 180 秒。")
    if profile.world != 0:
        raise ClientError("unsupported_world", "原版 GUI 自动登录仅支持世界 0。", {"requested": profile.world})
    runtime = backend.runtime
    runtime.verify_request(profile, server)
    if not runtime.running:
        raise ClientError("client_not_running", "本容器客户端已退出，请使用工作台入口重新启动。")
    stage = backend.read("stage")
    resumed = stage["stage"] == "IN_GAME"
    completed: list[str] = []
    deadline = time.monotonic() + timeout
    while True:
        current = stage["stage"]
        if current == "IN_GAME":
            if (backend.root / "state/agent-bridge-build.json").is_file():
                from .bridge import BridgeClient

                try:
                    native_ready = BridgeClient(backend.root).snapshot()["ready"]
                except ClientError as error:
                    if error.code not in {"bridge_unavailable", "stale_bridge_state", "bridge_session_mismatch"}:
                        raise
                    native_ready = False
                if not native_ready:
                    if time.monotonic() >= deadline:
                        raise ClientError("in_game_observation_unavailable", "角色已入图，但原生桥尚未恢复有效采样。", stage)
                    time.sleep(.1)
                    stage = backend.read("stage")
                    continue
            observed = backend.read("observe")
            current_character = observed.get("character")
            if (observed.get("native_values_valid") is not True
                    or observed.get("position") is None or not isinstance(current_character, dict)):
                raise ClientError("in_game_observation_unavailable", "入图状态尚不能可靠确认。", stage)
            if current_character["id"] != profile.character_id:
                raise ClientError("character_mismatch", "当前角色与请求角色不同，保留现有客户端。",
                                  {"expected": profile.character_id, "actual": current_character["id"], "stage": stage})
            if stage["channel"] != channel:
                raise ClientError("channel_mismatch", "当前频道与请求频道不同，保留现有客户端。",
                                  {"expected": channel, "actual": stage["channel"], "stage": stage})
            if stage["world_id"] != profile.world:
                raise ClientError("world_mismatch", "当前世界与请求世界不同，保留现有客户端。",
                                  {"expected": profile.world, "actual": stage["world_id"], "stage": stage})
            return {"ready": True, "started": False, "resumed": resumed,
                    "skipped_login": "login" not in completed, "actions": completed,
                    "character": current_character, "channel": channel,
                    "server_file": str(backend.root / "server.json"),
                    "source_revision": runtime.source_revision, "image": runtime.image,
                    "stage": stage, "state": observed}
        if current in {"STOPPED", "UNKNOWN"} or time.monotonic() >= deadline:
            diagnostic = backend.root / "runtime/runs" / ("open-diagnostic-" + uuid.uuid4().hex + ".json")
            diagnostic.parent.mkdir(parents=True, exist_ok=True)
            with diagnostic.open("x") as stream:
                json.dump({"stage": stage, "completed_actions": completed,
                           "requested_channel": channel, "requested_character_id": profile.character_id,
                           "server_file": str(backend.root / "server.json")},
                          stream, ensure_ascii=False, indent=2)
            raise ClientError("open_stage_unknown" if current in {"STOPPED", "UNKNOWN"} else "open_timeout",
                              "客户端未达到可确认的入图状态，已保存诊断并保留现场。",
                              {"stage": stage, "completed_actions": completed,
                               "diagnostic": str(diagnostic), "server_file": str(backend.root / "server.json")})
        if stage.get("renderer") == "software":
            raise ClientError("software_renderer", "当前客户端使用软件渲染，停止自动登录并保留诊断现场。", stage)
        login = stage.get("login")
        pending = isinstance(login, dict) and (login.get("request_pending") or login.get("transition_pending"))
        if current in {"LOGIN", "WORLD_SELECT", "CHANNEL_SELECT", "CHARACTER_SELECT"} and not pending:
            geometry = stage.get("game_geometry")
            if not isinstance(geometry, dict) or geometry.get("width") != 1280 or geometry.get("height") != 720:
                raise ClientError("unsupported_login_geometry", "登录布局须为当前已验证的 1280×720 游戏区。", stage)
            x, y = cast(int, geometry["x"]), cast(int, geometry["y"])
            if current == "LOGIN" and "login" not in completed:
                if stage.get("renderer") != "intel":
                    time.sleep(0.5)
                    stage = backend.read("stage")
                    continue
                backend.desktop([{"action": "click", "x": x + 727, "y": y + 308}])
                backend.text("runtime-ui", "key", "ctrl+a")
                backend.text("runtime-ui", "type-private", payload=profile.username)
                backend.desktop([{"action": "click", "x": x + 727, "y": y + 336}])
                backend.text("runtime-ui", "key", "ctrl+a")
                backend.text("runtime-ui", "type-private", payload=profile.password)
                backend.desktop([{"action": "click", "x": x + 880, "y": y + 306}])
                completed.append("login")
            elif current == "WORLD_SELECT" and "world" not in completed:
                backend.desktop([{"action": "click", "x": x + 483, "y": y + 213},
                               {"action": "wait", "seconds": 0.7},
                               {"action": "hold", "keys": ["Return"], "seconds": 0.1}])
                completed.append("world")
            elif current == "CHANNEL_SELECT" and "channel" not in completed:
                panel = cast(JsonObject, stage["channel_panel"])
                channels = cast(list[JsonObject], panel["channels"])
                matches = [entry for entry in channels if entry["channel"] == channel]
                if len(matches) != 1:
                    raise ClientError("channel_unavailable", "频道面板未提供请求频道。",
                                      {"requested": channel, "channels": channels})
                rect = matches[0]["root_rect"]
                if not isinstance(rect, dict):
                    raise ClientError("channel_layout_unavailable", "频道格子尚未获得可靠窗口投影，未点击。", stage)
                backend.desktop([{"action": "double-click", "x": (cast(int, rect["left"]) + cast(int, rect["right"])) // 2,
                               "y": (cast(int, rect["top"]) + cast(int, rect["bottom"])) // 2}])
                completed.append("channel")
            elif current == "CHARACTER_SELECT" and "character" not in completed:
                if cast(JsonObject, login).get("characters_available") is not True:
                    raise ClientError("character_list_unavailable", "角色页已识别，但角色名单尚不能可靠解析；未发送选角输入。", stage)
                characters = cast(list[JsonObject], cast(JsonObject, login)["characters"])
                matches = [entry for entry in characters if entry["id"] == profile.character_id]
                if len(matches) != 1:
                    raise ClientError("character_not_unique", "角色列表未唯一匹配目标角色；不自动创建角色。",
                                      {"requested": profile.character_id, "characters": characters})
                selected = matches[0]
                active_index = cast(int, cast(JsonObject, login)["selected_index"])
                desired_index = cast(int, selected["index"])
                # CUIAvatar 的 Left/Right 会同步 CLogin 索引，并自动切换每页三个角色。
                while active_index != desired_index:
                    expected_index = 0 if active_index == -1 else active_index + (1 if active_index < desired_index else -1)
                    key = "Right" if active_index < desired_index else "Left"
                    backend.desktop([{"action": "hold", "keys": [key], "seconds": 0.08},
                                     {"action": "wait", "seconds": 0.15}])
                    selection = backend.read("stage")
                    selected_login = selection.get("login")
                    if (selection["stage"] != "CHARACTER_SELECT" or not isinstance(selected_login, dict)
                            or selected_login.get("selected_index") != expected_index):
                        raise ClientError("character_selection_unconfirmed", "角色键盘选择未由客户端索引确认，未继续输入或开始游戏。", selection)
                    active_index = expected_index
                backend.desktop([{"action": "click", "x": x + 866, "y": y + 223}])
                completed.append("character")
        time.sleep(0.5)
        stage = backend.read("stage")
