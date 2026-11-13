"""GUI 账号登录的保守入口：无法确认页面或动作结果时保留现场。"""

import fcntl
import os
import time

from .backend import Backend, JsonObject
from .bridge import BridgeClient, require_input_idle
from .errors import ClientError
from .gui_first_login import submit_credentials_once
from .profile import AccountProfile
from .runtime import load_runtime


def _require_input_idle(backend: Backend, instance_id: str, run_id: str) -> None:
    require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ClientError("gui_login_timeout", "登录等待已超时，未继续输入或重放。")


def _dispatched(result: JsonObject, action: str) -> bool:
    timings = result.get("timings")
    return (
        result.get("input_dispatched") is True
        and result.get("cancelled") is False
        and isinstance(timings, list)
        and len(timings) == 1
        and isinstance(timings[0], dict)
        and timings[0].get("action") == action
        and (
            action != "hold"
            or isinstance(timings[0].get("held_seconds"), (int, float))
            and timings[0]["held_seconds"] > 0
        )
    )


def _terms(
    backend: Backend, instance_id: str, run_id: str, accept_terms: bool, deadline: float = float("inf")
) -> JsonObject:
    if not accept_terms:
        raise ClientError("gui_terms_not_authorized", "未授权同意协议，未输入。")

    def observe():
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        native = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
        stage = backend.read("stage")
        dialog = backend.read("dialog")
        login = stage.get("login")
        windows = stage.get("windows")
        focused = dialog.get("focused_window")
        if (
            not runtime.running
            or runtime.run_id != run_id
            or native.get("instance_id") != instance_id
            or native.get("run_id") != run_id
            or native.get("held_keys") != []
            or not isinstance(native.get("command"), dict)
            or native["command"].get("status") == "running"
            or "script" not in native
            or (
                native["script"] is not None
                and (not isinstance(native["script"], dict) or native["script"].get("status") == "running")
            )
            or stage.get("instance_id") != instance_id
            or not isinstance(stage.get("client"), dict)
            or stage["client"].get("run_id") != run_id
            or dialog.get("instance_id") != instance_id
            or not isinstance(dialog.get("client"), dict)
            or dialog["client"].get("run_id") != run_id
            or stage.get("unavailable") != []
            or dialog.get("unavailable") != []
            or stage.get("stage") != "LOGIN"
            or not isinstance(login, dict)
            or login.get("raw_step") != 0
            or login.get("request_pending") is not False
            or login.get("transition_pending") is not False
            or not isinstance(windows, list)
            or not all(isinstance(w, dict) for w in windows)
            or len(windows) != 4
            or {tuple(w.get("vtables", [])) for w in windows}
            != {
                ("0xb3f13c", "0xb3f0f0", "0xb3f0ec"),
                ("0xaf7168", "0xaf711c", "0xaf7118"),
                ("0xaf7940", "0xaf78f4", "0xaf78f0"),
                ("0xaf79c8", "0xaf797c", "0xaf7978"),
            }
            or not isinstance(focused, dict)
            or len([w for w in windows if w.get("login_page_candidate") == "terms"]) != 1
            or focused.get("address")
            != next(w for w in windows if w.get("login_page_candidate") == "terms").get("address")
            or focused.get("vtables") != ["0xaf79c8", "0xaf797c", "0xaf7978"]
            or focused.get("width") != 431
            or focused.get("height") != 426
        ):
            raise ClientError("gui_login_state_unknown", "协议页面或实例状态不明确，停止输入。")
        window = next(w for w in windows if w.get("login_page_candidate") == "terms")
        buttons = window.get("buttons")
        rect = focused.get("root_rect")
        matches = (
            [button for button in buttons if isinstance(button, dict) and button.get("control_id") == 1]
            if isinstance(buttons, list)
            else []
        )
        if (
            len(matches) != 1
            or type(matches[0].get("enabled")) is not bool
            or matches[0].get("layout_x") != 266
            or matches[0].get("layout_y") != 374
            or matches[0].get("width") != 75
            or matches[0].get("height") != 32
            or not isinstance(rect, dict)
            or type(rect.get("left")) is not int
            or type(rect.get("top")) is not int
            or rect.get("right") != rect["left"] + 431
            or rect.get("bottom") != rect["top"] + 426
        ):
            raise ClientError("gui_login_state_unknown", "协议按钮或窗口坐标不可确认，停止输入。")
        return window["address"], rect, matches[0]["enabled"]

    address, rect, enabled = observe()
    if not enabled:
        _require_input_idle(backend, instance_id, run_id)
        _check_deadline(deadline)
        result = backend.desktop([{"action": "click", "x": rect["left"] + 176, "y": rect["top"] + 199}])
        if not _dispatched(result, "click"):
            raise ClientError("gui_login_action_unknown", "正文聚焦结果不明，停止输入。")
        for _ in range(2):
            current, new_rect, enabled = observe()
            if current != address or new_rect != rect:
                raise ClientError("gui_login_state_unknown", "协议窗口已变化，停止输入。")
            if enabled:
                break
            _require_input_idle(backend, instance_id, run_id)
            _check_deadline(deadline)
            result = backend.read("desktop", "scroll", "down", "--ticks", "10")
            if result.get("input_dispatched") is not True or result.get("action") != "scroll":
                raise ClientError("gui_login_action_unknown", "滚动结果不明，停止输入。")
        current, new_rect, enabled = observe()
        if current != address or new_rect != rect or not enabled:
            raise ClientError("gui_login_state_unknown", "协议尚未确认滚到底，停止输入。")
    runtime = load_runtime(backend.root, backend.name, backend.instance)
    if not runtime.running or runtime.run_id != run_id:
        raise ClientError("gui_login_identity_unconfirmed", "运行实例已改变，未确认协议。")
    try:
        descriptor = os.open(runtime.run_dir / "gui-terms-submitted", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ClientError("gui_terms_already_attempted", "本次运行已有协议确认尝试，禁止重放。") from error
    with os.fdopen(descriptor, "w") as stream:
        stream.write("attempted\n")
    _require_input_idle(backend, instance_id, run_id)
    _check_deadline(deadline)
    result = backend.desktop([{"action": "click", "x": rect["left"] + 303, "y": rect["top"] + 390}])
    if not _dispatched(result, "click"):
        raise ClientError("gui_login_action_unknown", "协议确认结果不明，禁止重试。")
    after = backend.read("stage")
    if (
        after.get("instance_id") != instance_id
        or not isinstance(after.get("client"), dict)
        or after["client"].get("run_id") != run_id
    ):
        raise ClientError("gui_login_action_unknown", "协议确认后实例状态不明，禁止重试。")
    return {"phase": "unknown", "action": "terms_input_dispatched", "instance_id": instance_id, "run_id": run_id}


def _gender(backend: Backend, instance_id: str, run_id: str, gender: str, deadline: float = float("inf")) -> JsonObject:
    def observe():
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        native = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
        stage, dialog = backend.read("stage"), backend.read("dialog")
        login, windows, focused = stage.get("login"), stage.get("windows"), dialog.get("focused_window")
        if (
            not runtime.running
            or runtime.run_id != run_id
            or native.get("instance_id") != instance_id
            or native.get("run_id") != run_id
            or native.get("held_keys") != []
            or not isinstance(native.get("command"), dict)
            or native["command"].get("status") == "running"
            or "script" not in native
            or native["script"] is not None
            and (not isinstance(native["script"], dict) or native["script"].get("status") == "running")
            or stage.get("instance_id") != instance_id
            or not isinstance(stage.get("client"), dict)
            or stage["client"].get("run_id") != run_id
            or stage.get("stage") != "LOGIN"
            or stage.get("unavailable") != []
            or not isinstance(login, dict)
            or login.get("raw_step") != 0
            or login.get("request_pending") is not False
            or login.get("transition_pending") is not False
            or dialog.get("instance_id") != instance_id
            or not isinstance(dialog.get("client"), dict)
            or dialog["client"].get("run_id") != run_id
            or dialog.get("unavailable") != []
            or not isinstance(windows, list)
            or not all(isinstance(w, dict) for w in windows)
            or len(windows) != 4
            or {tuple(w.get("vtables", [])) for w in windows}
            != {
                ("0xb3f13c", "0xb3f0f0", "0xb3f0ec"),
                ("0xaf7168", "0xaf711c", "0xaf7118"),
                ("0xaf7940", "0xaf78f4", "0xaf78f0"),
                ("0xaf7298", "0xaf724c", "0xaf7248"),
            }
            or dialog.get("script_dialog_open") is not False
            or dialog.get("focused_talk_dialog_open") is not False
            or dialog.get("registered_talk_dialog_open") is not False
            or "focused_window" not in dialog
            or (focused is not None and not isinstance(focused, dict))
            or not isinstance(stage.get("game_geometry"), dict)
            or stage["game_geometry"].get("width") != 1280
            or stage["game_geometry"].get("height") != 720
        ):
            raise ClientError("gui_gender_state_unknown", "性别页面或实例状态不明确，停止输入。")
        matches = [w for w in windows if w.get("login_page_candidate") == "gender"]
        if (
            len(matches) != 1
            or isinstance(focused, dict)
            and (
                focused.get("address") != matches[0].get("address")
                or focused.get("vtables") != ["0xaf7298", "0xaf724c", "0xaf7248"]
            )
        ):
            raise ClientError("gui_gender_state_unknown", "性别窗口焦点不明确，停止输入。")
        window = matches[0]
        geometry = stage["game_geometry"]
        game_rect = window.get("game_rect")
        if (
            not isinstance(window.get("address"), str)
            or not window["address"]
            or window.get("window_position_source") != "stable Gr2D layer bounds and camera"
            or type(geometry.get("x")) is not int
            or type(geometry.get("y")) is not int
            or not isinstance(game_rect, dict)
            or any(type(game_rect.get(k)) is not int for k in ("left", "top", "right", "bottom"))
            or game_rect["right"] - game_rect["left"] != 354
            or game_rect["bottom"] - game_rect["top"] != 259
            or not 0 <= game_rect["left"] < game_rect["right"] <= 1280
            or not 0 <= game_rect["top"] < game_rect["bottom"] <= 720
        ):
            raise ClientError("gui_gender_state_unknown", "性别窗口动态投影不可确认。")
        rect = {
            k: game_rect[k] + geometry["x" if k in ("left", "right") else "y"]
            for k in ("left", "top", "right", "bottom")
        }
        if isinstance(focused, dict) and (focused.get("game_rect") != game_rect or focused.get("root_rect") != rect):
            raise ClientError("gui_gender_state_unknown", "性别窗口投影不一致。")
        buttons = window.get("buttons")
        confirm = (
            [b for b in buttons if isinstance(b, dict) and b.get("control_id") == 8002]
            if isinstance(buttons, list)
            else []
        )
        geometry = stage["game_geometry"]
        if (
            window.get("width") != 354
            or window.get("height") != 259
            or not isinstance(rect, dict)
            or type(geometry.get("x")) is not int
            or type(geometry.get("y")) is not int
            or type(rect.get("left")) is not int
            or type(rect.get("top")) is not int
            or rect.get("right") != rect["left"] + 354
            or rect.get("bottom") != rect["top"] + 259
            or len(confirm) != 1
            or confirm[0].get("enabled") is not True
            or confirm[0].get("layout_x") != 190
            or confirm[0].get("layout_y") != 150
            or confirm[0].get("width") != 75
            or confirm[0].get("height") != 32
            or type(window.get("raw_gender_selection")) is not int
            or window["raw_gender_selection"] not in (0, 1)
        ):
            raise ClientError("gui_gender_state_unknown", "性别值或按钮位置未知，停止输入。")
        return runtime, window["address"], rect, window["raw_gender_selection"], dict(geometry), dict(game_rect)

    def stable():
        first = observe()
        second = observe()
        if first[1:] != second[1:]:
            raise ClientError("gui_gender_state_unknown", "性别窗口两次观察不一致，未输入。")
        return second

    runtime, address, rect, raw, geometry, game_rect = stable()
    target = 0 if gender == "male" else 1
    if raw != target:
        try:
            descriptor = os.open(runtime.run_dir / "gui-gender-selection", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise ClientError("gui_gender_state_unknown", "性别选择已尝试，禁止重放。") from error
        with os.fdopen(descriptor, "w") as stream:
            stream.write("attempted\n")
        _, current, current_rect, value, current_geometry, current_game = stable()
        if (current, current_rect, value, current_geometry, current_game) != (address, rect, raw, geometry, game_rect):
            raise ClientError("gui_gender_state_unknown", "性别窗口状态变化，未输入。")
        _require_input_idle(backend, instance_id, run_id)
        _check_deadline(deadline)
        result = backend.desktop([{"action": "click", "x": rect["left"] + 228, "y": rect["top"] + 107}])
        if not _dispatched(result, "click"):
            raise ClientError("gui_login_action_unknown", "性别下拉结果不明，停止输入。")
        _, current, new_rect, value, new_geometry, new_game = stable()
        if (current, new_rect, value, new_geometry, new_game) != (address, rect, raw, geometry, game_rect):
            raise ClientError("gui_gender_state_unknown", "性别下拉状态变化，停止输入。")
        _require_input_idle(backend, instance_id, run_id)
        _check_deadline(deadline)
        result = backend.desktop(
            [{"action": "click", "x": rect["left"] + 172, "y": rect["top"] + (125 if target == 0 else 141)}]
        )
        if not _dispatched(result, "click"):
            raise ClientError("gui_login_action_unknown", "性别选择结果不明，停止输入。")
        runtime, current, new_rect, raw, new_geometry, new_game = stable()
        if (current, new_rect, raw, new_geometry, new_game) != (address, rect, target, geometry, game_rect):
            raise ClientError("gui_gender_state_unknown", "性别选择未确认，停止输入。")
    try:
        descriptor = os.open(runtime.run_dir / "gui-gender-submitted", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ClientError("gui_gender_state_unknown", "性别确认已尝试，禁止重放。") from error
    with os.fdopen(descriptor, "w") as stream:
        stream.write("attempted\n")
    _, current, new_rect, value, new_geometry, new_game = stable()
    if (current, new_rect, value, new_geometry, new_game) != (address, rect, target, geometry, game_rect):
        raise ClientError("gui_gender_state_unknown", "性别确认前状态变化，未输入。")
    _require_input_idle(backend, instance_id, run_id)
    _check_deadline(deadline)
    result = backend.desktop([{"action": "click", "x": rect["left"] + 227, "y": rect["top"] + 166}])
    if not _dispatched(result, "click"):
        raise ClientError("gui_login_action_unknown", "性别确认结果不明，禁止重试。")
    return {"phase": "unknown", "action": "gender_input_dispatched"}


def _step(
    backend: Backend,
    profile: AccountProfile,
    *,
    instance_id: str,
    run_id: str,
    accept_terms: bool,
    gender: str,
    world_confirmed: bool = False,
    deadline: float = float("inf"),
) -> JsonObject:
    """提交一次账号或读取已就绪的角色列表；未知页面不发送输入。"""
    if type(accept_terms) is not bool or gender not in ("male", "female"):
        raise ClientError("invalid_login_options", "协议授权与性别必须明确指定。")
    runtime = backend.runtime
    if (
        backend.name != "beidou"
        or not runtime.running
        or runtime.run_id != run_id
        or runtime.character_id is not None
        or (runtime.world, runtime.channel) != (profile.world, profile.channel)
    ):
        raise ClientError("gui_login_identity_unconfirmed", "GUI 账号会话身份不匹配，未输入。")
    native = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
    if native.get("instance_id") != instance_id or native.get("run_id") != run_id:
        raise ClientError("gui_login_identity_unconfirmed", "原生桥身份不匹配，未输入。")
    stage = backend.read("stage")
    client = stage.get("client")
    login = stage.get("login")
    if (
        stage.get("instance_id") != instance_id
        or not isinstance(client, dict)
        or client.get("run_id") != run_id
        or stage.get("unavailable") != []
        or not isinstance(login, dict)
        or login.get("request_pending") is not False
        or login.get("transition_pending") is not False
    ):
        raise ClientError("gui_login_state_unknown", "登录状态或实例身份不明确，未输入。")
    if stage.get("stage") == "CHARACTER_SELECT" and login.get("characters_available") is True:
        characters = login.get("characters")
        windows = stage.get("windows")
        expected = sorted(
            [
                ("0xb3f13c", "0xb3f0f0", "0xb3f0ec"),
                ("0xaf7168", "0xaf711c", "0xaf7118"),
                ("0xaf6f04", "0xaf6eb8", "0xaf6eb4"),
                ("0xaf70d0", "0xaf7084", "0xaf7080"),
                ("0xaf70d0", "0xaf7084", "0xaf7080"),
                ("0xaf6d90", "0xaf6d44", "0xaf6d40"),
            ]
        )
        if (
            type(stage.get("world_id")) is int
            and stage["world_id"] == profile.world
            and type(stage.get("channel")) is int
            and stage["channel"] == profile.channel + 1
            and isinstance(characters, list)
            and isinstance(windows, list)
            and all(isinstance(w, dict) and isinstance(w.get("vtables"), list) for w in windows)
            and sorted(tuple(w["vtables"]) for w in windows) == expected
        ):
            return {"phase": "character_list", "characters": characters, "instance_id": instance_id, "run_id": run_id}
        raise ClientError("gui_login_state_unknown", "角色列表或窗口状态不可确认。")
    if stage.get("stage") in ("WORLD_SELECT", "CHANNEL_SELECT"):
        if (
            native.get("held_keys") != []
            or not isinstance(native.get("command"), dict)
            or native["command"].get("status") == "running"
            or "script" not in native
            or native["script"] is not None
            and (not isinstance(native["script"], dict) or native["script"].get("status") == "running")
        ):
            raise ClientError("input_busy", "输入状态不空闲，未操作世界或频道。")
        windows, geometry = stage.get("windows"), stage.get("game_geometry")
        signatures = {
            ("0xb3f13c", "0xb3f0f0", "0xb3f0ec"),
            ("0xaf7168", "0xaf711c", "0xaf7118"),
            ("0xaf7a90", "0xaf7a44", "0xaf7a40"),
            ("0xaf70d0", "0xaf7084", "0xaf7080"),
        }
        if stage["stage"] == "CHANNEL_SELECT":
            signatures.add(("0xaf7b4c", "0xaf7b00", "0xaf7afc"))
        if (
            profile.world != 0
            or not isinstance(windows, list)
            or not all(isinstance(w, dict) for w in windows)
            or len(windows) != len(signatures)
            or {tuple(w.get("vtables", [])) for w in windows} != signatures
            or not isinstance(geometry, dict)
            or geometry.get("width") != 1280
            or geometry.get("height") != 720
            or type(geometry.get("x")) is not int
            or type(geometry.get("y")) is not int
        ):
            raise ClientError("gui_login_state_unknown", "世界或频道页面无法安全确认，未输入。")
        current_runtime = load_runtime(backend.root, backend.name, backend.instance)
        if not current_runtime.running or current_runtime.run_id != run_id:
            raise ClientError("gui_login_identity_unconfirmed", "运行实例已改变，未输入。")
        if stage["stage"] == "WORLD_SELECT":
            world_window = next(w for w in windows if w.get("vtables") == ["0xaf7a90", "0xaf7a44", "0xaf7a40"])
            if (
                not isinstance(world_window.get("address"), str)
                or not world_window["address"]
                or world_window.get("window_position_source") != "stable Gr2D layer bounds and camera"
                or world_window.get("game_rect") != {"left": 472, "top": 164, "right": 872, "bottom": 264}
            ):
                raise ClientError("gui_world_selection_unknown", "世界窗口动态位置未确认，未输入。")
            raw = login.get("raw_world_selection")
            if (
                not isinstance(raw, dict)
                or type(raw.get("count")) is not int
                or raw["count"] != 1
                or type(raw.get("selected_index")) is not int
                or raw["selected_index"] != 0
                or type(raw.get("raw_world_id")) is not int
                or raw["raw_world_id"] != profile.world
            ):
                raise ClientError("gui_world_selection_unknown", "世界原始 ID 或选择不可确认，未输入。")
            try:
                descriptor = os.open(
                    current_runtime.run_dir / "gui-world-submitted", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError as error:
                raise ClientError("gui_login_action_unknown", "世界操作已尝试，禁止重放。") from error
            with os.fdopen(descriptor, "w") as stream:
                stream.write("attempted\n")
            _require_input_idle(backend, instance_id, run_id)
            _check_deadline(deadline)
            result = backend.desktop([{"action": "click", "x": geometry["x"] + 483, "y": geometry["y"] + 213}])
            if not _dispatched(result, "click"):
                raise ClientError("gui_login_action_unknown", "世界点击结果不明，禁止重放。")
            after, fresh = backend.read("stage"), BridgeClient(backend.root, backend.name, backend.instance).snapshot()
            again = load_runtime(backend.root, backend.name, backend.instance)
            after_login, after_windows = after.get("login"), after.get("windows")
            after_world = (
                [w for w in after_windows if isinstance(w, dict) and w.get("vtables") == world_window["vtables"]]
                if isinstance(after_windows, list)
                else []
            )
            if (
                again.running
                and again.run_id == run_id
                and fresh.get("instance_id") == instance_id
                and fresh.get("run_id") == run_id
                and after.get("instance_id") == instance_id
                and isinstance(after.get("client"), dict)
                and after["client"].get("run_id") == run_id
                and after.get("stage") == "TRANSITION"
                and after.get("unavailable") == []
                and isinstance(after_login, dict)
                and type(after_login.get("request_pending")) is bool
                and type(after_login.get("transition_pending")) is bool
            ):
                return {"phase": "unknown", "action": "world_input_dispatched"}
            if (
                again.running
                and again.run_id == run_id
                and fresh.get("instance_id") == instance_id
                and fresh.get("run_id") == run_id
                and fresh.get("held_keys") == []
                and isinstance(fresh.get("command"), dict)
                and fresh["command"].get("status") != "running"
                and "script" in fresh
                and (
                    fresh["script"] is None
                    or isinstance(fresh["script"], dict)
                    and fresh["script"].get("status") != "running"
                )
                and after.get("instance_id") == instance_id
                and isinstance(after.get("client"), dict)
                and after["client"].get("run_id") == run_id
                and after.get("stage") == "CHANNEL_SELECT"
                and after.get("unavailable") == []
                and after.get("game_geometry") == geometry
                and isinstance(after_login, dict)
                and after_login.get("request_pending") is False
                and after_login.get("transition_pending") is False
                and isinstance(after_windows, list)
                and all(isinstance(w, dict) for w in after_windows)
                and len(after_windows) == len(signatures) + 1
                and {tuple(w.get("vtables", [])) for w in after_windows}
                == signatures | {("0xaf7b4c", "0xaf7b00", "0xaf7afc")}
            ):
                return {"phase": "unknown", "action": "world_input_dispatched"}
            if (
                not again.running
                or again.run_id != run_id
                or fresh.get("instance_id") != instance_id
                or fresh.get("run_id") != run_id
                or fresh.get("held_keys") != []
                or not isinstance(fresh.get("command"), dict)
                or fresh["command"].get("status") == "running"
                or "script" not in fresh
                or fresh["script"] is not None
                and (not isinstance(fresh["script"], dict) or fresh["script"].get("status") == "running")
                or after.get("instance_id") != instance_id
                or not isinstance(after.get("client"), dict)
                or after["client"].get("run_id") != run_id
                or after.get("stage") != "WORLD_SELECT"
                or after.get("unavailable") != []
                or after.get("game_geometry") != geometry
                or not isinstance(after_login, dict)
                or after_login.get("request_pending") is not False
                or after_login.get("transition_pending") is not False
                or after_login.get("raw_world_selection") != raw
                or not isinstance(after_login.get("raw_world_selection"), dict)
                or any(
                    type(after_login["raw_world_selection"].get(k)) is not int
                    for k in ("count", "selected_index", "raw_world_id")
                )
                or len(after_world) != 1
                or after_world[0].get("address") != world_window.get("address")
                or after_world[0].get("window_position_source") != world_window.get("window_position_source")
                or after_world[0].get("game_rect") != world_window.get("game_rect")
                or not isinstance(after_windows, list)
                or not all(isinstance(w, dict) for w in after_windows)
                or len(after_windows) != len(signatures)
                or {tuple(w.get("vtables", [])) for w in after_windows} != signatures
            ):
                raise ClientError("gui_login_action_unknown", "世界点击后状态不明确，未发送确认。")
            _require_input_idle(backend, instance_id, run_id)
            _check_deadline(deadline)
            result = backend.desktop([{"action": "hold", "keys": ["Return"], "seconds": 0.1}])
            if not _dispatched(result, "hold"):
                raise ClientError("gui_login_action_unknown", "世界确认结果不明，禁止重放。")
            return {"phase": "unknown", "action": "world_input_dispatched"}
        if not world_confirmed:
            raise ClientError("gui_world_selection_unknown", "频道所属世界尚不可确认，未输入。")
        panel = stage.get("channel_panel")
        channels = panel.get("channels") if isinstance(panel, dict) else None
        matches = (
            [c for c in channels if isinstance(c, dict) and c.get("channel") == profile.channel + 1]
            if isinstance(channels, list)
            else []
        )
        rect = matches[0].get("root_rect") if len(matches) == 1 else None
        if (
            not isinstance(rect, dict)
            or any(type(rect.get(k)) is not int for k in ("left", "right", "top", "bottom"))
            or rect["right"] <= rect["left"]
            or rect["bottom"] <= rect["top"]
        ):
            raise ClientError("gui_login_state_unknown", "频道位置尚不可确认，未输入。")
        try:
            descriptor = os.open(
                current_runtime.run_dir / "gui-channel-submitted", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
            )
        except FileExistsError as error:
            raise ClientError("gui_login_action_unknown", "频道操作已尝试，禁止重放。") from error
        with os.fdopen(descriptor, "w") as stream:
            stream.write("attempted\n")
        _require_input_idle(backend, instance_id, run_id)
        _check_deadline(deadline)
        result = backend.desktop(
            [
                {
                    "action": "double-click",
                    "x": (rect["left"] + rect["right"]) // 2,
                    "y": (rect["top"] + rect["bottom"]) // 2,
                }
            ]
        )
        if not _dispatched(result, "double-click"):
            raise ClientError("gui_login_action_unknown", "频道操作结果不明，禁止重放。")
        return {"phase": "unknown", "action": "channel_input_dispatched"}
    if stage.get("stage") == "LOGIN" and login.get("raw_step") == 0:
        windows = stage.get("windows")
        if not isinstance(windows, list):
            raise ClientError("gui_login_state_unknown", "窗口列表不可用，未输入。")
        if any(isinstance(w, dict) and w.get("login_page_candidate") == "terms" for w in windows):
            return _terms(backend, instance_id, run_id, accept_terms, deadline)
        if any(isinstance(w, dict) and w.get("login_page_candidate") == "gender" for w in windows):
            return _gender(backend, instance_id, run_id, gender, deadline)
        if (
            not all(isinstance(w, dict) for w in windows)
            or len(windows) != 3
            or {tuple(w.get("vtables", [])) for w in windows}
            != {
                ("0xb3f13c", "0xb3f0f0", "0xb3f0ec"),
                ("0xaf7168", "0xaf711c", "0xaf7118"),
                ("0xaf7940", "0xaf78f4", "0xaf78f0"),
            }
        ):
            raise ClientError("gui_login_state_unknown", "存在未知窗口或首次登录页面，未输入。")
        _require_input_idle(backend, instance_id, run_id)
        _check_deadline(deadline)
        return submit_credentials_once(backend, profile, instance_id, run_id, deadline=deadline)
    raise ClientError("gui_login_state_unknown", "当前页面尚不能安全操作，未输入。")


def _execute_locked(
    backend: Backend,
    profile: AccountProfile,
    *,
    instance_id: str,
    run_id: str,
    accept_terms: bool,
    gender: str,
    timeout: float = 30,
) -> JsonObject:
    """有界观察并等待已发出的一次性动作，不重复输入。"""
    if not 0 < timeout <= 180:
        raise ClientError("invalid_login_options", "等待时间须大于零且不超过 180 秒。")
    deadline = time.monotonic() + timeout
    last_action = None
    attempted: set[str] = set()
    while True:
        stage = backend.read("stage")
        client = stage.get("client")
        login = stage.get("login")
        if (
            stage.get("instance_id") != instance_id
            or not isinstance(client, dict)
            or client.get("run_id") != run_id
            or stage.get("unavailable") != []
            or not isinstance(login, dict)
        ):
            raise ClientError("gui_login_state_unknown", "登录观察或实例身份不明确，停止输入。")
        windows = stage.get("windows")
        if not isinstance(windows, list):
            raise ClientError("gui_login_state_unknown", "窗口列表不可用，停止输入。")
        terms = any(isinstance(window, dict) and window.get("login_page_candidate") == "terms" for window in windows)
        gender_page = any(
            isinstance(window, dict) and window.get("login_page_candidate") == "gender" for window in windows
        )
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        if not runtime.running or runtime.run_id != run_id:
            raise ClientError("gui_login_identity_unconfirmed", "运行实例已改变，停止等待。")
        marker = (
            "gui-terms-submitted"
            if terms
            else "gui-gender-submitted"
            if gender_page
            else "gui-login-submitted"
            if stage.get("stage") == "LOGIN"
            else "gui-world-submitted"
            if stage.get("stage") == "WORLD_SELECT"
            else "gui-channel-submitted"
            if stage.get("stage") == "CHANNEL_SELECT"
            else None
        )
        if stage.get("stage") == "TRANSITION" and last_action is None:
            raise ClientError("gui_login_state_unknown", "未确认本次动作，不能等待未知过渡。")
        waiting = (
            (stage.get("stage") == "TRANSITION" and last_action is not None)
            or marker is not None
            and (runtime.run_dir / marker).exists()
            or login.get("request_pending") is True
            or login.get("transition_pending") is True
            or (last_action == "credentials" and stage.get("stage") == "LOGIN" and not terms and not gender_page)
            or (last_action == "terms" and terms)
            or (last_action == "gender" and gender_page)
            or (last_action == "world" and stage.get("stage") == "WORLD_SELECT")
            or (last_action == "channel" and stage.get("stage") == "CHANNEL_SELECT")
        )
        if type(login.get("request_pending")) is not bool or type(login.get("transition_pending")) is not bool:
            raise ClientError("gui_login_state_unknown", "请求状态不明确，停止输入。")
        if not waiting:
            _check_deadline(deadline)
            page = (
                "terms"
                if terms
                else "gender"
                if gender_page
                else "credentials"
                if stage.get("stage") == "LOGIN"
                else "world"
                if stage.get("stage") == "WORLD_SELECT"
                else "channel"
                if stage.get("stage") == "CHANNEL_SELECT"
                else None
            )
            if page in attempted:
                raise ClientError("gui_login_action_unknown", "登录页面回退，禁止重放已发送的输入。")
            if page is not None:
                attempted.add(page)
            result = _step(
                backend,
                profile,
                instance_id=instance_id,
                run_id=run_id,
                accept_terms=accept_terms,
                gender=gender,
                world_confirmed=last_action == "world" and stage.get("stage") == "CHANNEL_SELECT",
                deadline=deadline,
            )
            if result.get("phase") == "character_list":
                return result
            if result.get("credentials_submitted") is True:
                last_action = "credentials"
            elif result.get("action") == "terms_input_dispatched":
                last_action = "terms"
            elif result.get("action") == "gender_input_dispatched":
                last_action = "gender"
            elif result.get("action") == "world_input_dispatched":
                last_action = "world"
            elif result.get("action") == "channel_input_dispatched":
                last_action = "channel"
            else:
                raise ClientError("gui_login_action_unknown", "登录动作结果不明确，停止输入。")
        if time.monotonic() >= deadline:
            raise ClientError("gui_login_timeout", "等待登录页面变化超时，未重复输入。")
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def execute(
    backend: Backend,
    profile: AccountProfile,
    *,
    instance_id: str,
    run_id: str,
    accept_terms: bool,
    gender: str,
    timeout: float = 30,
) -> JsonObject:
    """排他控制单个运行实例，其他 login 不接管输入。"""
    runtime = load_runtime(backend.root, backend.name, backend.instance)
    if not runtime.running or runtime.run_id != run_id:
        raise ClientError("gui_login_identity_unconfirmed", "运行实例已改变，未开始登录。")
    descriptor = os.open(runtime.run_dir / "gui-login.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "r+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ClientError("gui_login_busy", "本次运行已有登录控制器，未输入。") from error
        return _execute_locked(
            backend,
            profile,
            instance_id=instance_id,
            run_id=run_id,
            accept_terms=accept_terms,
            gender=gender,
            timeout=timeout,
        )
