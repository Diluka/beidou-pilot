"""原生无头客户端的独立容器生命周期；不执行游戏控制循环。"""

from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import cast
import uuid

from .bridge import BridgeClient
from .errors import ClientError, JsonObject
from .instances import InstancePaths
from .profile import LoginProfile
from .resources import load_resources


def docker(*arguments: str) -> str:
    try:
        return subprocess.run(["docker", *arguments], text=True, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        raise ClientError("headless_runtime_failed", "无头客户端容器操作失败。", {"reason": detail}) from error


def save_logs(identifier: str, directory: Path) -> JsonObject:
    result = subprocess.run(["docker", "logs", identifier], text=True, capture_output=True)
    (directory / "headless.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise ClientError("headless_log_failed", "无头客户端退出日志读取失败，已保留工具输出。")
    for line in reversed((result.stdout + result.stderr).splitlines()):
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") in {"closed", "fatal"}:
            reason = event.get("reason")
            if reason in {"sigterm", "sigint", "disconnected", "fatal_error"}:
                return {"stop_reason": reason}
            break
    return {}


def registration(root: Path, instance: str = "default") -> JsonObject | None:
    path = InstancePaths(root, "headless", instance).registration
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ClientError("headless_registration_invalid", "无头客户端会话登记无法读取。") from error
    if not isinstance(value, dict) or any(not isinstance(value.get(field), str) for field in
                                          ("container_id", "run_id", "image", "run_dir")):
        raise ClientError("headless_registration_invalid", "无头客户端会话登记字段无效。")
    return cast(JsonObject, value)


def current_container(root: Path, instance: str = "default") -> JsonObject | None:
    saved = registration(root, instance)
    if saved is None:
        return None
    if not saved["container_id"]:
        return None
    ids = docker("ps", "-aq", "--filter", "id=" + cast(str, saved["container_id"])).split()
    if not ids:
        return None
    container = json.loads(docker("inspect", ids[0]))[0]
    labels = container["Config"]["Labels"]
    if (labels.get("beidou.task") != "maple-headless-maintained"
            or labels.get("beidou.client.root") != str(root)
            or labels.get("beidou.client.instance", "default") != instance
            or container["Image"] != saved["image"]
            or container["HostConfig"]["Privileged"]
            or container["HostConfig"]["PortBindings"]
            or container["HostConfig"]["NetworkMode"] == "host"):
        raise ClientError("headless_identity_changed", "无头客户端容器身份与本次登记不符，保留现场。")
    return cast(JsonObject, container)


def is_running(root: Path, instance: str = "default") -> bool:
    container = current_container(root, instance)
    return container is not None and cast(JsonObject, container["State"])["Running"] is True


def any_running(root: Path) -> bool:
    return bool(docker("ps", "-q", "--filter", "label=beidou.task=maple-headless-maintained",
                       "--filter", "label=beidou.client.root=" + str(root)).split())


def registered_names(root: Path) -> list[str]:
    names = ["default"] if InstancePaths(root, "headless").registration.is_file() else []
    names.extend(path.parent.name for path in (root / "state/instances").glob("*/maple-session-headless.json"))
    return sorted(names)


def list_instances(root: Path) -> list[JsonObject]:
    records: list[JsonObject] = []
    for instance in registered_names(root):
        saved = registration(root, instance)
        assert saved is not None
        container = current_container(root, instance)
        running = container is not None and cast(JsonObject, container["State"])["Running"] is True
        records.append({"name": instance, "backend": "headless", "running": running,
                        "container_id": saved["container_id"] if container else None,
                        "run_id": saved["run_id"], "character_id": saved.get("character_id"),
                        "channel": saved.get("channel"), "run_dir": saved["run_dir"]})
    return records


def status(root: Path, instance: str = "default") -> JsonObject:
    container = current_container(root, instance)
    saved = registration(root, instance)
    if container is None or cast(JsonObject, container["State"])["Running"] is not True:
        result: JsonObject = {"backend": "headless", "instance": instance, "stage": "STOPPED", "running": False,
                              "channel": None, "character": None, "unavailable": []}
        if saved is not None:
            result.update(run_dir=saved["run_dir"], exit_code=saved.get("exit_code"),
                          stop_reason=saved.get("stop_reason", "container_missing"))
            if container is not None:
                stopped = cast(JsonObject, container["State"])
                details = save_logs(cast(str, container["Id"]), Path(cast(str, saved["run_dir"])))
                result.update(exit_code=stopped["ExitCode"], finished_at=stopped["FinishedAt"],
                              stop_reason=details.get("stop_reason", "process_exited" if stopped["ExitCode"] == 0 else "process_failed"))
        return result
    assert saved is not None
    state = BridgeClient(root, "headless", instance).snapshot()
    return {"backend": "headless", "instance": instance, "stage": "IN_GAME" if state["ready"] else "STARTING",
            "running": True, "channel": saved.get("channel"), "character": state["character"],
            "map_id": state["map_id"], "position": state["position"],
            "unavailable": [] if state["ready"] else ["无头客户端尚未进入可操作场景。"],
            "state": cast(JsonObject, state)}


def open_game(root: Path, *, target: Path | None, profile: LoginProfile,
              timeout: float = 90, workspace_server: bool = False, instance: str = "default") -> JsonObject:
    if not 5 <= timeout <= 180:
        raise ClientError("invalid_open_options", "启动等待期限须为5至180秒。")
    paths = InstancePaths(root, "headless", instance)
    existing = current_container(root, instance)
    if existing is not None and cast(JsonObject, existing["State"])["Running"] is True:
        saved = registration(root, instance)
        assert saved is not None
        if target is not None:
            requested_target = json.loads(target.resolve().read_text())
            if requested_target != saved.get("target_config"):
                raise ClientError("headless_target_mismatch", "当前无头会话目标与请求不同，保留现有会话。")
        if (profile.character_id != saved["character_id"] or profile.world != saved.get("world", 0)
                or profile.channel + 1 != saved["channel"]):
            raise ClientError("headless_character_mismatch", "当前无头会话角色、世界或频道与请求不同，保留现有会话。")
        result = status(root, instance)
        result.update(started=False, resumed=True, ready=result["stage"] == "IN_GAME")
        return result
    if target is None:
        raise ClientError("headless_target_required", "启动新的无头客户端需要显式 --target。")
    target = target.resolve()
    graphical = docker("ps", "-q", "--filter", "label=beidou.task=client-v17-maintained",
                       "--filter", "label=beidou.client.root=" + str(root)).split()
    if graphical:
        raise ClientError("client_already_running", "北斗客户端仍在运行；先正常关闭再切换客户端。")
    arguments = [sys.executable, str(root / "clientctl.py"), "plan", "--target", str(target)]
    if workspace_server:
        arguments.append("--workspace-server")
    planned = subprocess.run(arguments, text=True, capture_output=True)
    if planned.returncode:
        raise ClientError("headless_target_invalid", "无头目标未通过当前客户端目标核验。",
                          {"reason": planned.stderr.strip() or planned.stdout.strip()})
    resolved = json.loads(planned.stdout)
    if not resolved["running"] or not resolved["ip"]:
        raise ClientError("headless_target_stopped", "目标未运行，未启动无头客户端。")
    image_tag = os.environ.get("HEADLESS_CLIENT_IMAGE", "local/beidou-pilot:local")
    image = docker("image", "inspect", image_tag, "--format", "{{.Id}}").strip()
    resources = load_resources(root).headless_resources
    if not resources.is_dir():
        raise ClientError("headless_resources_missing", "无头资源目录尚未准备。")
    if existing is not None:
        close_game(root, instance)
    (root / "state").mkdir(parents=True, exist_ok=True)
    # 同CID并发open实际会同时通过检查；只串行化创建与登记，入图等待保持独立。
    with (root / "state/maple-headless-start.lock").open("a") as startup:
        fcntl.flock(startup, fcntl.LOCK_EX)
        target_config = json.loads(target.read_text())
        for other in registered_names(root):
            if other == instance:
                continue
            other_saved = registration(root, other)
            assert other_saved is not None
            other_target = other_saved.get("target_container_id")
            same_target = (other_target == resolved["container_id"] if other_target is not None
                           else other_saved.get("target_config") == target_config)
            if (same_target and other_saved.get("character_id") == profile.character_id
                    and other_saved.get("world", 0) == profile.world and is_running(root, other)):
                raise ClientError("character_already_controlled", "同一目标的角色已由另一个实例控制。",
                                  {"instance": other, "character_id": profile.character_id})
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        directory = paths.runs / run_id
        directory.mkdir(parents=True, mode=0o700)
        bridge = paths.bridge
        bridge.mkdir(parents=True, mode=0o700, exist_ok=True)
        runtime_config = {**asdict(profile), "server_host": resolved["ip"], "server_port": 8484,
                          "resources_dir": "/data", "bridge_dir": "/bridge", "run_id": run_id}
        runtime_profile = directory / "runtime.private.json"
        descriptor = os.open(runtime_profile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(runtime_config, stream)
        (directory / "target.json").write_text(json.dumps(resolved, indent=2) + "\n")
        name = "maple-headless-" + hashlib.sha256(str(root).encode()).hexdigest()[:8] + "-" + instance + "-" + uuid.uuid4().hex[:8]
        record = {"container_id": "", "run_id": run_id, "image": image, "run_dir": str(directory),
                  "target_file": str(target), "channel": profile.channel + 1,
                  "character_id": profile.character_id, "world": profile.world,
                  "target_config": target_config, "target_container_id": resolved["container_id"],
                  "backend": "headless", "instance": instance}
        saved_path = paths.registration
        saved_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path.write_text(json.dumps(record, indent=2) + "\n")
        container_id = docker("run", "-d", "--name", name, "--label", "beidou.task=maple-headless-maintained",
                              "--label", "beidou.client.root=" + str(root), "--network", resolved["network"],
                              "--label", "beidou.client.instance=" + instance,
                              "--read-only", "--cpus", "2", "--memory", "1g", "--pids-limit", "128",
                              "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                              "--user", str(os.getuid()) + ":" + str(os.getgid()),
                              "-v", str(resources) + ":/data:ro", "-v", str(runtime_profile) + ":/run/headless-config.json:ro",
                              "-v", str(bridge) + ":/bridge", image, "--config", "/run/headless-config.json").strip()
        record["container_id"] = container_id
        saved_path.write_text(json.dumps(record, indent=2) + "\n")
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        container = current_container(root, instance)
        if container is None or cast(JsonObject, container["State"])["Running"] is not True:
            details = save_logs(container_id, directory)
            details["run_dir"] = str(directory)
            if container is not None:
                details["exit_code"] = cast(JsonObject, container["State"])["ExitCode"]
            raise ClientError("headless_start_failed", "无头客户端已退出，日志已保留。", details)
        try:
            state = BridgeClient(root, "headless", instance).snapshot()
        except ClientError as error:
            if error.code not in {"bridge_unavailable", "bridge_session_mismatch", "stale_bridge_state"}:
                raise
        else:
            if state["ready"]:
                return {"backend": "headless", "instance": instance, "ready": True, "started": True, "resumed": False,
                        "character": state["character"], "state": cast(JsonObject, state),
                        "channel": record["channel"], "run_dir": str(directory)}
        time.sleep(.1)
    raise ClientError("headless_open_timeout", "无头客户端未在期限内入图，保留现场。", {"run_dir": str(directory)})


def close_game(root: Path, instance: str = "default") -> JsonObject:
    container = current_container(root, instance)
    if container is None:
        return {"backend": "headless", "instance": instance, "status": "closed", "cleanup_pending": False}
    identifier = cast(str, container["Id"])
    if cast(JsonObject, container["State"])["Running"] is True:
        # SIGTERM由原生宿主释放控制并关闭socket；容器退出另外核实。
        docker("stop", "--time", "10", identifier)
    stopped = json.loads(docker("inspect", identifier))[0]["State"]
    if stopped["Running"] or stopped["Pid"] != 0:
        raise ClientError("headless_close_unconfirmed", "无头客户端尚未确认退出。")
    saved = registration(root, instance)
    assert saved is not None
    details = save_logs(identifier, Path(cast(str, saved["run_dir"])))
    details.update(exit_code=stopped["ExitCode"], finished_at=stopped["FinishedAt"])
    details.setdefault("stop_reason", "process_exited" if stopped["ExitCode"] == 0 else "process_failed")
    (Path(cast(str, saved["run_dir"])) / "exit.json").write_text(json.dumps(details, indent=2) + "\n")
    docker("rm", identifier)
    saved["closed_at"] = datetime.now(timezone.utc).isoformat()
    saved.update(details)
    InstancePaths(root, "headless", instance).registration.write_text(json.dumps(saved, indent=2) + "\n")
    return {"backend": "headless", "instance": instance, "status": "closed", "cleanup_pending": False,
            "container_id": identifier, "run_dir": saved["run_dir"], **details}
