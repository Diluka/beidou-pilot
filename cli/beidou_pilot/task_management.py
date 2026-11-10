"""活动Lua会话的任务管理；不持有动作锁，不替代整会话取消。"""

import fcntl
import json
import math
from pathlib import Path
import re
import time
from typing import Literal, TypedDict, cast
import uuid

from .backend import Backend
from .bridge import BridgeClient
from .errors import ClientError, JsonObject


class TaskResponse(TypedDict):
    protocol: Literal[1]
    instance_id: str
    run_id: str
    script_id: str
    scene_generation: int
    seq: int
    observed_at_ms: int
    request_id: str
    operation: Literal["add", "replace", "stop"]
    name: str
    expected_revision: int
    revision: int
    status: Literal["pending", "completed", "rejected", "cancelled"]
    reason: str | None
    error: str | None
    changed: bool
    control_released: bool


def _read_result(directory: Path, request_id: str) -> TaskResponse | None:
    try:
        raw = json.loads((directory / "task-results" / (request_id + ".json")).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ClientError("invalid_task_result", "无法读取任务管理结果。", {"request_id": request_id}) from error
    if (not isinstance(raw, dict) or type(raw.get("protocol")) is not int or raw["protocol"] != 1
            or raw.get("request_id") != request_id
            or any(not isinstance(raw.get(field), str) for field in
                   ("instance_id", "run_id", "script_id", "name"))
            or any(type(raw.get(field)) is not int or raw[field] < 0 for field in
                   ("scene_generation", "seq", "observed_at_ms", "expected_revision", "revision"))
            or raw.get("operation") not in {"add", "replace", "stop"}
            or raw.get("status") not in {"pending", "completed", "rejected", "cancelled"}
            or any(field not in raw or raw[field] is not None and not isinstance(raw[field], str)
                   for field in ("reason", "error"))
            or any(type(raw.get(field)) is not bool for field in ("changed", "control_released"))):
        raise ClientError("invalid_task_result", "任务管理结果的协议或字段无效。", {"request_id": request_id})
    return cast(TaskResponse, raw)


def task_result(backend: Backend, request_id: str) -> JsonObject:
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ClientError("invalid_task_request", "管理request_id须为32位小写十六进制。")
    result = _read_result(backend.paths.bridge, request_id)
    if result is None:
        raise ClientError("task_result_unavailable", "本请求尚无管理结果；未自动重放。", {"request_id": request_id})
    return cast(JsonObject, result)


def change_task(backend: Backend, operation: Literal["add", "replace", "stop"], name: str, *,
                script_id: str, expected_revision: int | None = None, priority: int = 0,
                path: Path | None = None, code: str | None = None, timeout: float = 3) -> JsonObject:
    if (not re.fullmatch(r"[0-9a-f]{32}", script_id) or not math.isfinite(timeout) or timeout <= 0
            or not -0x80000000 <= priority <= 0x7fffffff
            or expected_revision is not None and not 1 <= expected_revision <= 0xffffffffffffffff):
        raise ClientError("invalid_task_options", "会话ID、任务revision、优先级或管理等待期限无效。")
    if (operation == "add" and expected_revision is not None
            or operation in {"replace", "stop"} and expected_revision is None
            or operation != "stop" and (path is None) == (code is None)
            or operation == "stop" and (path is not None or code is not None)):
        raise ClientError("invalid_task_options", "任务操作的源码与预期revision组合无效。")
    bridge = BridgeClient(backend.root, backend.name, backend.instance)
    before = bridge.snapshot()
    script = before.get("script")
    if script is None or script["id"] != script_id or script["status"] != "running":
        raise ClientError("task_session_mismatch", "目标Lua会话当前未运行，未发布管理请求。")
    if "tasks" not in script or any("revision" not in task for task in script["tasks"]):
        raise ClientError("task_management_unsupported", "当前原生桥未提供任务revision，未发布管理请求。")
    if operation != "stop" and not before["ready"]:
        raise ClientError("bridge_not_ready", "角色尚未就绪，未发布任务源码。")
    request_id = uuid.uuid4().hex
    directory = bridge.directory
    until = time.monotonic() + timeout
    try:
        handle = (directory / "task.lock").open("a")
    except OSError as error:
        raise ClientError("task_management_unavailable", "无法打开任务管理通道。") from error
    with handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.monotonic() >= until:
                    raise ClientError("task_management_busy", "另一个任务管理请求仍在等待结果。") from error
                time.sleep(.01)
        try:
            name_hex = name.encode("utf-8").hex()
            if operation != "stop":
                if path is not None:
                    source = path.read_bytes()
                    source.decode("utf-8")
                else:
                    source = cast(str, code).encode("utf-8")
                scripts = directory / "scripts"
                scripts.mkdir(mode=0o700, exist_ok=True)
                temporary = scripts / (request_id + ".tmp")
                with temporary.open("xb") as stream:
                    stream.write(source)
                temporary.replace(scripts / (request_id + ".lua"))
            line = " ".join(map(str, (1, before["instance_id"], before["run_id"], script_id,
                                      before["scene_generation"], request_id, operation, name_hex,
                                      expected_revision or 0, priority, request_id if operation != "stop" else "-"))) + "\n"
            temporary = directory / ("task-request-" + request_id + ".tmp")
            with temporary.open("x", encoding="ascii") as stream:
                stream.write(line)
            temporary.replace(directory / "task-request.txt")
        except (OSError, UnicodeError) as error:
            raise ClientError("task_request_write_failed", "无法准备UTF-8任务源码或发布管理请求；未自动重放。",
                              {"request_id": request_id, "reason": str(error)}) from error
        try:
            while True:
                try:
                    current = bridge.snapshot(max_age=timeout + 1)
                except ClientError as error:
                    raise ClientError("task_result_unconfirmed", "原生采样不可用，任务管理结果未确认。",
                                      {"request_id": request_id, "cause": error.code}) from error
                if current["instance_id"] != before["instance_id"] or current["run_id"] != before["run_id"]:
                    raise ClientError("task_result_unconfirmed", "原生实例已变化，任务管理结果未确认。", {"request_id": request_id})
                result = _read_result(directory, request_id)
                if result is not None:
                    if (result["instance_id"] != before["instance_id"] or result["run_id"] != before["run_id"]
                            or result["script_id"] != script_id or result["seq"] <= before["seq"]
                            or result["operation"] != operation or result["name"] != name
                            or result["expected_revision"] != (expected_revision or 0)):
                        raise ClientError("invalid_task_result", "任务管理结果不属于本次实例、会话或请求。", {"request_id": request_id})
                    if result["status"] == "completed":
                        return cast(JsonObject, result)
                    if result["status"] in {"rejected", "cancelled"}:
                        raise ClientError("task_request_" + result["status"], "任务管理请求未完成。", cast(JsonObject, result))
                if time.monotonic() >= until:
                    raise ClientError("task_result_unconfirmed", "等待任务管理结果超时；未停止会话或自动重放。", {"request_id": request_id})
                time.sleep(.01)
        except KeyboardInterrupt as error:
            raise ClientError("task_request_interrupted", "管理等待已中断，结果未确认；原会话继续运行。",
                              {"request_id": request_id}) from error
