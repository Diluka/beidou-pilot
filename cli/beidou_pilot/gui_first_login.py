"""人工确认截图后的实验性单次 GUI 凭据提交，不识别首次弹窗。"""
import os
from typing import cast

from .backend import Backend, JsonObject
from .errors import ClientError
from .profile import AccountProfile


def submit_credentials_once(backend: Backend, profile: AccountProfile, instance_id: str, run_id: str) -> JsonObject:
    runtime = backend.runtime
    if (backend.name != "beidou" or not runtime.running or runtime.run_id != run_id
            or runtime.character_id is not None or (runtime.world, runtime.channel) != (profile.world, profile.channel)):
        raise ClientError("gui_login_identity_unconfirmed", "GUI 账号会话身份不匹配，未输入。")
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
        if (sample.get("stage") != "LOGIN" or sample.get("renderer") != "intel" or sample.get("unavailable")
                or not isinstance(login, dict) or login.get("raw_step") != 0
                or login.get("request_pending") is not False or login.get("transition_pending") is not False
                or not isinstance(geometry, dict) or geometry.get("width") != 1280 or geometry.get("height") != 720):
            raise ClientError("gui_login_form_unconfirmed", "登录表单状态不明确，未输入。")
    if first.get("game_geometry") != stage.get("game_geometry"):
        raise ClientError("gui_login_form_unconfirmed", "观察期间窗口位置变化，未输入。")
    focused = dialog.get("focused_window")
    geometry = cast(JsonObject, stage["game_geometry"])
    x, y = cast(int, geometry["x"]), cast(int, geometry["y"])
    if (not isinstance(focused, dict) or focused.get("game_rect") != {"left": 622, "top": 288, "right": 952, "bottom": 468}
            or focused.get("root_rect") != {"left": x + 622, "top": y + 288, "right": x + 952, "bottom": y + 468}
            or focused.get("vtables") != ["0xaf7940", "0xaf78f4", "0xaf78f0"]
            or focused.get("width") != 330 or focused.get("height") != 180
            or {item.get("control_id") for item in focused.get("buttons", [])} != set(range(1000, 1007))
            or dialog.get("unavailable") or dialog.get("script_dialog_open") is not False
            or dialog.get("focused_talk_dialog_open") is not False or dialog.get("registered_talk_dialog_open") is not False):
        raise ClientError("gui_login_form_unconfirmed", "焦点与已观察登录表单不符，未输入。")
    try:
        descriptor = os.open(runtime.run_dir / "gui-login-submitted", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise ClientError("gui_login_already_attempted", "本次运行已有登录尝试，禁止重放。") from error
    with os.fdopen(descriptor, "w") as stream:
        stream.write("attempted\n")
    try:
        backend.desktop([{"action": "click", "x": x + 727, "y": y + 308}])
        backend.text("runtime-ui", "key", "ctrl+a")
        backend.text("runtime-ui", "type-private", payload=profile.username)
        backend.desktop([{"action": "click", "x": x + 727, "y": y + 336}])
        backend.text("runtime-ui", "key", "ctrl+a")
        backend.text("runtime-ui", "type-private", payload=profile.password)
        backend.desktop([{"action": "click", "x": x + 880, "y": y + 306}])
    except Exception:
        raise ClientError("gui_login_input_unknown", "输入结果不明；保留现场，禁止重试。") from None
    return {"status": "unknown", "credentials_submitted": True, "instance_id": instance_id, "run_id": run_id}
