"""观察已启动的登录会话，显式提交一次建角请求。"""

import argparse
import math
import time
from typing import cast

from .backend import Backend
from .bridge import BridgeClient
from .errors import ClientError, JsonObject
from .login_bridge import LoginBridge
from .profile import CharacterCreation
from .runtime import load_runtime


def execute(backend: Backend, args: argparse.Namespace) -> JsonObject:
    if backend.name != "headless":
        if args.command != "login":
            raise ClientError("unsupported_capability", "GUI 暂不支持建角。")
        if not math.isfinite(args.timeout) or args.timeout < 0:
            raise ClientError("usage", "等待时间必须为非负有限数。")
        runtime = load_runtime(backend.root, backend.name, backend.instance)
        if not runtime.running:
            raise ClientError("bridge_session_unavailable", "本容器的客户端进程已退出。")
        native = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
        if native.get("run_id") != runtime.run_id or not native.get("instance_id"):
            raise ClientError("gui_login_identity_unconfirmed", "原生桥身份不匹配。")
        if args.accept_terms or args.gender is not None:
            from .gui_login import execute as gui_execute
            from .profile import load_account_profile

            return gui_execute(
                backend,
                load_account_profile(backend.root / "account.json"),
                instance_id=native["instance_id"],
                run_id=runtime.run_id,
                accept_terms=args.accept_terms,
                gender=args.gender,
                timeout=args.timeout,
            )
        deadline = time.monotonic() + args.timeout
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
                args.timeout == 0
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
    timeout = getattr(args, "timeout", 0)
    if not math.isfinite(timeout) or timeout < 0:
        raise ClientError("usage", "等待时间必须为非负有限数。")
    runtime = load_runtime(backend.root, backend.name, backend.instance)
    native = BridgeClient(backend.root, backend.name, backend.instance)
    if args.command == "character" and args.character_action == "result":
        bridge = LoginBridge(native.directory, args.instance_id, args.run_id)
        result = bridge.result(args.request_id)
        if result["status"] in ("completed", "rejected"):
            return result
        try:
            if (
                not runtime.running
                or runtime.run_id != args.run_id
                or native.snapshot()["instance_id"] != args.instance_id
            ):
                raise ClientError("container_identity_changed", "原实例已退出或身份已改变。")
        except ClientError:
            return {
                "request_id": args.request_id,
                "instance_id": args.instance_id,
                "run_id": args.run_id,
                "status": "unknown",
                "last_observed_status": result["status"],
            }
        return result
    if not runtime.running:
        raise ClientError("bridge_session_unavailable", "本容器的客户端进程已退出；请查看当前所属运行日志确认原因。")
    deadline = time.monotonic() + timeout
    if args.command == "login":
        instance_id = None
        phase = None
        while True:
            try:
                current = native.snapshot()
                if instance_id is not None and current["instance_id"] != instance_id:
                    raise ClientError("container_identity_changed", "登录期间原生实例身份已改变。")
                instance_id = cast(str, current["instance_id"])
                bridge = LoginBridge(native.directory, instance_id, runtime.run_id)
                state = bridge.snapshot()
                phase = state["phase"]
                if phase == "failed":
                    reason = state.get("error")
                    raise ClientError(
                        "login_failed", "登录进程报告失败。", {"reason": reason if isinstance(reason, str) else None}
                    )
                if phase == "character_list" and state["characters"] is not None:
                    return {
                        key: state[key]
                        for key in ("phase", "characters", "pending_request_id", "instance_id", "run_id")
                    }
            except ClientError as error:
                if error.code not in {"bridge_unavailable", "login_bridge_unavailable", "login_bridge_stale_state"}:
                    raise
            if time.monotonic() >= deadline:
                raise ClientError("login_timeout", "等待角色列表超时；登录进程继续运行。", {"phase": phase})
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    state = native.snapshot()
    bridge = LoginBridge(native.directory, cast(str, state["instance_id"]), runtime.run_id)
    creation = CharacterCreation(
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
        female=args.gender == "female",
    )
    try:
        request_id = bridge.submit(creation)
    except ClientError as error:
        if error.code == "login_bridge_write_failed":
            error.details.update({"instance_id": bridge.instance_id, "run_id": runtime.run_id})
        raise
    identity = {"request_id": request_id, "instance_id": cast(str, state["instance_id"]), "run_id": runtime.run_id}
    last_status = "unknown"
    while True:
        try:
            result = bridge.result(request_id)
            last_status = cast(str, result["status"])
            if last_status in ("completed", "rejected"):
                return result
            current_runtime = load_runtime(backend.root, backend.name, backend.instance)
            current = native.snapshot()
            if (
                not current_runtime.running
                or current_runtime.run_id != runtime.run_id
                or current["instance_id"] != state["instance_id"]
            ):
                return {**identity, "status": "unknown", "last_observed_status": last_status}
        except (ClientError, KeyboardInterrupt):
            return {**identity, "status": "unknown", "last_observed_status": last_status}
        if time.monotonic() >= deadline:
            return {**identity, **result}
        try:
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        except KeyboardInterrupt:
            return {**identity, "status": "unknown", "last_observed_status": last_status}
