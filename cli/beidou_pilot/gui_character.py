"""GUI 建角结果的保守核验；当前不支持提交未经验证的外观参数。"""

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
from .gui_login import _dispatched
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


def record_final_dispatch(
    directory: Path, *, instance_id: str, run_id: str, request_id: str, receipt: JsonObject
) -> None:
    """只记录明确的单次点击派发回执；进程中断时保留未知。"""
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ClientError("login_bridge_invalid_request", "请求身份无效。")
    if not _dispatched(receipt, "click"):
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


def _require_verified_gui_candidates() -> None:
    """b3cf354 空姓名、a7c0fb7 冒险家职业和性别候选已实测。"""


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
    """发送最多一次右箭头；调用方先确认性别并独占 GUI，异常时禁止重放。"""

    def observe():
        try:
            with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
                record = json.load(stream)
        except (OSError, ValueError) as error:
            raise ClientError("gui_character_state_unknown", "建角请求不可读取，停止输入。") from error
        try:
            (directory / "gui-character-final-submit").stat()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise ClientError("gui_character_state_unknown", "无法确认最终提交状态。") from error
        else:
            raise ClientError("gui_character_state_unknown", "最终提交已尝试，禁止输入。")
        if (
            not isinstance(record, dict)
            or record.get("request_id") != request_id
            or record.get("instance_id") != instance_id
            or record.get("run_id") != run_id
            or record.get("params") != asdict(params)
        ):
            raise ClientError("gui_character_identity_unconfirmed", "建角请求身份或参数不匹配。")
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
        stage = backend.read("stage")
        dialog = backend.read("dialog")
        if (
            backend.name != "beidou"
            or not runtime.running
            or runtime.run_id != run_id
            or identify_creation_page(stage, dialog, instance_id=instance_id, run_id=run_id) != "appearance"
            or dialog.get("script_dialog_open") is not False
            or dialog.get("focused_talk_dialog_open") is not False
            or dialog.get("registered_talk_dialog_open") is not False
        ):
            raise ClientError("gui_character_state_unknown", "外观页面或实例状态不明确，停止输入。")
        focused = dialog["focused_window"]
        windows = stage.get("windows")
        address = focused.get("address")
        if not isinstance(address, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", address) or int(address, 16) == 0:
            raise ClientError("gui_character_state_unknown", "外观窗口地址不可确认。")
        matches = (
            [window for window in windows if isinstance(window, dict) and window.get("address") == address]
            if isinstance(windows, list)
            else []
        )
        if len(matches) != 1 or matches[0].get("vtables") != focused.get("vtables"):
            raise ClientError("gui_character_state_unknown", "外观窗口身份不明确。")
        raw = matches[0].get("raw_appearance_candidates")
        if (
            not isinstance(raw, list)
            or len(raw) != 8
            or any(type(value) is not int for value in raw)
            or type(matches[0].get("raw_job_candidate")) is not int
            or matches[0]["raw_job_candidate"] != params.job
            or type(matches[0].get("raw_appearance_selector")) is not int
            or matches[0]["raw_appearance_selector"] != int(params.female)
        ):
            raise ClientError("gui_character_state_unknown", "外观原始值、职业或性别不可确认。")
        return focused, matches[0], raw

    focused, window, before = observe()
    plan = plan_observed_appearance_step(params, before, seen)
    if plan["status"] != "step":
        return plan
    control_id, field = plan["control_id"], plan["field"]
    stage_buttons, dialog_buttons = window.get("buttons"), focused.get("buttons")
    stage_matches = (
        [b for b in stage_buttons if isinstance(b, dict) and b.get("control_id") == control_id]
        if isinstance(stage_buttons, list)
        else []
    )
    dialog_matches = (
        [b for b in dialog_buttons if isinstance(b, dict) and b.get("control_id") == control_id]
        if isinstance(dialog_buttons, list)
        else []
    )
    rect = dialog_matches[0].get("root_rect") if len(dialog_matches) == 1 else None
    window_rect = focused.get("root_rect")
    if (
        len(stage_matches) != 1
        or stage_matches[0].get("enabled") is not True
        or not isinstance(rect, dict)
        or not isinstance(window_rect, dict)
        or any(
            type(rect.get(k)) is not int or type(window_rect.get(k)) is not int
            for k in ("left", "top", "right", "bottom")
        )
        or rect["right"] - rect["left"] != 15
        or rect["bottom"] - rect["top"] != 16
        or window_rect["right"] - window_rect["left"] != 225
        or window_rect["bottom"] - window_rect["top"] != 377
        or stage_matches[0].get("width") != 15
        or stage_matches[0].get("height") != 16
        or stage_matches[0].get("layout_x") != 196
        or stage_matches[0].get("layout_y") != 106 + field * 18
        or dialog_matches[0].get("layout_x") != stage_matches[0]["layout_x"]
        or dialog_matches[0].get("layout_y") != stage_matches[0]["layout_y"]
        or rect["left"] != window_rect["left"] + stage_matches[0]["layout_x"]
        or rect["top"] != window_rect["top"] + stage_matches[0]["layout_y"]
        or not (
            window_rect["left"] <= rect["left"] < rect["right"] <= window_rect["right"]
            and window_rect["top"] <= rect["top"] < rect["bottom"] <= window_rect["bottom"]
        )
    ):
        raise ClientError("gui_character_state_unknown", "外观按钮或坐标不可确认。")
    require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    seen[field].add(before[field])
    result = backend.desktop(
        [{"action": "click", "x": (rect["left"] + rect["right"]) // 2, "y": (rect["top"] + rect["bottom"]) // 2}]
    )
    if not _dispatched(result, "click"):
        raise ClientError("gui_character_action_unknown", "外观输入结果不明，停止输入。")
    after_focused, _, after = observe()
    if after_focused.get("address") != focused.get("address") or not validate_appearance_transition(
        before, after, field
    ):
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
    """内部遍历原语；调用方持有公共 input_lock 且先实证性别。超时不回退或重放。"""
    require_supported_creation(params)
    _require_verified_gui_candidates()
    if not math.isfinite(timeout) or timeout <= 0:
        raise ClientError("usage", "外观等待时间须为正有限数。")
    try:
        descriptor = os.open(
            directory / "gui-character-appearance-attempt", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(request_id)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ClientError("gui_character_already_attempted", "外观调整已尝试，禁止重放。") from error
    except OSError as error:
        raise ClientError("login_bridge_write_failed", "外观尝试标记未确认，禁止输入。") from error
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


def identify_creation_page(stage: JsonObject, dialog: JsonObject, *, instance_id: str, run_id: str) -> str:
    """识别已采样的焦点窗口；识别页面不代表动作或参数已验证。"""
    for sample in (stage, dialog):
        client = sample.get("client")
        if (
            sample.get("instance_id") != instance_id
            or not isinstance(client, dict)
            or client.get("run_id") != run_id
            or sample.get("unavailable") != []
        ):
            return "unknown"
    login = stage.get("login")
    focused = dialog.get("focused_window")
    if (
        not isinstance(login, dict)
        or login.get("request_pending") is not False
        or login.get("transition_pending") is not False
        or not isinstance(focused, dict)
    ):
        return "unknown"
    vtables = focused.get("vtables")
    if (
        not isinstance(vtables, list)
        or not all(isinstance(value, str) for value in vtables)
        or type(login.get("raw_step")) is not int
        or type(focused.get("width")) is not int
        or type(focused.get("height")) is not int
    ):
        return "unknown"
    signature = (login["raw_step"], tuple(vtables), focused["width"], focused["height"])
    pages = {
        (3, ("0xaf7360", "0xaf7314", "0xaf7310"), 700, 460): "category",
        (4, ("0xaf7564", "0xaf7518", "0xaf7514"), 201, 224): "name",
        (4, ("0xaf777c", "0xaf7730", "0xaf772c"), 225, 377): "appearance",
    }
    return pages.get(signature, "unknown")


def creation_page_button(
    stage: JsonObject, dialog: JsonObject, *, instance_id: str, run_id: str, page: str
) -> JsonObject | None:
    """仅返回两种已观察稳定页面的确认按钮坐标，不代表参数已核实。"""
    expected = {
        "category": (1003, 530, 422, 73, 29, 240, 40, 700, 460),
        "name": (1000, 27, 178, 81, 41, 721, 155, 201, 224),
    }
    if page not in expected or identify_creation_page(stage, dialog, instance_id=instance_id, run_id=run_id) != page:
        return None
    if any(
        dialog.get(key) is not False
        for key in ("script_dialog_open", "focused_talk_dialog_open", "registered_talk_dialog_open")
    ):
        return None
    focused, geometry, windows = dialog.get("focused_window"), dialog.get("game_geometry"), stage.get("windows")
    if not isinstance(focused, dict) or not isinstance(geometry, dict) or not isinstance(windows, list):
        return None
    control_id, x, y, width, height, gx, gy, window_width, window_height = expected[page]
    if (
        geometry.get("width") != 1280
        or geometry.get("height") != 720
        or type(geometry.get("x")) is not int
        or type(geometry.get("y")) is not int
        or focused.get("game_rect") != {"left": gx, "top": gy, "right": gx + window_width, "bottom": gy + window_height}
        or focused.get("root_rect")
        != {
            "left": geometry["x"] + gx,
            "top": geometry["y"] + gy,
            "right": geometry["x"] + gx + window_width,
            "bottom": geometry["y"] + gy + window_height,
        }
    ):
        return None
    address = focused.get("address")
    if not isinstance(address, str) or not re.fullmatch(r"0x[0-9a-fA-F]+", address) or int(address, 16) == 0:
        return None
    matches = [window for window in windows if isinstance(window, dict) and window.get("address") == address]
    if len(matches) != 1 or matches[0].get("vtables") != focused.get("vtables"):
        return None
    native_buttons, projected_buttons = matches[0].get("buttons"), focused.get("buttons")
    native = (
        [button for button in native_buttons if isinstance(button, dict) and button.get("control_id") == control_id]
        if isinstance(native_buttons, list)
        else []
    )
    projected = (
        [button for button in projected_buttons if isinstance(button, dict) and button.get("control_id") == control_id]
        if isinstance(projected_buttons, list)
        else []
    )
    if len(native) != 1 or len(projected) != 1:
        return None
    if (
        native[0].get("enabled") is not True
        or any(
            button.get("layout_x") != x
            or button.get("layout_y") != y
            or button.get("width") != width
            or button.get("height") != height
            for button in (native[0], projected[0])
        )
        or projected[0].get("root_rect")
        != {
            "left": geometry["x"] + gx + x,
            "top": geometry["y"] + gy + y,
            "right": geometry["x"] + gx + x + width,
            "bottom": geometry["y"] + gy + y + height,
        }
    ):
        return None
    return {"action": "click", "x": geometry["x"] + gx + x + width // 2, "y": geometry["y"] + gy + y + height // 2}


def name_candidate_decision(
    stage: JsonObject, dialog: JsonObject, *, instance_id: str, run_id: str, name: str
) -> JsonObject:
    """姓名页纯决策；候选未经实机验证，调用方不得据此启用真实输入。"""
    if (
        not isinstance(name, str)
        or not name
        or any(not 32 <= ord(ch) <= 126 for ch in name)
        or creation_page_button(stage, dialog, instance_id=instance_id, run_id=run_id, page="name") is None
    ):
        return {"status": "unknown"}
    focused = dialog["focused_window"]
    matches = [w for w in stage["windows"] if isinstance(w, dict) and w.get("address") == focused["address"]]
    if len(matches) != 1 or matches[0].get("creation_name_focused") is not True:
        return {"status": "unknown"}
    candidate = matches[0].get("creation_name_candidate")
    if not isinstance(candidate, str) or any(not 32 <= ord(ch) <= 126 for ch in candidate):
        return {"status": "unknown"}
    return {"status": "empty" if not candidate else "matched" if candidate == name else "different"}


def _enter_name(
    backend: Backend,
    params: CharacterCreation,
    *,
    directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    deadline: float,
) -> JsonObject:
    """未接线姓名控制器；候选未实测期间由支持门禁止输入。"""
    require_supported_creation(params)
    _require_verified_gui_candidates()

    def observe():
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
        if backend.name != "beidou" or not runtime.running or runtime.run_id != run_id:
            raise ClientError("gui_character_state_unknown", "建角实例状态不明确。")
        stage, dialog = backend.read("stage"), backend.read("dialog")
        decision = name_candidate_decision(stage, dialog, instance_id=instance_id, run_id=run_id, name=params.name)
        return decision["status"], dialog

    try:
        with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
            record = json.load(stream)
    except (OSError, ValueError) as error:
        raise ClientError("gui_character_state_unknown", "建角请求不可读取。") from error
    for marker in ("gui-character-final-submit", "gui-character-name-check", "gui-character-appearance-attempt"):
        try:
            (directory / marker).stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ClientError("gui_character_state_unknown", "请求进度不可读取。") from error
        raise ClientError("gui_character_already_attempted", "请求已进入后续阶段，禁止输入姓名。")
    if (
        not isinstance(record, dict)
        or record.get("instance_id") != instance_id
        or record.get("run_id") != run_id
        or record.get("request_id") != request_id
        or record.get("params") != asdict(params)
    ):
        raise ClientError("gui_character_identity_unconfirmed", "建角请求身份或参数不匹配。")
    status, dialog = observe()
    if status == "matched":
        return {"status": "matched"}
    if status != "empty":
        return {"status": "unknown"}
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    try:
        descriptor = os.open(directory / "gui-character-name-attempt", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(request_id)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ClientError("gui_character_already_attempted", "姓名输入已尝试，禁止重放。") from error
    except OSError as error:
        raise ClientError("login_bridge_write_failed", "姓名输入标记未确认，禁止输入。") from error
    current, next_dialog = observe()
    if (
        current != "empty"
        or next_dialog["focused_window"].get("address") != dialog["focused_window"].get("address")
        or time.monotonic() >= deadline
    ):
        return {"status": "unknown"}
    require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    backend.text("runtime-ui", "type-private", payload=params.name)
    status, next_dialog = observe()
    if not isinstance(next_dialog.get("focused_window"), dict) or next_dialog["focused_window"].get(
        "address"
    ) != dialog["focused_window"].get("address"):
        return {"status": "unknown"}
    return {"status": "matched" if status == "matched" else "unknown"}


def _check_name(
    backend: Backend,
    params: CharacterCreation,
    *,
    directory: Path,
    request_id: str,
    instance_id: str,
    run_id: str,
    deadline: float,
) -> JsonObject:
    """姓名核查最多一次；调用者持有公共输入锁，此动作不创建角色。"""
    require_supported_creation(params)
    _require_verified_gui_candidates()

    def observe():
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
        if backend.name != "beidou" or not runtime.running or runtime.run_id != run_id:
            raise ClientError("gui_character_state_unknown", "建角实例状态不明确。")
        stage, dialog = backend.read("stage"), backend.read("dialog")
        return stage, dialog

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
    for marker in ("gui-character-final-submit", "gui-character-appearance-attempt"):
        try:
            (directory / marker).stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ClientError("gui_character_state_unknown", "请求进度不可确认。") from error
        raise ClientError("gui_character_already_attempted", "请求已进入后续阶段，禁止重放姓名核查。")
    stage, dialog = observe()
    action = creation_page_button(stage, dialog, instance_id=instance_id, run_id=run_id, page="name")
    if (
        action is None
        or name_candidate_decision(stage, dialog, instance_id=instance_id, run_id=run_id, name=params.name)["status"]
        != "matched"
    ):
        return {"status": "unknown"}
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    try:
        descriptor = os.open(directory / "gui-character-name-check", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(request_id)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ClientError("gui_character_already_attempted", "姓名核查已尝试，禁止重放。") from error
    except OSError as error:
        raise ClientError("login_bridge_write_failed", "姓名核查标记未确认，禁止输入。") from error
    current, current_dialog = observe()
    if (
        creation_page_button(current, current_dialog, instance_id=instance_id, run_id=run_id, page="name") != action
        or current_dialog["focused_window"].get("address") != dialog["focused_window"].get("address")
        or name_candidate_decision(current, current_dialog, instance_id=instance_id, run_id=run_id, name=params.name)[
            "status"
        ]
        != "matched"
    ):
        return {"status": "unknown"}
    require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    if not _dispatched(backend.desktop([action]), "click"):
        raise ClientError("gui_character_action_unknown", "姓名核查结果不明，禁止重放。")
    while time.monotonic() < deadline:
        stage, dialog = observe()
        focused = dialog.get("focused_window")
        windows = stage.get("windows")
        address = focused.get("address") if isinstance(focused, dict) else None
        if (
            identify_creation_page(stage, dialog, instance_id=instance_id, run_id=run_id) == "appearance"
            and isinstance(address, str)
            and re.fullmatch(r"0x[0-9a-fA-F]+", address)
            and int(address, 16) != 0
            and isinstance(windows, list)
            and len(
                [
                    w
                    for w in windows
                    if isinstance(w, dict)
                    and w.get("address") == address
                    and w.get("vtables") == focused.get("vtables")
                ]
            )
            == 1
        ):
            break
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    else:
        return {"status": "unknown", "reason": "next_page_unconfirmed"}
    try:
        descriptor = os.open(directory / "gui-character-name-checked", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(request_id)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as error:
        raise ClientError("login_bridge_write_failed", "姓名核查结果未持久化，停止建角。") from error
    return {"status": "appearance_page"}


def _final_confirmation_action(
    stage: JsonObject, dialog: JsonObject, params: CharacterCreation, *, instance_id: str, run_id: str
) -> JsonObject | None:
    """未实测候选的纯比较；实际动作仍受验证门阻断。"""
    if identify_creation_page(stage, dialog, instance_id=instance_id, run_id=run_id) != "appearance" or any(
        dialog.get(key) is not False
        for key in ("script_dialog_open", "focused_talk_dialog_open", "registered_talk_dialog_open")
    ):
        return None
    focused, geometry, windows = dialog.get("focused_window"), dialog.get("game_geometry"), stage.get("windows")
    if not isinstance(focused, dict) or not isinstance(geometry, dict) or not isinstance(windows, list):
        return None
    address = focused.get("address")
    if (
        not isinstance(address, str)
        or not re.fullmatch(r"0x[0-9a-fA-F]+", address)
        or int(address, 16) == 0
        or geometry.get("width") != 1280
        or geometry.get("height") != 720
        or type(geometry.get("x")) is not int
        or type(geometry.get("y")) is not int
        or focused.get("game_rect") != {"left": 721, "top": 155, "right": 946, "bottom": 532}
        or focused.get("root_rect")
        != {
            "left": geometry["x"] + 721,
            "top": geometry["y"] + 155,
            "right": geometry["x"] + 946,
            "bottom": geometry["y"] + 532,
        }
    ):
        return None
    matches = [
        w
        for w in windows
        if isinstance(w, dict) and w.get("address") == address and w.get("vtables") == focused.get("vtables")
    ]
    if len(matches) != 1:
        return None
    window = matches[0]
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
        or type(window.get("raw_job_candidate")) is not int
        or window["raw_job_candidate"] != params.job
        or type(window.get("raw_appearance_selector")) is not int
        or window["raw_appearance_selector"] != int(params.female)
    ):
        return None
    native, projected = window.get("buttons"), focused.get("buttons")
    first = (
        [b for b in native if isinstance(b, dict) and b.get("control_id") == 1000] if isinstance(native, list) else []
    )
    second = (
        [b for b in projected if isinstance(b, dict) and b.get("control_id") == 1000]
        if isinstance(projected, list)
        else []
    )
    if (
        len(first) != 1
        or len(second) != 1
        or first[0].get("enabled") is not True
        or any(
            b.get("layout_x") != 37 or b.get("layout_y") != 330 or b.get("width") != 81 or b.get("height") != 41
            for b in (first[0], second[0])
        )
        or second[0].get("root_rect")
        != {
            "left": geometry["x"] + 758,
            "top": geometry["y"] + 485,
            "right": geometry["x"] + 839,
            "bottom": geometry["y"] + 526,
        }
    ):
        return None
    return {"action": "click", "x": geometry["x"] + 798, "y": geometry["y"] + 505}


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
    """单次最终确认；调用者持公共输入锁，未知结果不可重放。"""
    require_supported_creation(params)
    _require_verified_gui_candidates()
    unknown: JsonObject = {"request_id": request_id, "instance_id": instance_id, "run_id": run_id, "status": "unknown"}
    try:
        with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
            record = json.load(stream)
        name_checked = (directory / "gui-character-name-checked").read_text(encoding="utf-8")
    except (OSError, ValueError) as error:
        raise ClientError("gui_character_state_unknown", "请求或姓名检查结果不可确认。") from error
    if (
        not isinstance(record, dict)
        or record.get("instance_id") != instance_id
        or record.get("run_id") != run_id
        or record.get("request_id") != request_id
        or record.get("params") != asdict(params)
        or name_checked != request_id
    ):
        raise ClientError("gui_character_identity_unconfirmed", "请求或姓名检查身份不匹配。")

    def observe():
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
        if backend.name != "beidou" or not runtime.running or runtime.run_id != run_id:
            raise ClientError("gui_character_state_unknown", "建角实例状态不明确。")
        stage, dialog = backend.read("stage"), backend.read("dialog")
        return _final_confirmation_action(stage, dialog, params, instance_id=instance_id, run_id=run_id), dialog

    action, dialog = observe()
    if action is None or time.monotonic() >= deadline:
        return unknown
    mark_final_submit(directory, instance_id=instance_id, run_id=run_id, request_id=request_id)
    current, current_dialog = observe()
    if (
        current != action
        or not isinstance(current_dialog.get("focused_window"), dict)
        or current_dialog["focused_window"].get("address") != dialog["focused_window"].get("address")
    ):
        return unknown
    require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
    if time.monotonic() >= deadline:
        return unknown
    receipt = backend.desktop([action])
    record_final_dispatch(directory, instance_id=instance_id, run_id=run_id, request_id=request_id, receipt=receipt)
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
    """单次确认默认类别；调用方持公共输入锁，翻页不证明请求的职业已核实。"""

    def observe():
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
        if backend.name != "beidou" or not runtime.running or runtime.run_id != run_id:
            raise ClientError("gui_character_state_unknown", "建角实例状态不明确。")
        stage, dialog = backend.read("stage"), backend.read("dialog")
        return stage, dialog

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
    for marker in ("gui-character-final-submit", "gui-character-appearance-attempt"):
        try:
            (directory / marker).stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ClientError("gui_character_state_unknown", "无法核对请求进度。") from error
        raise ClientError("gui_character_already_attempted", "请求已进入后续阶段，禁止重放类别确认。")
    stage, dialog = observe()
    action = creation_page_button(stage, dialog, instance_id=instance_id, run_id=run_id, page="category")
    if action is None:
        raise ClientError("gui_character_state_unknown", "类别页面不明确，停止输入。")
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    try:
        descriptor = os.open(directory / "gui-character-category-attempt", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(request_id)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ClientError("gui_character_already_attempted", "类别确认已尝试，禁止重放。") from error
    except OSError as error:
        raise ClientError("login_bridge_write_failed", "类别确认标记未确认，禁止输入。") from error
    after_stage, after_dialog = observe()
    if creation_page_button(
        after_stage, after_dialog, instance_id=instance_id, run_id=run_id, page="category"
    ) != action or after_dialog["focused_window"].get("address") != dialog["focused_window"].get("address"):
        raise ClientError("gui_character_state_unknown", "类别页面已变化，停止输入。")
    require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    receipt = backend.desktop([action])
    if not _dispatched(receipt, "click"):
        raise ClientError("gui_character_action_unknown", "类别确认结果不明，禁止重放。")
    while time.monotonic() < deadline:
        stage, dialog = observe()
        if creation_page_button(stage, dialog, instance_id=instance_id, run_id=run_id, page="name") is not None:
            return {"status": "name_page"}
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    return {"status": "unknown", "reason": "next_page_unconfirmed"}


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
    """空列表单次点击创建；后续仅观察类别页，调用者持公共输入锁。"""

    def observe():
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
        stage, dialog = backend.read("stage"), backend.read("dialog")
        client, login, windows = stage.get("client"), stage.get("login"), stage.get("windows")
        focus, geometry = dialog.get("focused_window"), dialog.get("game_geometry")
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
            or login.get("raw_step") != 2
            or login.get("characters_available") is not True
            or login.get("characters") != []
            or login.get("request_pending") is not False
            or login.get("transition_pending") is not False
            or not isinstance(windows, list)
            or dialog.get("instance_id") != instance_id
            or not isinstance(dialog.get("client"), dict)
            or dialog["client"].get("run_id") != run_id
            or dialog.get("unavailable") != []
            or any(
                dialog.get(k) is not False
                for k in ("script_dialog_open", "focused_talk_dialog_open", "registered_talk_dialog_open")
            )
            or not isinstance(focus, dict)
            or focus.get("vtables") != ["0xaf6f04", "0xaf6eb8", "0xaf6eb4"]
            or focus.get("width") != 720
            or focus.get("height") != 80
            or not isinstance(geometry, dict)
            or geometry.get("width") != 1280
            or geometry.get("height") != 720
            or type(geometry.get("x")) is not int
            or type(geometry.get("y")) is not int
        ):
            raise ClientError("gui_character_state_unknown", "空角色列表或实例不明确。")
        focus_address = focus.get("address")
        if (
            not isinstance(focus_address, str)
            or not re.fullmatch(r"0x[0-9a-fA-F]+", focus_address)
            or int(focus_address, 16) == 0
            or len(
                [
                    w
                    for w in windows
                    if isinstance(w, dict)
                    and w.get("address") == focus_address
                    and w.get("vtables") == focus.get("vtables")
                ]
            )
            != 1
        ):
            raise ClientError("gui_character_state_unknown", "角色列表焦点不明确。")
        matches = [
            w for w in windows if isinstance(w, dict) and w.get("vtables") == ["0xaf6d90", "0xaf6d44", "0xaf6d40"]
        ]
        if len(matches) != 1:
            raise ClientError("gui_character_state_unknown", "角色创建窗口不唯一。")
        window = matches[0]
        address = window.get("address")
        buttons = window.get("buttons")
        create = (
            [b for b in buttons if isinstance(b, dict) and b.get("control_id") == 1001]
            if isinstance(buttons, list)
            else []
        )
        if (
            not isinstance(address, str)
            or not re.fullmatch(r"0x[0-9a-fA-F]+", address)
            or int(address, 16) == 0
            or window.get("width") != 101
            or window.get("height") != 131
            or window.get("game_rect") != {"left": 812, "top": 209, "right": 913, "bottom": 340}
            or window.get("root_rect")
            != {
                "left": geometry["x"] + 812,
                "top": geometry["y"] + 209,
                "right": geometry["x"] + 913,
                "bottom": geometry["y"] + 340,
            }
            or len(create) != 1
            or create[0].get("enabled") is not True
            or create[0].get("layout_x") != 4
            or create[0].get("layout_y") != 36
            or create[0].get("width") != 101
            or create[0].get("height") != 35
        ):
            raise ClientError("gui_character_state_unknown", "角色创建按钮位置不明确。")
        return (
            {"action": "click", "x": geometry["x"] + 812 + 4 + 50, "y": geometry["y"] + 209 + 36 + 17},
            address,
            focus_address,
        )

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
        or record.get("previous_ids") != []
    ):
        raise ClientError("gui_character_identity_unconfirmed", "空角色请求身份不匹配。")
    action, address, focus_address = observe()
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    try:
        descriptor = os.open(directory / "gui-character-open-attempt", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(request_id)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ClientError("gui_character_already_attempted", "角色创建页面已尝试打开，禁止重放。") from error
    except OSError as error:
        raise ClientError("login_bridge_write_failed", "页面操作标记未确认。") from error
    if observe() != (action, address, focus_address):
        return {"status": "unknown"}
    require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    if not _dispatched(backend.desktop([action]), "click"):
        raise ClientError("gui_character_action_unknown", "打开创建页面结果不明，禁止重放。")
    while time.monotonic() < deadline:
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        native = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
        if (
            not runtime.running
            or runtime.run_id != run_id
            or native.get("instance_id") != instance_id
            or native.get("run_id") != run_id
        ):
            return {"status": "unknown"}
        stage, dialog = backend.read("stage"), backend.read("dialog")
        if creation_page_button(stage, dialog, instance_id=instance_id, run_id=run_id, page="category") is not None:
            return {"status": "category_page"}
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
    """先核实并最多切换一次外观性别；调用者持公共输入锁。"""
    _require_verified_gui_candidates()

    def observe():
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
        stage, dialog = backend.read("stage"), backend.read("dialog")
        if (
            backend.name != "beidou"
            or not runtime.running
            or runtime.run_id != run_id
            or identify_creation_page(stage, dialog, instance_id=instance_id, run_id=run_id) != "appearance"
            or any(
                dialog.get(k) is not False
                for k in ("script_dialog_open", "focused_talk_dialog_open", "registered_talk_dialog_open")
            )
        ):
            raise ClientError("gui_character_state_unknown", "性别页面或实例状态不明。")
        focused, windows = dialog["focused_window"], stage.get("windows")
        address = focused.get("address")
        matches = (
            [
                w
                for w in windows
                if isinstance(w, dict) and w.get("address") == address and w.get("vtables") == focused.get("vtables")
            ]
            if isinstance(windows, list)
            else []
        )
        if (
            not isinstance(address, str)
            or not re.fullmatch(r"0x[0-9a-fA-F]+", address)
            or int(address, 16) == 0
            or len(matches) != 1
        ):
            raise ClientError("gui_character_state_unknown", "性别窗口身份不明确。")
        window = matches[0]
        if (
            type(window.get("raw_job_candidate")) is not int
            or window["raw_job_candidate"] != params.job
            or type(window.get("raw_appearance_selector")) is not int
            or window["raw_appearance_selector"] not in (0, 1)
            or not isinstance(window.get("raw_appearance_candidates"), list)
            or len(window["raw_appearance_candidates"]) != 8
            or any(type(v) is not int for v in window["raw_appearance_candidates"])
        ):
            raise ClientError("gui_character_state_unknown", "职业、性别或外观原始值不明确。")
        return focused, window

    try:
        with (directory / "gui-character-attempt.json").open(encoding="utf-8") as stream:
            record = json.load(stream)
        if (directory / "gui-character-name-checked").read_text(encoding="utf-8") != request_id:
            raise ClientError("gui_character_state_unknown", "姓名核查未确认。")
    except (OSError, ValueError) as error:
        raise ClientError("gui_character_state_unknown", "请求状态不可读取。") from error
    if (
        not isinstance(record, dict)
        or record.get("instance_id") != instance_id
        or record.get("run_id") != run_id
        or record.get("request_id") != request_id
        or record.get("params") != asdict(params)
    ):
        raise ClientError("gui_character_identity_unconfirmed", "建角请求身份或参数不匹配。")
    for marker in ("gui-character-gender-attempt", "gui-character-appearance-attempt", "gui-character-final-submit"):
        try:
            (directory / marker).stat()
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ClientError("gui_character_state_unknown", "请求进度不可读取。") from error
        raise ClientError("gui_character_already_attempted", "性别或后续步骤已尝试，禁止重放。")
    focused, window = observe()
    if window["raw_appearance_selector"] == int(params.female):
        return {"status": "matched"}
    native, projected, rect = window.get("buttons"), focused.get("buttons"), focused.get("root_rect")
    buttons = (
        [b for b in native if isinstance(b, dict) and b.get("control_id") == 1019] if isinstance(native, list) else []
    )
    drawn = (
        [b for b in projected if isinstance(b, dict) and b.get("control_id") == 1019]
        if isinstance(projected, list)
        else []
    )
    if (
        len(buttons) != 1
        or len(drawn) != 1
        or buttons[0].get("enabled") is not True
        or any(
            b.get("layout_x") != 196 or b.get("layout_y") != 250 or b.get("width") != 15 or b.get("height") != 16
            for b in (buttons[0], drawn[0])
        )
        or not isinstance(rect, dict)
        or any(type(rect.get(k)) is not int for k in ("left", "top", "right", "bottom"))
        or rect["right"] - rect["left"] != 225
        or rect["bottom"] - rect["top"] != 377
        or drawn[0].get("root_rect")
        != {
            "left": rect["left"] + 196,
            "top": rect["top"] + 250,
            "right": rect["left"] + 211,
            "bottom": rect["top"] + 266,
        }
    ):
        raise ClientError("gui_character_state_unknown", "性别按钮或坐标不明确。")
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    try:
        descriptor = os.open(directory / "gui-character-gender-attempt", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(request_id)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise ClientError("gui_character_already_attempted", "性别切换已尝试，禁止重放。") from error
    except OSError as error:
        raise ClientError("login_bridge_write_failed", "性别切换标记未确认。") from error
    current, observed = observe()
    if (
        current.get("address") != focused.get("address")
        or current.get("root_rect") != rect
        or current.get("buttons") != focused.get("buttons")
        or observed.get("buttons") != window.get("buttons")
        or observed.get("raw_appearance_selector") != window["raw_appearance_selector"]
        or observed.get("raw_appearance_candidates") != window["raw_appearance_candidates"]
    ):
        return {"status": "unknown"}
    require_input_idle(BridgeClient(backend.root, backend.name, backend.instance), instance_id, run_id)
    if time.monotonic() >= deadline:
        return {"status": "unknown", "reason": "timeout"}
    receipt = backend.desktop([{"action": "click", "x": rect["left"] + 203, "y": rect["top"] + 258}])
    if not _dispatched(receipt, "click"):
        raise ClientError("gui_character_action_unknown", "性别切换派发不明，禁止重放。")
    after, observed = observe()
    if after.get("address") != focused.get("address") or observed["raw_appearance_selector"] != int(params.female):
        return {"status": "unknown"}
    return {"status": "matched"}


def _create_once_locked(
    backend: Backend, params: CharacterCreation, *, directory: Path, instance_id: str, run_id: str, timeout: float
) -> JsonObject:
    """公共 input_lock 和 per-run character.lock 已由调用方持有。"""
    require_supported_creation(params)
    _require_verified_gui_candidates()
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
            (_enter_name, "matched"),
            (_check_name, "appearance_page"),
            (_set_gender, "matched"),
        ):
            result = operation(backend, params, **arguments)
            if result.get("status") != expected:
                return {**identity, "status": "unknown"}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {**identity, "status": "unknown"}
        result = _apply_appearance(backend, params, directory=directory, **identity, timeout=remaining)
        if result.get("status") != "matched":
            return {**identity, "status": "unknown"}
        _submit_creation(backend, params, **arguments)
        if (directory / "gui-character-final-dispatched").read_text(encoding="utf-8") != identity["request_id"]:
            return {**identity, "status": "unknown"}
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
