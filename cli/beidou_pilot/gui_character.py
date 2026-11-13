"""GUI 建角：经原生桥调用原版客户端内部建角动作并保守核验结果。"""

from dataclasses import asdict
import fcntl
import json
import math
import os
import time
from pathlib import Path
import re
import uuid

from .errors import ClientError, JsonObject
from .profile import CharacterCreation, validate_character_creation
from .login_bridge import LoginBridge
from .bridge import BridgeClient, require_input_idle
from .backend import Backend
from .runtime import load_runtime


def record_attempt(
    directory: Path, *, instance_id: str, run_id: str, params: CharacterCreation, previous_ids: set[int]
) -> JsonObject:
    """在任何建角输入前持久化唯一尝试；同一运行目录禁止再次认领。"""
    validate_character_creation(params)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", instance_id) or not run_id:
        raise ClientError("login_bridge_invalid_identity", "建角实例身份无效。")
    if any(type(value) is not int or not 0 < value < 2**31 for value in previous_ids):
        raise ClientError("login_bridge_invalid_state", "原角色列表包含无效 CID。")
    record: JsonObject = {
        "protocol": 1,
        "operation": "create_character",
        "request_id": uuid.uuid4().hex,
        "instance_id": instance_id,
        "run_id": run_id,
        "params": asdict(params),
        "previous_ids": sorted(previous_ids),
        "status": "unknown",
    }
    try:
        descriptor = os.open(directory / "gui-character-attempt.json", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        details: JsonObject = {"instance_id": instance_id, "run_id": run_id}
        try:
            with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
                existing = json.load(stream)
            if (
                isinstance(existing, dict)
                and existing.get("instance_id") == instance_id
                and existing.get("run_id") == run_id
                and isinstance(existing.get("request_id"), str)
                and re.fullmatch(r"[0-9a-f]{32}", existing["request_id"])
            ):
                details["request_id"] = existing["request_id"]
        except (OSError, ValueError):
            pass
        raise ClientError("gui_character_already_attempted", "本次运行已有建角尝试，禁止重发。", details) from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise ClientError(
            "login_bridge_write_failed",
            "建角尝试持久化结果不明，禁止重发。",
            {"request_id": record["request_id"], "instance_id": instance_id, "run_id": run_id},
        ) from error
    return record


def query_result(directory: Path, *, instance_id: str, run_id: str, request_id: str) -> JsonObject:
    """沿用登录桥结果文件协议，缺失文件保持未知。"""
    result = LoginBridge(directory, instance_id, run_id).result(request_id)
    return {"instance_id": instance_id, "run_id": run_id, **result}


def mark_final_submit(directory: Path, *, instance_id: str, run_id: str, request_id: str) -> None:
    """最终确认输入前先记账；该标记只证明已尝试，不证明输入成功。"""
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ClientError("login_bridge_invalid_request", "请求身份无效。")
    try:
        with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
            record = json.load(stream)
        if (
            not isinstance(record, dict)
            or record.get("request_id") != request_id
            or record.get("instance_id") != instance_id
            or record.get("run_id") != run_id
        ):
            raise ClientError("gui_character_identity_unconfirmed", "建角请求身份不符，未确认。")
        descriptor = os.open(directory / "gui-character-final-submit", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(request_id)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ClientError("gui_character_already_attempted", "最终确认已尝试，禁止重发。") from error
    except (OSError, ValueError) as error:
        raise ClientError(
            "login_bridge_write_failed",
            "最终确认标记未确认，禁止输入。",
            {"request_id": request_id, "instance_id": instance_id, "run_id": run_id},
        ) from error


def record_final_dispatch(directory: Path, *, instance_id: str, run_id: str, request_id: str, dispatched: bool) -> None:
    """只记录明确的单次原生动作回执；进程中断时保留未知。"""
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ClientError("login_bridge_invalid_request", "请求身份无效。")
    if dispatched is not True:
        raise ClientError("gui_character_action_unknown", "最终确认派发结果不明，禁止重发。")
    try:
        with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
            record = json.load(stream)
        if (
            not isinstance(record, dict)
            or record.get("request_id") != request_id
            or record.get("instance_id") != instance_id
            or record.get("run_id") != run_id
            or (directory / "gui-character-final-submit").read_text(encoding="utf-8") != request_id
        ):
            raise ClientError("gui_character_identity_unconfirmed", "最终确认请求身份不符。")
        descriptor = os.open(directory / "gui-character-final-dispatched", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(request_id)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ClientError("gui_character_already_attempted", "最终确认回执已记录，禁止重发。") from error
    except (OSError, ValueError) as error:
        raise ClientError(
            "login_bridge_write_failed",
            "最终确认回执持久化未确认，禁止重发。",
            {"request_id": request_id, "instance_id": instance_id, "run_id": run_id},
        ) from error


def persist_result(
    directory: Path, *, bridge_directory: Path, instance_id: str, run_id: str, request_id: str, state: JsonObject
) -> JsonObject:
    """核验新增角色并写入登录桥结果。

    调用方须已核实全部参数、向该请求发送最终确认并提供新鲜观察；
    本函数只核验角色身份，不验证外观或提交是否成功发送。
    """
    bridge = LoginBridge(bridge_directory, instance_id, run_id)
    existing = bridge.result(request_id)
    if existing["status"] in ("completed", "rejected"):
        return existing
    try:
        with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
            record = json.load(stream)
        if (directory / "gui-character-final-submit").read_text(encoding="utf-8") != request_id or (
            directory / "gui-character-final-dispatched"
        ).read_text(encoding="utf-8") != request_id:
            return {"request_id": request_id, "instance_id": instance_id, "run_id": run_id, "status": "unknown"}
    except (OSError, ValueError):
        return {"request_id": request_id, "instance_id": instance_id, "run_id": run_id, "status": "unknown"}
    if (
        not isinstance(record, dict)
        or record.get("protocol") != 1
        or record.get("operation") != "create_character"
        or record.get("instance_id") != instance_id
        or record.get("run_id") != run_id
        or record.get("request_id") != request_id
        or not isinstance(record.get("params"), dict)
        or not isinstance(record["params"].get("name"), str)
        or not isinstance(record.get("previous_ids"), list)
        or any(type(cid) is not int or not 0 < cid < 2**31 for cid in record["previous_ids"])
    ):
        return {"request_id": request_id, "instance_id": instance_id, "run_id": run_id, "status": "unknown"}
    result = verify_created_character(
        state,
        instance_id=instance_id,
        run_id=run_id,
        name=record["params"]["name"],
        previous_ids=set(record["previous_ids"]),
    )
    result = {"protocol": 1, "operation": "create_character", "request_id": request_id, **result}
    if result["status"] != "completed":
        return result
    try:
        with (bridge_directory / "login.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            # LoginBridge.result treats every OSError as missing. Before replacing,
            # distinguish a genuinely missing result from an unreadable terminal one.
            result_path = bridge_directory / "login-results" / (request_id + ".json")
            missing = False
            try:
                with result_path.open(encoding="utf-8") as stream:
                    current = json.load(stream)
            except FileNotFoundError:
                missing = True
                current = None
            except OSError as error:
                raise ClientError("login_bridge_unavailable", "无法读取现有建角结果，未覆盖。") from error
            except ValueError as error:
                raise ClientError("login_bridge_invalid_result", "现有建角结果无效，未覆盖。") from error
            if not missing:
                if (
                    not isinstance(current, dict)
                    or type(current.get("protocol")) is not int
                    or current["protocol"] != 1
                    or current.get("instance_id") != instance_id
                    or current.get("run_id") != run_id
                    or current.get("request_id") != request_id
                    or current.get("operation") != "create_character"
                    or current.get("status") not in ("accepted", "unknown", "completed", "rejected")
                    or (
                        current.get("status") == "completed"
                        and (type(current.get("character_id")) is not int or not 0 < current["character_id"] < 2**31)
                    )
                    or (
                        current.get("character_id") is not None
                        and (type(current["character_id"]) is not int or not 0 < current["character_id"] < 2**31)
                    )
                    or (current.get("error") is not None and not isinstance(current["error"], str))
                ):
                    raise ClientError("login_bridge_invalid_result", "现有建角结果或身份无效，未覆盖。")
                if current["status"] in ("completed", "rejected"):
                    return current
            results = bridge_directory / "login-results"
            results.mkdir(exist_ok=True)
            temporary = results / (request_id + "-" + uuid.uuid4().hex + ".tmp")
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(results / (request_id + ".json"))
    except OSError as error:
        raise ClientError(
            "login_bridge_write_failed",
            "建角结果持久化未确认；禁止重发。",
            {"request_id": request_id, "instance_id": instance_id, "run_id": run_id},
        ) from error
    return result


def require_supported_creation(params: CharacterCreation) -> None:
    """校验当前原生姓名候选可表达的参数；可选项能否到达由遍历判断。"""
    validate_character_creation(params)
    if params.job != 1:
        raise ClientError("unsupported_capability", "GUI 目前只验证冒险家建角类别 job=1。")
    if any(not 32 <= ord(ch) <= 126 for ch in params.name):
        raise ClientError("unsupported_capability", "GUI 目前无法核验非 ASCII 姓名。")


def plan_observed_appearance_step(params: CharacterCreation, raw: list[int], seen: list[set[int]]) -> JsonObject:
    """按封包字段顺序逐槽比较；调用前仍须实测并核对性别、职业候选。"""
    validate_character_creation(params)
    if not isinstance(raw, list) or len(raw) != 8 or any(type(value) is not int for value in raw) or len(seen) != 8:
        return {"status": "unknown"}
    desired = (
        params.face,
        params.hair,
        params.hair_color,
        params.skin,
        params.top,
        params.bottom,
        params.shoes,
        params.weapon,
    )
    for index, (current, target) in enumerate(zip(raw, desired)):
        if current != target:
            if current in seen[index]:
                return {"status": "unavailable", "field": index}
            return {"status": "step", "field": index, "control_id": 1011 + index}
    return {"status": "matched"}


def validate_appearance_transition(before: list[int], after: list[int], field: int) -> bool:
    """仅当目标槽发生变化且其他七槽不变时确认一次外观动作。"""
    return (
        type(field) is int
        and 0 <= field < 8
        and isinstance(before, list)
        and isinstance(after, list)
        and len(before) == len(after) == 8
        and all(type(value) is int for value in before + after)
        and before[field] != after[field]
        and all(left == right for index, (left, right) in enumerate(zip(before, after)) if index != field)
    )


CATEGORY_PAGE = ("0xaf7360", "0xaf7314", "0xaf7310")
NAME_PAGE = ("0xaf7564", "0xaf7518", "0xaf7514")
APPEARANCE_PAGE = ("0xaf777c", "0xaf7730", "0xaf772c")
CHARACTER_CREATE_PANEL = ("0xaf6d90", "0xaf6d44", "0xaf6d40")

CREATION_PAGES = (
    ("category", CATEGORY_PAGE, 700, 460),
    ("name", NAME_PAGE, 201, 224),
    ("appearance", APPEARANCE_PAGE, 225, 377),
)


def _address(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", value) or int(value, 16) == 0:
        raise ClientError("gui_character_state_unknown", "窗口原生地址不可确认，未输入。")
    return value


def identify_creation_page(stage: JsonObject, *, instance_id: str, run_id: str) -> str:
    """按已观察窗口 vtable 与尺寸识别建角页；识别不代表参数已验证。"""
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
        return "unknown"
    windows = stage.get("windows")
    if not isinstance(windows, list):
        return "unknown"
    for page, signature, width, height in CREATION_PAGES:
        matches = [
            window
            for window in windows
            if isinstance(window, dict)
            and window.get("vtables") == list(signature)
            and window.get("width") == width
            and window.get("height") == height
        ]
        if len(matches) == 1:
            return page
    return "unknown"


def _creation_window(stage: JsonObject, page: str) -> tuple[str, JsonObject]:
    for name, signature, width, height in CREATION_PAGES:
        if name != page:
            continue
        windows = stage.get("windows")
        matches = (
            [window for window in windows if isinstance(window, dict) and window.get("vtables") == list(signature)]
            if isinstance(windows, list)
            else []
        )
        if len(matches) != 1 or matches[0].get("width") != width or matches[0].get("height") != height:
            raise ClientError("gui_character_state_unknown", "建角页面或窗口身份不可确认，未输入。")
        return _address(matches[0].get("address")), matches[0]
    raise ClientError("gui_character_state_unknown", "建角页面不可确认，未输入。")


def _observe(backend: Backend, instance_id: str, run_id: str):
    """核对实例身份、原生输入空闲与页面观察，返回新鲜 stage 与桥客户端。"""
    runtime = load_runtime(backend.root, backend.name, backend.instance)
    if backend.name != "beidou" or not runtime.running or runtime.run_id != run_id:
        raise ClientError("gui_character_state_unknown", "建角实例身份已改变，未输入。")
    bridge = BridgeClient(backend.root, backend.name, backend.instance)
    native = bridge.snapshot()
    if native.get("instance_id") != instance_id or native.get("run_id") != run_id:
        raise ClientError("gui_character_identity_unconfirmed", "原生桥身份不匹配，未输入。")
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
    ):
        raise ClientError("gui_character_state_unknown", "建角观察或实例身份不明确，未输入。")
    return runtime, stage, bridge


def _require_attempt(
    directory: Path, params: CharacterCreation, *, request_id: str, instance_id: str, run_id: str
) -> JsonObject:
    try:
        with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
            record = json.load(stream)
    except (OSError, ValueError) as error:
        raise ClientError("gui_character_state_unknown", "建角请求不可读取。") from error
    if (
        not isinstance(record, dict)
        or record.get("instance_id") != instance_id
        or record.get("run_id") != run_id
        or record.get("request_id") != request_id
        or record.get("params") != asdict(params)
    ):
        raise ClientError("gui_character_identity_unconfirmed", "建角请求身份或参数不匹配。")
    return record


def _marker(directory: Path, name: str) -> bool:
    return (directory / name).exists()


def _mark(directory: Path, name: str, request_id: str) -> None:
    try:
        descriptor = os.open(directory / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ClientError("gui_character_already_attempted", "该建角步骤已尝试，禁止重放。") from error
    except OSError as error:
        raise ClientError("login_bridge_write_failed", "建角步骤标记未确认，未输入。") from error
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(request_id)
        stream.flush()
        os.fsync(stream.fileno())


def _open_creation(
    backend: Backend,
    params: CharacterCreation,
    *,
    directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    deadline: float,
) -> JsonObject:
    """空列表下由原版角色列表按钮打开建角；只观察类别页。"""
    _require_attempt(directory, params, request_id=request_id, instance_id=instance_id, run_id=run_id)
    for name in (
        "gui-character-final-submit",
        "gui-character-appearance-attempt",
        "gui-character-name-attempt",
        "gui-character-category-attempt",
    ):
        if _marker(directory, name):
            raise ClientError("gui_character_already_attempted", "建角请求已进入后续阶段，禁止重放。")
    _, stage, bridge = _observe(backend, instance_id, run_id)
    login = stage.get("login")
    if (
        stage.get("stage") != "CHARACTER_SELECT"
        or not isinstance(login, dict)
        or login.get("raw_step") != 2
        or login.get("characters_available") is not True
        or login.get("characters") != []
        or login.get("request_pending") is not False
        or login.get("transition_pending") is not False
    ):
        raise ClientError("gui_character_state_unknown", "空角色列表或实例状态不明确，未输入。")
    windows = stage.get("windows")
    matches = (
        [
            window
            for window in windows
            if isinstance(window, dict) and window.get("vtables") == list(CHARACTER_CREATE_PANEL)
        ]
        if isinstance(windows, list)
        else []
    )
    if len(matches) != 1 or matches[0].get("width") != 101 or matches[0].get("height") != 131:
        raise ClientError("gui_character_state_unknown", "角色创建按钮窗口不可确认，未输入。")
    address = _address(matches[0].get("address"))
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    _mark(directory, "gui-character-open-attempt", request_id)
    bridge.login_action("ui_button", address, "1001")
    while time.monotonic() < deadline:
        _, current, _ = _observe(backend, instance_id, run_id)
        if identify_creation_page(current, instance_id=instance_id, run_id=run_id) == "category":
            return {"status": "category_page"}
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    return {"status": "unknown", "reason": "next_page_unconfirmed"}


def _navigate_category(
    backend: Backend,
    params: CharacterCreation,
    *,
    directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    deadline: float,
) -> JsonObject:
    """类别页单次确认默认类别；后续仅观察姓名页。"""
    _require_attempt(directory, params, request_id=request_id, instance_id=instance_id, run_id=run_id)
    for name in ("gui-character-final-submit", "gui-character-appearance-attempt", "gui-character-name-attempt"):
        if _marker(directory, name):
            raise ClientError("gui_character_already_attempted", "请求已进入后续阶段，禁止重放类别确认。")
    _, stage, bridge = _observe(backend, instance_id, run_id)
    if identify_creation_page(stage, instance_id=instance_id, run_id=run_id) != "category":
        raise ClientError("gui_character_state_unknown", "类别页面不明确，停止输入。")
    address, _ = _creation_window(stage, "category")
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    _mark(directory, "gui-character-category-attempt", request_id)
    bridge.login_action("ui_button", address, "1003")
    while time.monotonic() < deadline:
        _, current, _ = _observe(backend, instance_id, run_id)
        if identify_creation_page(current, instance_id=instance_id, run_id=run_id) == "name":
            return {"status": "name_page"}
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    return {"status": "unknown", "reason": "next_page_unconfirmed"}


def _submit_name(
    backend: Backend,
    params: CharacterCreation,
    *,
    directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    deadline: float,
) -> JsonObject:
    """姓名页单次发起姓名核查；核查结果由页面推进体现，不重复提交。"""
    require_supported_creation(params)
    _require_attempt(directory, params, request_id=request_id, instance_id=instance_id, run_id=run_id)
    for name in ("gui-character-final-submit", "gui-character-appearance-attempt"):
        if _marker(directory, name):
            raise ClientError("gui_character_already_attempted", "请求已进入后续阶段，禁止重放姓名核查。")
    _, stage, bridge = _observe(backend, instance_id, run_id)
    if identify_creation_page(stage, instance_id=instance_id, run_id=run_id) != "name":
        raise ClientError("gui_character_state_unknown", "姓名页面不明确，停止输入。")
    address, _ = _creation_window(stage, "name")
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    _mark(directory, "gui-character-name-attempt", request_id)
    bridge.login_action("check_name", address, params.name.encode("ascii"))
    while time.monotonic() < deadline:
        _, current, _ = _observe(backend, instance_id, run_id)
        if identify_creation_page(current, instance_id=instance_id, run_id=run_id) == "appearance":
            _mark(directory, "gui-character-name-checked", request_id)
            return {"status": "appearance_page"}
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    return {"status": "unknown", "reason": "next_page_unconfirmed"}


def _set_gender(
    backend: Backend,
    params: CharacterCreation,
    *,
    directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    deadline: float,
) -> JsonObject:
    """外观页单次切换外观性别；切换后核对选择与职业。"""
    require_supported_creation(params)
    _require_attempt(directory, params, request_id=request_id, instance_id=instance_id, run_id=run_id)
    checked = directory / "gui-character-name-checked"
    try:
        if checked.read_text(encoding="utf-8") != request_id:
            raise ClientError("gui_character_state_unknown", "姓名核查未确认。")
    except OSError as error:
        raise ClientError("gui_character_state_unknown", "姓名核查结果不可读取。") from error
    for name in ("gui-character-final-submit", "gui-character-appearance-attempt"):
        if _marker(directory, name):
            raise ClientError("gui_character_already_attempted", "后续步骤已尝试，禁止重放。")
    _, stage, bridge = _observe(backend, instance_id, run_id)
    if identify_creation_page(stage, instance_id=instance_id, run_id=run_id) != "appearance":
        raise ClientError("gui_character_state_unknown", "外观页面不明确，停止输入。")
    address, window = _creation_window(stage, "appearance")
    selector, job = window.get("raw_appearance_selector"), window.get("raw_job_candidate")
    if type(job) is not int or job != params.job or type(selector) is not int or selector not in (0, 1):
        raise ClientError("gui_character_state_unknown", "职业或外观性别不可确认，停止输入。")
    if selector == int(params.female):
        return {"status": "matched"}
    if _marker(directory, "gui-character-gender-attempt"):
        raise ClientError("gui_character_already_attempted", "性别切换已尝试，禁止重放。")
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    _mark(directory, "gui-character-gender-attempt", request_id)
    bridge.login_action("ui_button", address, "1019")
    while time.monotonic() < deadline:
        _, current, _ = _observe(backend, instance_id, run_id)
        if identify_creation_page(current, instance_id=instance_id, run_id=run_id) != "appearance":
            raise ClientError("gui_character_action_unknown", "性别切换后页面变化不明确。")
        _, observed = _creation_window(current, "appearance")
        if observed.get("raw_job_candidate") != params.job:
            raise ClientError("gui_character_state_unknown", "性别切换后职业值变化。")
        if observed.get("raw_appearance_selector") == int(params.female):
            return {"status": "matched"}
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    return {"status": "unknown", "reason": "timeout"}


def _appearance_step(
    backend: Backend,
    params: CharacterCreation,
    seen: list[set[int]],
    *,
    directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    deadline: float,
) -> JsonObject:
    """外观页发送最多一次原生轮转，并核对只有目标槽发生变化。"""
    _require_attempt(directory, params, request_id=request_id, instance_id=instance_id, run_id=run_id)
    if _marker(directory, "gui-character-final-submit"):
        raise ClientError("gui_character_state_unknown", "最终提交已尝试，禁止输入。")
    _, stage, bridge = _observe(backend, instance_id, run_id)
    if identify_creation_page(stage, instance_id=instance_id, run_id=run_id) != "appearance":
        raise ClientError("gui_character_state_unknown", "外观页面或实例状态不明确，停止输入。")
    address, window = _creation_window(stage, "appearance")
    raw = window.get("raw_appearance_candidates")
    selector, job = window.get("raw_appearance_selector"), window.get("raw_job_candidate")
    if (
        not isinstance(raw, list)
        or len(raw) != 8
        or any(type(value) is not int for value in raw)
        or type(job) is not int
        or job != params.job
        or type(selector) is not int
        or selector != int(params.female)
    ):
        raise ClientError("gui_character_state_unknown", "外观原始值、职业或性别不可确认。")
    plan = plan_observed_appearance_step(params, raw, seen)
    if plan["status"] != "step":
        return plan
    control, field = plan["control_id"], plan["field"]
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    seen[field].add(raw[field])
    bridge.login_action("ui_button", address, str(control))
    _, after_stage, _ = _observe(backend, instance_id, run_id)
    if identify_creation_page(after_stage, instance_id=instance_id, run_id=run_id) != "appearance":
        raise ClientError("gui_character_action_unknown", "外观轮转后页面变化不明确。")
    after_address, after_window = _creation_window(after_stage, "appearance")
    after = after_window.get("raw_appearance_candidates")
    if after_address != address or not validate_appearance_transition(raw, after, field):
        raise ClientError("gui_character_action_unknown", "外观变化不明确，停止输入。")
    return {"status": "changed", "field": field, "raw": after}


def _apply_appearance(
    backend: Backend,
    params: CharacterCreation,
    *,
    directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    timeout: float,
) -> JsonObject:
    """按已观察候选逐槽轮转到目标值；超时不回退或重放。"""
    require_supported_creation(params)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ClientError("usage", "外观等待时间须为正有限数。")
    if _marker(directory, "gui-character-appearance-attempt"):
        raise ClientError("gui_character_already_attempted", "外观调整已尝试，禁止重放。")
    _mark(directory, "gui-character-appearance-attempt", request_id)
    deadline = time.monotonic() + timeout
    seen: list[set[int]] = [set() for _ in range(8)]
    while time.monotonic() < deadline:
        result = _appearance_step(
            backend,
            params,
            seen,
            directory=directory,
            request_id=request_id,
            instance_id=instance_id,
            run_id=run_id,
            deadline=deadline,
        )
        if result["status"] != "changed":
            return result
    return {"status": "unknown", "reason": "timeout"}


def _final_state(stage: JsonObject, params: CharacterCreation, *, instance_id: str, run_id: str) -> JsonObject | None:
    """最终提交前的纯比较：页面、外观、职业、性别与创建按钮就绪。"""
    if identify_creation_page(stage, instance_id=instance_id, run_id=run_id) != "appearance":
        return None
    try:
        address, window = _creation_window(stage, "appearance")
    except ClientError:
        return None
    expected = [
        params.face,
        params.hair,
        params.hair_color,
        params.skin,
        params.top,
        params.bottom,
        params.shoes,
        params.weapon,
    ]
    raw = window.get("raw_appearance_candidates")
    if (
        not isinstance(raw, list)
        or len(raw) != 8
        or any(type(value) is not int for value in raw)
        or raw != expected
        or window.get("raw_job_candidate") != params.job
        or type(window.get("raw_appearance_selector")) is not int
        or window["raw_appearance_selector"] != int(params.female)
    ):
        return None
    buttons = window.get("buttons")
    create = (
        [button for button in buttons if isinstance(button, dict) and button.get("control_id") == 1000]
        if isinstance(buttons, list)
        else []
    )
    if len(create) != 1 or create[0].get("enabled") is not True:
        return None
    return {"address": address}


def _submit_creation(
    backend: Backend,
    params: CharacterCreation,
    *,
    directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    deadline: float,
) -> JsonObject:
    """单次最终确认；调用方持公共输入锁，未知结果不可重放。"""
    require_supported_creation(params)
    unknown: JsonObject = {"request_id": request_id, "instance_id": instance_id, "run_id": run_id, "status": "unknown"}
    _require_attempt(directory, params, request_id=request_id, instance_id=instance_id, run_id=run_id)
    try:
        if (directory / "gui-character-name-checked").read_text(encoding="utf-8") != request_id:
            raise ClientError("gui_character_state_unknown", "姓名核查未确认。")
    except OSError as error:
        raise ClientError("gui_character_state_unknown", "姓名核查结果不可读取。") from error
    if _marker(directory, "gui-character-final-submit"):
        raise ClientError("gui_character_already_attempted", "最终确认已尝试，禁止重发。")
    _, stage, bridge = _observe(backend, instance_id, run_id)
    target = _final_state(stage, params, instance_id=instance_id, run_id=run_id)
    if target is None or time.monotonic() >= deadline:
        return unknown
    _mark(directory, "gui-character-final-submit", request_id)
    _, again, bridge = _observe(backend, instance_id, run_id)
    if _final_state(again, params, instance_id=instance_id, run_id=run_id) != target:
        return unknown
    bridge.login_action("ui_button", target["address"], "1000")
    record_final_dispatch(directory, instance_id=instance_id, run_id=run_id, request_id=request_id, dispatched=True)
    return unknown


def _wait_creation_result(
    backend: Backend,
    *,
    directory: Path,
    bridge_directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    deadline: float,
) -> JsonObject:
    """只读等待同实例角色增量并持久化结果，绝不重发输入。"""
    identity: JsonObject = {"request_id": request_id, "instance_id": instance_id, "run_id": run_id}
    previous = None
    while True:
        try:
            result = query_result(bridge_directory, instance_id=instance_id, run_id=run_id, request_id=request_id)
            if result["status"] in ("completed", "rejected"):
                return result
            runtime = load_runtime(backend.root, backend.name, backend.instance)
            native = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
            if (
                not runtime.running
                or runtime.run_id != run_id
                or native.get("instance_id") != instance_id
                or native.get("run_id") != run_id
            ):
                return {**identity, "status": "unknown"}
            stage = backend.read("stage")
            login = stage.get("login")
            fingerprint = json.dumps(
                {
                    "instance_id": stage.get("instance_id"),
                    "client": stage.get("client"),
                    "stage": stage.get("stage"),
                    "unavailable": stage.get("unavailable"),
                    "login": login,
                },
                sort_keys=True,
            )
            if fingerprint == previous:
                result = persist_result(
                    directory,
                    bridge_directory=bridge_directory,
                    instance_id=instance_id,
                    run_id=run_id,
                    request_id=request_id,
                    state=stage,
                )
                if result["status"] in ("completed", "rejected"):
                    return result
            previous = fingerprint
        except ClientError:
            return {**identity, "status": "unknown"}
        if time.monotonic() >= deadline:
            return {**identity, "status": "unknown"}
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def observe_result(
    backend: Backend,
    *,
    directory: Path,
    bridge_directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    timeout: float = 0,
) -> JsonObject:
    """查询或安全复查结果；不取得公共输入锁，不发送输入。"""
    if not math.isfinite(timeout) or timeout < 0:
        raise ClientError("usage", "结果等待时间须为非负有限数。")
    return _wait_creation_result(
        backend,
        directory=directory,
        bridge_directory=bridge_directory,
        request_id=request_id,
        instance_id=instance_id,
        run_id=run_id,
        deadline=time.monotonic() + timeout,
    )


def _create_once_locked(
    backend: Backend, params: CharacterCreation, *, directory: Path, instance_id: str, run_id: str, timeout: float
) -> JsonObject:
    """公共 input_lock 和 per-run character.lock 已由调用方持有。"""
    require_supported_creation(params)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ClientError("usage", "建角等待时间须为正有限数。")
    exists = True
    try:
        with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
            existing = json.load(stream)
    except FileNotFoundError:
        exists = False
        existing = None
    except (OSError, ValueError) as error:
        raise ClientError(
            "gui_character_state_unknown",
            "已有建角请求不可读取，禁止重发。",
            {"instance_id": instance_id, "run_id": run_id},
        ) from error
    if exists:
        details: JsonObject = {"instance_id": instance_id, "run_id": run_id}
        if (
            isinstance(existing, dict)
            and existing.get("instance_id") == instance_id
            and existing.get("run_id") == run_id
            and isinstance(existing.get("request_id"), str)
            and re.fullmatch(r"[0-9a-f]{32}", existing["request_id"])
        ):
            details["request_id"] = existing["request_id"]
        raise ClientError("gui_character_already_attempted", "本次运行已有建角尝试，禁止重发。", details)
    deadline = time.monotonic() + timeout
    runtime = load_runtime(backend.root, backend.name, backend.instance)
    require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
    stage = backend.read("stage")
    login = stage.get("login")
    client = stage.get("client")
    if (
        backend.name != "beidou"
        or not runtime.running
        or runtime.run_id != run_id
        or stage.get("instance_id") != instance_id
        or not isinstance(client, dict)
        or client.get("run_id") != run_id
        or stage.get("unavailable") != []
        or stage.get("stage") != "CHARACTER_SELECT"
        or not isinstance(login, dict)
        or login.get("characters_available") is not True
        or login.get("request_pending") is not False
        or login.get("transition_pending") is not False
        or not isinstance(login.get("characters"), list)
    ):
        raise ClientError("gui_character_state_unknown", "角色列表或实例状态不明确，未输入。")
    characters = login["characters"]
    if any(
        not isinstance(c, dict)
        or type(c.get("id")) is not int
        or not 0 < c["id"] < 2**31
        or not isinstance(c.get("name"), str)
        or not c["name"]
        for c in characters
    ) or len({c["id"] for c in characters}) != len(characters):
        raise ClientError("gui_character_state_unknown", "角色列表不完整，未输入。")
    if any(c["name"] == params.name for c in characters):
        raise ClientError("gui_character_name_exists", "角色列表已有同名角色，未输入。")
    if characters:
        raise ClientError("unsupported_capability", "GUI 建角目前只验证空角色列表，未输入。")
    record = record_attempt(
        directory, instance_id=instance_id, run_id=run_id, params=params, previous_ids={c["id"] for c in characters}
    )
    identity = {"request_id": record["request_id"], "instance_id": instance_id, "run_id": run_id}
    arguments = {"directory": directory, **identity, "deadline": deadline}
    try:
        for operation, expected in (
            (_open_creation, "category_page"),
            (_navigate_category, "name_page"),
            (_submit_name, "appearance_page"),
            (_set_gender, "matched"),
        ):
            result = operation(backend, params, **arguments)
            if result.get("status") != expected:
                return {**identity, "status": "unknown", "reason": result.get("reason")}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {**identity, "status": "unknown", "reason": "timeout"}
        result = _apply_appearance(backend, params, directory=directory, **identity, timeout=remaining)
        if result.get("status") != "matched":
            return {**identity, "status": "unknown", "reason": result.get("reason")}
        _submit_creation(backend, params, **arguments)
        try:
            dispatched = (directory / "gui-character-final-dispatched").read_text(encoding="utf-8")
        except FileNotFoundError:
            return {**identity, "status": "unknown", "reason": "final_dispatch_unconfirmed"}
        if dispatched != identity["request_id"]:
            return {**identity, "status": "unknown", "reason": "final_dispatch_unconfirmed"}
        return _wait_creation_result(
            backend, bridge_directory=BridgeClient(backend.root, backend.name, backend.instance).directory, **arguments
        )
    except ClientError as error:
        return {**identity, "status": "unknown", "reason": error.code}
    except (OSError, KeyboardInterrupt):
        return {**identity, "status": "unknown", "reason": "operation_unconfirmed"}


def create_once(
    backend: Backend, params: CharacterCreation, *, directory: Path, instance_id: str, run_id: str, timeout: float
) -> JsonObject:
    """外层持公共 input_lock；此处依次取得 per-run 锁和短时结果锁。"""
    runtime = load_runtime(backend.root, backend.name, backend.instance)
    if runtime.run_id != run_id or Path(runtime.run_dir).resolve() != directory.resolve():
        raise ClientError("gui_character_identity_unconfirmed", "运行目录或实例不匹配。")
    descriptor = os.open(directory / "gui-character.lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ClientError("input_busy", "本次运行已有建角操作。") from error
        return _create_once_locked(
            backend, params, directory=directory, instance_id=instance_id, run_id=run_id, timeout=timeout
        )


def verify_created_character(
    state: JsonObject, *, instance_id: str, run_id: str, name: str, previous_ids: set[int]
) -> JsonObject:
    """仅从新鲜调用方观察到的角色列表核验唯一新增 CID。

    调用方须在同一已确认的请求前保存完整角色列表，并负责确认状态新鲜度。
    观察不确定时返回 unknown，不能据此重发请求。
    """
    client = state.get("client")
    login = state.get("login")
    unknown: JsonObject = {"status": "unknown", "instance_id": instance_id, "run_id": run_id}
    if (
        not name
        or state.get("instance_id") != instance_id
        or not isinstance(client, dict)
        or client.get("run_id") != run_id
        or state.get("unavailable") != []
        or state.get("stage") != "CHARACTER_SELECT"
        or not isinstance(login, dict)
        or login.get("characters_available") is not True
        or login.get("request_pending") is not False
        or login.get("transition_pending") is not False
    ):
        return unknown
    characters = login.get("characters")
    if not isinstance(characters, list) or any(
        not isinstance(c, dict)
        or type(c.get("id")) is not int
        or not 0 < c["id"] < 2**31
        or not isinstance(c.get("name"), str)
        or not c["name"]
        for c in characters
    ):
        return unknown
    ids = [c["id"] for c in characters]
    if len(ids) != len(set(ids)) or not previous_ids.issubset(ids):
        return unknown
    added = [c for c in characters if c["id"] not in previous_ids]
    if len(added) != 1 or added[0]["name"] != name:
        return unknown
    return {**unknown, "status": "completed", "character_id": added[0]["id"]}
