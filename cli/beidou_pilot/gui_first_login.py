"""人工确认截图后的实验性单次 GUI 凭据提交，不识别首次弹窗。"""

import os
import time
from typing import cast

from .backend import Backend, JsonObject
from .bridge import BridgeClient, require_input_idle
from .errors import ClientError
from .profile import AccountProfile


def submit_credentials_once(
    backend: Backend, profile: AccountProfile, instance_id: str, run_id: str, *, deadline: float | None = None
) -> JsonObject:
    runtime = backend.runtime
    if (
        backend.name != "beidou"
        or not runtime.running
        or runtime.run_id != run_id
        or runtime.character_id is not None
        or (runtime.world, runtime.channel) != (profile.world, profile.channel)
    ):
        raise ClientError("gui_login_identity_unconfirmed", "GUI 账号会话身份不匹配，未输入。")
    bridge = BridgeClient(backend.root, backend.name, backend.instance)

    require_input_idle(bridge, instance_id, run_id)
    first = backend.read("stage")
    dialog = backend.read("dialog")
    stage = backend.read("stage")
    for sample in (first, dialog, stage):
        client = sample.get("client")
        if sample.get("instance_id") != instance_id or not isinstance(client, dict) or client.get("run_id") != run_id:
            raise ClientError("gui_login_identity_unconfirmed", "观察身份不匹配，未输入。")
    for sample in (first, stage):
        login = sample.get("login")
        geometry = sample.get("game_geometry")
        if (
            sample.get("stage") != "LOGIN"
            or sample.get("renderer") != "intel"
            or sample.get("unavailable")
            or not isinstance(login, dict)
            or login.get("raw_step") != 0
            or login.get("request_pending") is not False
            or login.get("transition_pending") is not False
            or not isinstance(geometry, dict)
            or geometry.get("width") != 1280
            or geometry.get("height") != 720
        ):
            raise ClientError("gui_login_form_unconfirmed", "登录表单状态不明确，未输入。")
    if first.get("game_geometry") != stage.get("game_geometry"):
        raise ClientError("gui_login_form_unconfirmed", "观察期间窗口位置变化，未输入。")
    focused = dialog.get("focused_window")
    baseline_windows = stage.get("windows")
    if not isinstance(baseline_windows, list) or not baseline_windows:
        raise ClientError("gui_login_form_unconfirmed", "窗口清单不可用，未输入。")
    signatures = {
        (window.get("address"), tuple(window.get("vtables", [])), window.get("width"), window.get("height"))
        for window in baseline_windows
    }
    expected = {
        (("0xb3f13c", "0xb3f0f0", "0xb3f0ec"), 1280, 720),
        (("0xaf7168", "0xaf711c", "0xaf7118"), 125, 352),
        (("0xaf7940", "0xaf78f4", "0xaf78f0"), 330, 180),
    }
    first_windows = first.get("windows")
    if (
        len(baseline_windows) != 3
        or len(signatures) != 3
        or {(v, w, h) for _, v, w, h in signatures} != expected
        or not isinstance(first_windows, list)
        or len(first_windows) != 3
        or {
            (window.get("address"), tuple(window.get("vtables", [])), window.get("width"), window.get("height"))
            for window in first_windows
        }
        != signatures
    ):
        raise ClientError("gui_login_form_unconfirmed", "登录窗口清单不明确，未输入。")
    geometry = cast(JsonObject, stage["game_geometry"])
    x, y = cast(int, geometry["x"]), cast(int, geometry["y"])
    if (
        not isinstance(focused, dict)
        or focused.get("game_rect") != {"left": 622, "top": 288, "right": 952, "bottom": 468}
        or focused.get("root_rect") != {"left": x + 622, "top": y + 288, "right": x + 952, "bottom": y + 468}
        or focused.get("vtables") != ["0xaf7940", "0xaf78f4", "0xaf78f0"]
        or focused.get("width") != 330
        or focused.get("height") != 180
        or {item.get("control_id") for item in focused.get("buttons", [])} != set(range(1000, 1007))
        or dialog.get("unavailable")
        or dialog.get("script_dialog_open") is not False
        or dialog.get("focused_talk_dialog_open") is not False
        or dialog.get("registered_talk_dialog_open") is not False
    ):
        raise ClientError("gui_login_form_unconfirmed", "焦点与已观察登录表单不符，未输入。")
    try:
        descriptor = os.open(runtime.run_dir / "gui-login-submitted", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ClientError("gui_login_already_attempted", "本次运行已有登录尝试，禁止重放。") from error
    with os.fdopen(descriptor, "w") as stream:
        stream.write("attempted\n")

    def verify_form(account_empty: bool, password_empty: bool, focus: str | None = None) -> None:
        require_input_idle(bridge, instance_id, run_id)
        current = backend.read("stage")
        current_dialog = backend.read("dialog")
        for sample in (current, current_dialog):
            client = sample.get("client")
            if (
                sample.get("instance_id") != instance_id
                or not isinstance(client, dict)
                or client.get("run_id") != run_id
            ):
                raise ClientError("gui_login_identity_unconfirmed", "运行身份已变化。")
        if (
            current.get("stage") != "LOGIN"
            or current.get("renderer") != "intel"
            or current.get("unavailable")
            or current.get("game_geometry") != geometry
            or current.get("login") != stage.get("login")
            or current_dialog.get("unavailable")
            or current_dialog.get("script_dialog_open") is not False
            or current_dialog.get("focused_talk_dialog_open") is not False
            or current_dialog.get("registered_talk_dialog_open") is not False
            or current_dialog.get("focused_window") != focused
        ):
            raise ClientError("gui_login_form_unconfirmed", "登录表单状态已变化。")
        windows = current.get("windows")
        if (
            not isinstance(windows, list)
            or len(windows) != len(baseline_windows)
            or {
                (window.get("address"), tuple(window.get("vtables", [])), window.get("width"), window.get("height"))
                for window in windows
            }
            != signatures
        ):
            raise ClientError("gui_login_form_unconfirmed", "窗口清单已变化。")
        matches = (
            [
                window
                for window in windows
                if isinstance(window, dict)
                and window.get("address") == focused.get("address")
                and window.get("vtables") == focused.get("vtables")
            ]
            if isinstance(windows, list)
            else []
        )
        if (
            len(matches) != 1
            or matches[0].get("account_empty") is not account_empty
            or matches[0].get("password_empty") is not password_empty
            or (focus is not None and matches[0].get("login_edit_focus") != focus)
        ):
            raise ClientError("gui_login_form_unconfirmed", "登录输入框状态或焦点未确认。")

    def check_deadline() -> None:
        if deadline is not None and time.monotonic() >= deadline:
            raise ClientError("gui_login_timeout", "登录期限已到，未发送后续输入。")

    def click(px: int, py: int, account_empty: bool, password_empty: bool, focus: str | None = None) -> None:
        verify_form(account_empty, password_empty, focus)
        check_deadline()
        result = backend.desktop([{"action": "click", "x": px, "y": py}])
        timings = result.get("timings")
        if (
            result.get("cancelled") is not False
            or result.get("input_dispatched") is not True
            or not isinstance(timings, list)
            or len(timings) != 1
            or not isinstance(timings[0], dict)
            or timings[0].get("action") != "click"
        ):
            raise ClientError("gui_login_input_unknown", "点击未确认。")

    try:
        click(x + 727, y + 308, True, True)
        verify_form(True, True, "account")
        check_deadline()
        backend.text("runtime-ui", "type-private", payload=profile.username)
        verify_form(False, True, "account")
        click(x + 727, y + 336, False, True, "account")
        verify_form(False, True, "password")
        check_deadline()
        backend.text("runtime-ui", "type-private", payload=profile.password)
        verify_form(False, False, "password")
        click(x + 880, y + 306, False, False, "password")
    except Exception:
        raise ClientError("gui_login_input_unknown", "输入结果不明；保留现场，禁止重试。") from None
    return {"status": "unknown", "credentials_submitted": True, "instance_id": instance_id, "run_id": run_id}
