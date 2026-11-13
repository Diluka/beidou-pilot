"""GUI 账号登录：经原生桥调用原版客户端内部动作，无法确认时保留现场。

登录页、协议页与性别页的动作由原生桥在游戏线程调用原版客户端入口完成；
Python 只核对实例身份、页面与一次性授权，不发送坐标或键鼠输入。
"""

import fcntl
import math
import os
import time

from .backend import Backend, JsonObject
from .bridge import BridgeClient, require_input_idle
from .errors import ClientError
from .profile import AccountProfile
from .runtime import load_runtime

CWND_MAN = ("0xb3f13c", "0xb3f0f0", "0xb3f0ec")
SIDE_PANEL = ("0xaf7168", "0xaf711c", "0xaf7118")
LOGIN_FORM = ("0xaf7940", "0xaf78f4", "0xaf78f0")
TERMS_PAGE = ("0xaf79c8", "0xaf797c", "0xaf7978")
GENDER_PAGE = ("0xaf7298", "0xaf724c", "0xaf7248")
WORLD_PANEL = ("0xaf7a90", "0xaf7a44", "0xaf7a40")
CHANNEL_PANEL = ("0xaf7b4c", "0xaf7b00", "0xaf7afc")
SIDE_BUTTONS = ("0xaf70d0", "0xaf7084", "0xaf7080")

def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise ClientError("gui_login_timeout", "登录等待已超时，未继续输入或重放。")


def _observe(backend: Backend, instance_id: str, run_id: str):
    """核对实例身份、原生输入空闲与页面观察，返回新鲜 stage。"""
    runtime = load_runtime(backend.root, backend.name, backend.instance)
    if backend.name != "beidou" or not runtime.running or runtime.run_id != run_id:
        raise ClientError("gui_login_identity_unconfirmed", "GUI 账号会话身份已改变，停止输入。")
    bridge = BridgeClient(backend.root, backend.name, backend.instance)
    native = bridge.snapshot()
    if native.get("instance_id") != instance_id or native.get("run_id") != run_id:
        raise ClientError("gui_login_identity_unconfirmed", "原生桥身份不匹配，停止输入。")
    require_input_idle(bridge, instance_id, run_id)
    stage = backend.read("stage")
    client = stage.get("client")
    login = stage.get("login")
    if (
        stage.get("instance_id") != instance_id
        or not isinstance(client, dict)
        or client.get("run_id") != run_id
        or stage.get("unavailable") != []
        or not isinstance(login, dict)
        or stage.get("stage") not in ("LOGIN", "WORLD_SELECT", "CHANNEL_SELECT", "CHARACTER_SELECT", "TRANSITION")
    ):
        raise ClientError("gui_login_state_unknown", "登录观察或实例身份不明确，停止输入。")
    return runtime, stage, bridge


def _windows(stage: JsonObject) -> list[JsonObject]:
    windows = stage.get("windows")
    if not isinstance(windows, list) or not all(isinstance(window, dict) for window in windows):
        raise ClientError("gui_login_state_unknown", "窗口清单不可用，停止输入。")
    return windows


def _window(stage: JsonObject, signature: tuple[str, str, str], *, width: int, height: int) -> str:
    """唯一匹配已观察窗口签名，返回其原生地址。"""
    matches = [window for window in _windows(stage) if window.get("vtables") == list(signature)]
    if (
        len(matches) != 1
        or type(matches[0].get("width")) is not int
        or matches[0]["width"] != width
        or type(matches[0].get("height")) is not int
        or matches[0]["height"] != height
        or not isinstance(matches[0].get("address"), str)
    ):
        raise ClientError("gui_login_state_unknown", "登录窗口身份或尺寸不可确认，停止输入。")
    return matches[0]["address"]


def _signatures(stage: JsonObject) -> frozenset[tuple[str, ...]]:
    return frozenset(tuple(window.get("vtables", [])) for window in _windows(stage))


def _encode_private(value: str) -> bytes:
    """账号字段按客户端窄字符集编码；不可表达时停止。"""
    try:
        return value.encode("cp936")
    except UnicodeEncodeError as error:
        raise ClientError("unsupported_credentials", "GUI 账号字段超出客户端字符集，未输入。") from error


def _mark(runtime: JsonObject, name: str) -> None:
    try:
        descriptor = os.open(runtime.run_dir / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ClientError("gui_login_action_unknown", "本次运行已尝试该登录动作，禁止重放。") from error
    except OSError as error:
        raise ClientError("gui_login_action_unknown", "登录动作标记未确认，未输入。") from error
    with os.fdopen(descriptor, "w") as stream:
        stream.write("attempted\n")


def _run_action(
    bridge: BridgeClient, runtime: JsonObject, marker: str, action: str, *arguments: str | bytes, timeout: float = 2.0
) -> JsonObject:
    _mark(runtime, marker)
    return bridge.login_action(action, *arguments, timeout=timeout)


def _act(
    stage: JsonObject,
    page: str,
    runtime: JsonObject,
    bridge: BridgeClient,
    profile: AccountProfile,
    *,
    accept_terms: bool,
    gender: str,
) -> JsonObject:
    if page == "terms":
        if not accept_terms:
            raise ClientError("gui_terms_not_authorized", "未授权同意协议，未输入。")
        address = _window(stage, TERMS_PAGE, width=431, height=426)
        return _run_action(bridge, runtime, "gui-terms-submitted", "accept_terms", address)
    if page == "gender":
        address = _window(stage, GENDER_PAGE, width=354, height=259)
        return _run_action(
            bridge, runtime, "gui-gender-submitted", "select_gender", address, "0" if gender == "male" else "1"
        )
    if page == "credentials":
        address = _window(stage, LOGIN_FORM, width=330, height=180)
        return _run_action(
            bridge,
            runtime,
            "gui-login-submitted",
            "submit_login",
            address,
            _encode_private(profile.username),
            _encode_private(profile.password),
        )
    if page == "world":
        address = _window(stage, WORLD_PANEL, width=400, height=100)
        return _run_action(bridge, runtime, "gui-world-submitted", "select_world", address, str(profile.world))
    if page == "channel":
        address = _window(stage, CHANNEL_PANEL, width=448, height=253)
        return _run_action(
            bridge, runtime, "gui-channel-submitted", "select_channel", str(profile.channel), address
        )
    raise ClientError("gui_login_action_unknown", "登录动作结果不明确，停止输入。")


def _page(stage: JsonObject) -> str | None:
    """按已观察页面分类；登录态的三类窗口集合必须精确匹配。"""
    login = stage.get("login")
    if not isinstance(login, dict) or login.get("request_pending") is not False or login.get("transition_pending") is not False:
        return None
    if stage.get("stage") == "LOGIN":
        signatures = _signatures(stage)
        if TERMS_PAGE in signatures:
            return "terms" if signatures == frozenset((CWND_MAN, SIDE_PANEL, LOGIN_FORM, TERMS_PAGE)) else None
        if GENDER_PAGE in signatures:
            return "gender" if signatures == frozenset((CWND_MAN, SIDE_PANEL, LOGIN_FORM, GENDER_PAGE)) else None
        return "credentials" if signatures == frozenset((CWND_MAN, SIDE_PANEL, LOGIN_FORM)) else None
    if stage.get("stage") == "WORLD_SELECT":
        if _signatures(stage) != frozenset((CWND_MAN, SIDE_PANEL, WORLD_PANEL, SIDE_BUTTONS)):
            return None
        raw = login.get("raw_world_selection")
        if (
            not isinstance(raw, dict)
            or type(raw.get("count")) is not int
            or raw["count"] != 1
            or type(raw.get("selected_index")) is not int
            or raw["selected_index"] != 0
            or type(raw.get("raw_world_id")) is not int
            or raw["raw_world_id"] != 0
        ):
            return None
        return "world"
    if stage.get("stage") == "CHANNEL_SELECT":
        if _signatures(stage) != frozenset((CWND_MAN, SIDE_PANEL, WORLD_PANEL, CHANNEL_PANEL, SIDE_BUTTONS)):
            return None
        return "channel"
    return None


def _channel_ready(stage: JsonObject, profile: AccountProfile) -> bool:
    """频道面板给出目标频道的 1 基频道号且索引一致。"""
    panel = stage.get("channel_panel")
    channels = panel.get("channels") if isinstance(panel, dict) else None
    if (
        stage.get("stage") != "CHANNEL_SELECT"
        or not isinstance(panel, dict)
        or type(panel.get("count")) is not int
        or not 1 <= panel["count"] <= 20
        or not isinstance(channels, list)
        or len(channels) != panel["count"]
    ):
        return False
    matches = [
        channel
        for channel in channels
        if isinstance(channel, dict) and type(channel.get("channel")) is int and channel["channel"] == profile.channel + 1
    ]
    return len(matches) == 1 and type(matches[0].get("index")) is int and matches[0]["index"] == profile.channel


def _execute_locked(
    backend: Backend,
    profile: AccountProfile,
    *,
    instance_id: str,
    run_id: str,
    accept_terms: bool,
    gender: str,
    deadline: float,
) -> JsonObject:
    """有界观察并等待已发出的一次性原生动作，不重复调用。"""
    order = ["terms", "credentials", "gender", "world", "channel"]
    sent_page: str | None = None
    while True:
        _check_deadline(deadline)
        runtime, stage, bridge = _observe(backend, instance_id, run_id)
        login = stage.get("login")
        assert isinstance(login, dict)
        if stage.get("stage") == "CHARACTER_SELECT" and login.get("characters_available") is True:
            if sent_page in (None, "channel"):
                return {
                    "phase": "character_list",
                    "characters": login.get("characters"),
                    "instance_id": instance_id,
                    "run_id": run_id,
                }
        page = _page(stage)
        if page == "channel" and not _channel_ready(stage, profile):
            page = None
        if page == sent_page:
            page = None
        if page is not None:
            if sent_page is not None and order.index(page) <= order.index(sent_page):
                raise ClientError("gui_login_action_unknown", "登录页面回退，禁止重放已发送的输入。")
            _act(stage, page, runtime, bridge, profile, accept_terms=accept_terms, gender=gender)
            sent_page = page
        elif sent_page is None and not (
            stage.get("stage") == "TRANSITION"
            or login.get("request_pending") is True
            or login.get("transition_pending") is True
        ):
            raise ClientError("gui_login_state_unknown", "当前登录页面尚不能安全操作，未输入。")
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
    deadline: float | None = None,
) -> JsonObject:
    """排他控制单个运行实例，其他 login 不接管输入。"""
    if not 0 < timeout <= 180:
        raise ClientError("invalid_login_options", "等待时间须大于零且不超过 180 秒。")
    if gender not in ("male", "female"):
        raise ClientError("invalid_login_options", "性别必须明确指定。")
    if deadline is None:
        deadline = time.monotonic() + timeout
    elif isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ClientError("invalid_login_options", "绝对期限须为有限单调时钟值。")
    runtime = load_runtime(backend.root, backend.name, backend.instance)
    if not runtime.running or runtime.run_id != run_id or runtime.character_id is not None:
        raise ClientError("gui_login_identity_unconfirmed", "GUI 账号会话身份不匹配或已有角色，未输入。")
    if (runtime.world, runtime.channel) != (profile.world, profile.channel):
        raise ClientError("gui_login_identity_unconfirmed", "运行参数与账号文件不一致，未输入。")
    if profile.world != 0:
        raise ClientError("unsupported_capability", "GUI 自动登录目前只验证世界 0。")
    if not 0 <= profile.channel <= 19:
        raise ClientError("unsupported_capability", "GUI 自动登录目前只验证第 1 至 20 频道。")
    _check_deadline(deadline)
    try:
        descriptor = os.open(runtime.run_dir / "gui-login.lock", os.O_CREAT | os.O_RDWR, 0o600)
    except OSError as error:
        raise ClientError("gui_login_identity_unconfirmed", "登录控制器锁不可用，未输入。") from error
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
            deadline=deadline,
        )
