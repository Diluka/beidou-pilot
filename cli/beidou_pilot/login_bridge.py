"""登录与建角文件协议；调用方负责核实运行中的实例身份。"""

from dataclasses import asdict
import fcntl
import json
import math
from pathlib import Path
import re
import time
from typing import cast
import uuid

from .errors import ClientError, JsonObject
from .profile import CharacterCreation, validate_character_creation


class LoginBridge:
    def __init__(self, directory: Path, instance_id: str, run_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", instance_id) or not run_id:
            raise ClientError("login_bridge_invalid_identity", "登录桥实例身份无效。")
        self.directory = directory
        self.instance_id = instance_id
        self.run_id = run_id

    def _identity_matches(self, value: JsonObject) -> bool:
        return (type(value.get("protocol")) is int and value["protocol"] == 1
                and value.get("instance_id") == self.instance_id and value.get("run_id") == self.run_id)

    def snapshot(self, max_age: float = 1.0) -> JsonObject:
        if not math.isfinite(max_age) or max_age <= 0:
            raise ClientError("login_bridge_invalid_options", "登录状态有效期须大于零。")
        try:
            value = json.loads((self.directory / "login-state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ClientError("login_bridge_unavailable", "无法读取登录状态。") from error
        if (not isinstance(value, dict) or not self._identity_matches(value)
                or type(value.get("seq")) is not int or value["seq"] < 0
                or type(value.get("observed_at_ms")) is not int
                or not isinstance(value.get("phase"), str) or not value["phase"]
                or "characters" not in value
                or value["characters"] is not None and not isinstance(value["characters"], list)
                or "pending_request_id" not in value
                or value["pending_request_id"] is not None and (not isinstance(value["pending_request_id"], str)
                    or not re.fullmatch(r"[0-9a-f]{32}", value["pending_request_id"]))):
            raise ClientError("login_bridge_invalid_state", "登录状态或实例身份无效。")
        age = time.time() - value["observed_at_ms"] / 1000
        if not 0 <= age <= max_age:
            raise ClientError("login_bridge_stale_state", "登录状态已过期。")
        return cast(JsonObject, value)

    def submit(self, params: CharacterCreation) -> str:
        """显式提交一次；发布失败或结果未知均不自动重发。"""
        validate_character_creation(params)
        request_id = uuid.uuid4().hex
        try:
            with (self.directory / "login.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ClientError("login_bridge_busy", "另一个登录请求正在提交。") from error
                state = self.snapshot()
                if state["phase"] != "character_list" or state["characters"] is None:
                    raise ClientError("login_bridge_not_ready", "角色列表尚未就绪，未提交建角请求。")
                if (self.directory / "login-command.json").exists() or state["pending_request_id"] is not None:
                    raise ClientError("login_bridge_busy", "已有建角请求等待原生端处理。")
                command = {"protocol": 1, "instance_id": self.instance_id, "run_id": self.run_id,
                           "request_id": request_id, "operation": "create_character", "params": asdict(params)}
                temporary = self.directory / ("login-command-" + request_id + ".tmp")
                with temporary.open("x", encoding="utf-8") as stream:
                    json.dump(command, stream, ensure_ascii=False)
                temporary.replace(self.directory / "login-command.json")
        except OSError as error:
            raise ClientError("login_bridge_write_failed", "登录请求发布未确认，未自动重发。",
                              {"request_id": request_id}) from error
        return request_id

    def result(self, request_id: str) -> JsonObject:
        """按请求身份读取结果；文件缺失或无法读取时保持未知。"""
        if not re.fullmatch(r"[0-9a-f]{32}", request_id):
            raise ClientError("login_bridge_invalid_request", "请求身份无效。")
        unknown: JsonObject = {"request_id": request_id, "status": "unknown"}
        try:
            value = json.loads((self.directory / "login-results" / (request_id + ".json")).read_text(encoding="utf-8"))
        except OSError:
            return unknown
        except ValueError as error:
            raise ClientError("login_bridge_invalid_result", "登录结果不是有效 JSON。") from error
        if (not isinstance(value, dict) or not self._identity_matches(value)
                or value.get("request_id") != request_id or value.get("operation") != "create_character"
                or value.get("status") not in ("accepted", "completed", "rejected", "unknown")
                or (value.get("status") == "completed" and
                    (type(value.get("character_id")) is not int or not 0 < value["character_id"] < 2**31))
                or ("character_id" in value and value["character_id"] is not None
                    and (type(value["character_id"]) is not int or not 0 < value["character_id"] < 2**31))
                or ("error" in value and value["error"] is not None and not isinstance(value["error"], str))):
            raise ClientError("login_bridge_invalid_result", "登录结果或实例身份无效。")
        return cast(JsonObject, value)
