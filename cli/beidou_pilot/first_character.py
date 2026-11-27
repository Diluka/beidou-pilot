"""观察已启动的登录会话，显式提交一次建角请求。"""

import argparse
import json
import math
import re
import time
from typing import cast

from .backend import Backend
from .bridge import BridgeClient
from .errors import ClientError, JsonObject
from .login_bridge import LoginBridge
from .profile import CharacterCreation
from .runtime import load_runtime


def execute(backend: Backend, args: argparse.Namespace) -> JsonObject:
    accept_terms = getattr(args, "accept_terms", False)
    gender = getattr(args, "gender", None)
    timeout = getattr(args, "timeout", None)
    if timeout is None:
        if args.command == "character" and args.character_action == "create":
            timeout = 90
        else:
            timeout = (
                30 if args.command == "login" and (accept_terms or gender is not None) else 0
            )
    if args.command == "character":
        from .gui_character import create_once, observe_result, query_result

        native = BridgeClient(backend.root, backend.name, backend.instance)
        if args.character_action == "result":
            identity = {"instance_id": args.instance_id, "run_id": args.run_id, "request_id": args.request_id}
            result = query_result(native.directory, **identity)
            if result["status"] in ("completed", "rejected"):
                return result
            try:
                runtime = load_runtime(backend.root, backend.name, backend.instance)
                snapshot = native.snapshot()
            except ClientError:
                return {**identity, "status": "unknown", "last_observed_status": result["status"]}
            if (
                not runtime.running
                or runtime.run_id != args.run_id
                or snapshot.get("instance_id") != args.instance_id
                or snapshot.get("run_id") != args.run_id
            ):
                return {**identity, "status": "unknown", "last_observed_status": result["status"]}
            return observe_result(
                backend, directory=runtime.run_dir, bridge_directory=native.directory, timeout=1, **identity
            )
        if not math.isfinite(timeout) or timeout <= 0:
            raise ClientError("usage", "建角等待时间须为正有限数。")
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        if not runtime.running:
            try:
                with (runtime.run_dir / "gui-character-attempt.json").open(encoding="utf-8") as stream:
                    attempt = json.load(stream)
            except (OSError, ValueError):
                attempt = None
            if (
                isinstance(attempt, dict)
                and type(attempt.get("protocol")) is int
                and attempt["protocol"] == 1
                and attempt.get("operation") == "create_character"
                and attempt.get("run_id") == runtime.run_id
                and isinstance(attempt.get("instance_id"), str)
                and re.fullmatch(r"[A-Za-z0-9_-]+", attempt["instance_id"])
                and isinstance(attempt.get("request_id"), str)
                and re.fullmatch(r"[0-9a-f]{32}", attempt["request_id"])
            ):
                raise ClientError(
                    "gui_character_already_attempted",
                    "原客户端已退出；已有建角尝试，禁止重发。",
                    {key: attempt[key] for key in ("request_id", "instance_id", "run_id")},
                )
            raise ClientError(
                "bridge_session_unavailable", "本容器的客户端进程已退出，无法确认建角请求；禁止重发。"
            )
        snapshot = native.snapshot()
        if snapshot.get("run_id") != runtime.run_id or not snapshot.get("instance_id"):
            raise ClientError("gui_character_identity_unconfirmed", "原生桥身份不匹配。")
        params = CharacterCreation(
            name=args.name,
            job=args.job,
            face=args.face,
            hair=args.hair,
            hair_color=args.hair_color,
            skin=args.skin,
            top=args.top,
            bottom=args.bottom,
            shoes=args.shoes,
            weapon=args.weapon,
            female=gender == "female",
        )
        return create_once(
            backend,
            params,
            directory=runtime.run_dir,
            instance_id=snapshot["instance_id"],
            run_id=runtime.run_id,
            timeout=timeout,
        )
    if not math.isfinite(timeout) or timeout < 0:
        raise ClientError("usage", "等待时间必须为非负有限数。")
    action = accept_terms or gender is not None
    if action and gender is None:
        raise ClientError("usage", "GUI 登录动作必须明确指定性别。")
    if action and not 0 < timeout <= 180:
        raise ClientError("invalid_login_options", "GUI 登录动作等待时间须大于零且不超过 180 秒。")
    deadline = time.monotonic() + timeout
    runtime = load_runtime(backend.root, backend.name, backend.instance)
    if not runtime.running:
        raise ClientError("bridge_session_unavailable", "本容器的客户端进程已退出。")
    bridge = BridgeClient(backend.root, backend.name, backend.instance)
    while True:
        current = load_runtime(backend.root, backend.name, backend.instance)
        if not current.running or current.run_id != runtime.run_id:
            raise ClientError("gui_login_identity_unconfirmed", "运行实例已改变。")
        try:
            native = bridge.snapshot()
        except ClientError as error:
            if error.code != "bridge_unavailable":
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if timeout == 0:
                    raise
                raise ClientError("login_timeout", "等待原生桥就绪超时；未发送输入。") from error
            time.sleep(min(0.1, remaining))
            continue
        if native.get("run_id") != runtime.run_id or not native.get("instance_id"):
            raise ClientError("gui_login_identity_unconfirmed", "原生桥身份不匹配。")
        break
    if action:
        from .gui_login import execute as gui_execute
        from .profile import load_account_profile

        profile = load_account_profile(backend.root / "account.json")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ClientError("login_timeout", "等待登录准备超时；未发送输入。")
        return gui_execute(
            backend,
            profile,
            instance_id=native["instance_id"],
            run_id=runtime.run_id,
            accept_terms=accept_terms,
            gender=gender,
            timeout=remaining,
            deadline=deadline,
        )
    while True:
        stage = backend.read("stage")
        client = stage.get("client")
        current = load_runtime(backend.root, backend.name, backend.instance)
        if (
            not current.running
            or current.run_id != runtime.run_id
            or stage.get("instance_id") != native["instance_id"]
            or not isinstance(client, dict)
            or client.get("run_id") != runtime.run_id
        ):
            raise ClientError("gui_login_identity_unconfirmed", "登录观察身份不匹配。")
        login = stage.get("login")
        if (
            timeout == 0
            or stage.get("stage") == "CHARACTER_SELECT"
            and isinstance(login, dict)
            and login.get("characters_available") is True
        ):
            return stage
        if time.monotonic() >= deadline:
            raise ClientError(
                "login_timeout", "等待角色列表超时；登录进程继续运行。", {"stage": stage.get("stage")}
            )
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
