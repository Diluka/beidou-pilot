"""幂等打开客户端并用普通 GUI 完成已有角色登录。"""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from typing import cast
import uuid

from .backend import Backend, JsonObject
from .errors import ClientError


def adopt_session(backend: Backend, stage: JsonObject | None = None) -> JsonObject:
    """按容器实际网络采用已登记会话；不启动、停止或更改 Docker 资源。"""
    clients = json.loads(backend.text("clientctl", "status"))
    ids = [entry["id"] for entry in clients]
    containers = []
    if ids:
        try:
            inspected = subprocess.run(["docker", "inspect", *ids], text=True, capture_output=True, check=True)
        except OSError as error:
            raise ClientError("session_inspection_unavailable", "无法核验客户端网络归属。", {"reason": str(error)}) from error
        except subprocess.CalledProcessError as error:
            raise ClientError("session_inspection_failed", "客户端网络归属核验失败。", {"stderr": error.stderr.strip()}) from error
        containers = json.loads(inspected.stdout)
    directory = backend.root / "state"
    saved_path = directory / "maple-session.json"
    registration_problems: list[str] = []
    try:
        saved = json.loads(saved_path.read_text()) if saved_path.is_file() else {}
    except (OSError, json.JSONDecodeError) as error:
        saved = {}
        registration_problems.append(str(saved_path) + ": " + str(error))
    current = stage.get("client") if stage is not None else None
    current_id = current.get("container_id") if isinstance(current, dict) else None
    if current_id is None:
        running = [entry for entry in containers if entry["State"]["Running"]]
        if running:
            containers = running
        elif isinstance(saved, dict) and saved.get("client_id"):
            recorded = [entry for entry in containers if entry["Id"] == saved["client_id"]]
            if recorded:
                containers = recorded
    else:
        containers = [entry for entry in containers if entry["Id"].startswith(cast(str, current_id))]
    targets: list[JsonObject] = []
    for path in directory.rglob("target.json"):
        session_path = path.parent / "session.json"
        if not session_path.is_file():
            continue
        try:
            target = json.loads(path.read_text())
            registration = json.loads(session_path.read_text())
        except (OSError, json.JSONDecodeError) as error:
            registration_problems.append(str(path) + ": " + str(error))
            continue
        if not isinstance(target, dict) or not isinstance(registration, dict):
            registration_problems.append(str(path) + ": 登记不是 JSON 对象。")
            continue
        if (set(target) != {"project", "service", "network", "expected_image"}
                or any(not isinstance(value, str) or not value for value in target.values())
                or any(not isinstance(registration.get(key), str) or not registration[key]
                       for key in ("client_root", "network", "session_tag", "container_id", "image", "project", "service"))):
            registration_problems.append(str(path) + ": 会话登记字段不完整。")
            continue
        if registration.get("client_root") != str(backend.root):
            continue
        network = target.get("network")
        if (not isinstance(network, str) or registration.get("network") != network
                or any(target.get(key) != registration.get(key)
                       for key in ("project", "service"))
                or target.get("expected_image") != registration.get("image")):
            registration_problems.append(str(path) + ": target 与 session 登记不一致。")
            continue
        for container in containers:
            labels = container["Config"]["Labels"]
            if (labels.get("beidou.client.root") != str(backend.root)
                    or labels.get("beidou.task") != "client-v17-maintained"
                    or network not in container["NetworkSettings"]["Networks"]):
                continue
            environment = dict(value.split("=", 1) for value in container["Config"]["Env"])
            targets.append({"target_file": str(path.resolve()), "client_id": container["Id"],
                            "run_id": environment["RUN_ID"], "network": network,
                            "continuous": environment.get("CLIENT_SECONDS") == "0"})
    if len(targets) == 1:
        selected = targets[0]
        directory.mkdir(mode=0o700, exist_ok=True)
        record = dict(saved) if isinstance(saved, dict) and saved.get("target_file") == selected["target_file"] else {}
        record.update(selected)
        record["adopted_at"] = datetime.now(timezone.utc).isoformat()
        saved_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return {**selected, "cleanup_pending": False, "ownership": "container-network-and-registration"}
    try:
        networks = subprocess.run(["docker", "network", "ls", "--filter",
                                  "label=beidou.client.root=" + str(backend.root),
                                  "--format", "{{.Name}}"], text=True, capture_output=True, check=True)
    except OSError as error:
        raise ClientError("session_inspection_unavailable", "无法核验客户端登记网络。", {"reason": str(error)}) from error
    except subprocess.CalledProcessError as error:
        raise ClientError("session_inspection_failed", "客户端登记网络核验失败。", {"stderr": error.stderr.strip()}) from error
    owned_networks = networks.stdout.splitlines()
    return {"target_file": None, "cleanup_pending": bool(owned_networks),
            "reason": "registration_not_unique" if len(targets) > 1 else "no_proven_registered_target",
            "candidates": targets, "registered_networks": owned_networks,
            "registration_problems": registration_problems}


def close_game(backend: Backend) -> JsonObject:
    """正常停止本目录客户端，再回收唯一已证明归属的会话网络。"""
    adopted = adopt_session(backend)
    backend.text("clientctl", "stop")
    clients = json.loads(backend.text("clientctl", "status"))
    if any(entry["running"] or entry["pid"] != 0 for entry in clients):
        raise ClientError("close_not_confirmed", "客户端尚未完全退出。", {"clients": clients})
    target = adopted["target_file"]
    if target is None:
        return {"status": "closed", "clients": clients, "cleanup_pending": adopted["cleanup_pending"],
                "network_cleanup": adopted}
    try:
        released = backend.text("session", "finish", cast(str, target))
    except ClientError as error:
        return {"status": "closed", "clients": clients, "cleanup_pending": True,
                "target_file": target, "network_cleanup": {"code": error.code, "message": error.message,
                                                           "details": error.details}}
    saved_path = backend.root / "state/maple-session.json"
    record = json.loads(saved_path.read_text())
    record["closed_at"] = datetime.now(timezone.utc).isoformat()
    record["network_cleanup"] = "released"
    saved_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return {"status": "closed", "clients": clients, "cleanup_pending": False,
            "target_file": target, "network_cleanup": released.strip()}


def open_game(backend: Backend, *, channel: int = 1, character: str | None = None,
              character_index: int | None = None,
              target: Path | None = None, project: str = "beidou-ms",
              service: str = "beidou-server-all", workspace_server: bool = True,
              timeout: float = 90) -> JsonObject:
    """复用现有会话；只有 STOPPED 才准备隔离目标并持续启动。"""
    if not 1 <= channel <= 20 or not 5 <= timeout <= 180:
        raise ClientError("invalid_open_options", "频道须为 1 至 20，等待时间须为 5 至 180 秒。")
    if character_index is not None and (character is not None or not 0 <= character_index < 24):
        raise ClientError("invalid_character_selection", "角色名与索引互斥；角色索引须为 0 至 23。")
    if character is None and character_index is None:
        private_name = backend.root / "private/character-name.json"
        if private_name.is_file():
            if private_name.stat().st_mode & 0o777 != 0o600:
                raise ClientError("private_file_permissions", "私密角色文件须为 0600。")
            try:
                document = json.loads(private_name.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise ClientError("invalid_character_file", "私密角色文件无法读取或不是有效 JSON。") from error
            value = document.get("character_name") if isinstance(document, dict) else None
            if not isinstance(value, str) or not value or any(ord(letter) < 32 for letter in value):
                raise ClientError("invalid_character_name", "私密角色名称格式无效。")
            character = value
    elif character is not None and (not character or any(ord(letter) < 32 for letter in character)):
        raise ClientError("invalid_character_name", "角色名称格式无效。")
    stage = backend.read("stage")
    resumed = stage["running"] is True
    started = False
    target_path = target.resolve() if target is not None else None
    completed: list[str] = []
    adoption = adopt_session(backend, stage) if resumed else None
    if adoption is not None and adoption["target_file"] is not None:
        adopted_target = Path(cast(str, adoption["target_file"]))
        if target_path is not None:
            try:
                requested = json.loads(target_path.read_text())
                current_target = json.loads(adopted_target.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise ClientError("target_unreadable", "无法核对显式目标文件，保留现有客户端。", {"path": str(target_path)}) from error
            if requested != current_target:
                raise ClientError("target_mismatch", "当前客户端连接的目标与请求不同，未切换或重启。",
                                  {"requested": str(target_path), "actual": str(adopted_target)})
        target_path = adopted_target
    elif resumed and target_path is not None:
        raise ClientError("current_target_unverified", "无法证明现有客户端与显式目标一致，保留现场。")
    if stage["stage"] == "STOPPED":
        check = json.loads(backend.text("clientctl", "check"))
        if check["image_available"] is not True:
            raise ClientError("client_image_unavailable", "客户端镜像不可用；未准备网络或启动客户端。")
        if target_path is None:
            arguments = ["prepare", "--project", project, "--service", service]
            if workspace_server:
                arguments.append("--workspace-server")
            # prepare 在创建网络前输出恢复路径；引擎失败时 Backend 保留 stdout。
            output = backend.text("session", *arguments)
            target_path = Path(output.splitlines()[0]).resolve()
        else:
            try:
                requested = json.loads(target_path.read_text())
            except (OSError, json.JSONDecodeError) as error:
                raise ClientError("target_unreadable", "显式目标文件无法读取或不是有效 JSON。", {"path": str(target_path)}) from error
            workspace_server = (isinstance(requested, dict)
                                and (requested.get("project"), requested.get("service"))
                                == ("beidou-ms", "beidou-server-all"))
        arguments = ["start", "--target", str(target_path), "--continuous"]
        if workspace_server:
            arguments.append("--workspace-server")
        backend.text("clientctl", *arguments)
        started = True
        completed.append("start")
        stage = backend.read("stage")
        directory = backend.root / "state"
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.joinpath("maple-session.json").write_text(json.dumps({
            "target_file": str(target_path), "started_at": datetime.now(timezone.utc).isoformat(),
            "channel": channel, "character": character, "continuous": True,
            "run_id": cast(JsonObject, stage["client"])["run_id"],
        }, ensure_ascii=False) + "\n")
    deadline = time.monotonic() + timeout
    while True:
        current = stage["stage"]
        if current == "IN_GAME":
            if adoption is None:
                adoption = adopt_session(backend, stage)
                if adoption["target_file"] is not None:
                    target_path = Path(cast(str, adoption["target_file"]))
            if (backend.root / "state/agent-bridge-build.json").is_file():
                from .bridge import BridgeClient

                try:
                    native_ready = BridgeClient(backend.root).snapshot()["ready"]
                except ClientError as error:
                    if error.code not in {"bridge_unavailable", "stale_bridge_state", "bridge_session_mismatch"}:
                        raise
                    native_ready = False
                if not native_ready:
                    if time.monotonic() >= deadline:
                        raise ClientError("in_game_observation_unavailable", "角色已入图，但原生桥尚未恢复有效采样。", stage)
                    time.sleep(.1)
                    stage = backend.read("stage")
                    continue
            observed = backend.read("observe")
            current_character = observed.get("character")
            if (observed.get("native_values_valid") is not True
                    or observed.get("position") is None or not isinstance(current_character, dict)):
                raise ClientError("in_game_observation_unavailable", "入图状态尚不能可靠确认。", stage)
            if character_index is not None and character is None:
                saved_selection = backend.root / "state/maple-selection.json"
                saved = json.loads(saved_selection.read_text()) if saved_selection.is_file() else None
                client = cast(JsonObject, stage["client"])
                if (not isinstance(saved, dict) or saved.get("run_id") != client["run_id"]
                        or saved.get("index") != character_index or saved.get("id") != current_character["id"]):
                    raise ClientError("character_index_unavailable", "当前已入图，缺少同一运行记录的角色索引；请按实际角色名继续。",
                                      {"requested_index": character_index, "actual": current_character})
                character = cast(str, saved["name"])
            if character is not None and current_character["name"] != character:
                raise ClientError("character_mismatch", "当前角色与请求角色不同，保留现有客户端。",
                                  {"expected": character, "actual": current_character["name"], "stage": stage})
            if stage["channel"] != channel:
                raise ClientError("channel_mismatch", "当前频道与请求频道不同，保留现有客户端。",
                                  {"expected": channel, "actual": stage["channel"], "stage": stage})
            return {"ready": True, "started": started, "resumed": resumed,
                    "skipped_login": "login" not in completed, "actions": completed,
                    "character": current_character, "channel": channel,
                    "target_file": str(target_path) if target_path else None,
                    "session": adoption,
                    "stage": stage, "state": observed}
        if current in {"STOPPED", "UNKNOWN"} or time.monotonic() >= deadline:
            diagnostic = backend.root / "runtime/runs" / ("open-diagnostic-" + uuid.uuid4().hex + ".json")
            diagnostic.parent.mkdir(parents=True, exist_ok=True)
            with diagnostic.open("x") as stream:
                json.dump({"stage": stage, "completed_actions": completed,
                           "requested_channel": channel, "requested_character": character,
                           "requested_character_index": character_index,
                           "target_file": str(target_path) if target_path else None},
                          stream, ensure_ascii=False, indent=2)
            raise ClientError("open_stage_unknown" if current in {"STOPPED", "UNKNOWN"} else "open_timeout",
                              "客户端未达到可确认的入图状态，已保存诊断并保留现场。",
                              {"stage": stage, "completed_actions": completed,
                               "diagnostic": str(diagnostic), "target_file": str(target_path) if target_path else None})
        if stage.get("renderer") == "software":
            raise ClientError("software_renderer", "当前客户端使用软件渲染，停止自动登录并保留诊断现场。", stage)
        login = stage.get("login")
        pending = isinstance(login, dict) and (login.get("request_pending") or login.get("transition_pending"))
        if current in {"LOGIN", "WORLD_SELECT", "CHANNEL_SELECT", "CHARACTER_SELECT"} and not pending:
            geometry = stage.get("game_geometry")
            if not isinstance(geometry, dict) or geometry.get("width") != 1280 or geometry.get("height") != 720:
                raise ClientError("unsupported_login_geometry", "登录布局须为当前已验证的 1280×720 游戏区。", stage)
            x, y = cast(int, geometry["x"]), cast(int, geometry["y"])
            if current == "LOGIN" and "login" not in completed:
                if stage.get("renderer") != "intel":
                    time.sleep(0.5)
                    stage = backend.read("stage")
                    continue
                backend.desktop([{"action": "click", "x": x + 727, "y": y + 308}])
                backend.text("runtime-ui", "key", "ctrl+a")
                backend.text("runtime-ui", "type-private", "name")
                backend.desktop([{"action": "click", "x": x + 727, "y": y + 336}])
                backend.text("runtime-ui", "key", "ctrl+a")
                backend.text("runtime-ui", "type-private", "password")
                backend.desktop([{"action": "click", "x": x + 880, "y": y + 306}])
                completed.append("login")
            elif current == "WORLD_SELECT" and "world" not in completed:
                backend.desktop([{"action": "click", "x": x + 483, "y": y + 213},
                               {"action": "wait", "seconds": 0.7},
                               {"action": "hold", "keys": ["Return"], "seconds": 0.1}])
                completed.append("world")
            elif current == "CHANNEL_SELECT" and "channel" not in completed:
                panel = cast(JsonObject, stage["channel_panel"])
                channels = cast(list[JsonObject], panel["channels"])
                matches = [entry for entry in channels if entry["channel"] == channel]
                if len(matches) != 1:
                    raise ClientError("channel_unavailable", "频道面板未提供请求频道。",
                                      {"requested": channel, "channels": channels})
                rect = matches[0]["root_rect"]
                if not isinstance(rect, dict):
                    raise ClientError("channel_layout_unavailable", "频道格子尚未获得可靠窗口投影，未点击。", stage)
                backend.desktop([{"action": "double-click", "x": (cast(int, rect["left"]) + cast(int, rect["right"])) // 2,
                               "y": (cast(int, rect["top"]) + cast(int, rect["bottom"])) // 2}])
                completed.append("channel")
            elif current == "CHARACTER_SELECT" and "character" not in completed:
                if cast(JsonObject, login).get("characters_available") is not True:
                    raise ClientError("character_list_unavailable", "角色页已识别，但角色名单尚不能可靠解析；未发送选角输入。", stage)
                characters = cast(list[JsonObject], cast(JsonObject, login)["characters"])
                matches = [entry for entry in characters
                           if ((character_index is not None and entry["index"] == character_index)
                               or (character_index is None and (character is None or entry["name"] == character)))]
                if len(matches) != 1:
                    raise ClientError("character_not_unique", "角色列表未唯一匹配目标角色；不自动创建角色。",
                                      {"requested": character, "requested_index": character_index, "characters": characters})
                selected = matches[0]
                selection = stage
                selected_login = cast(JsonObject, login)
                active_index = cast(int, selected_login["selected_index"])
                desired_index = cast(int, selected["index"])
                # CUIAvatar 的 Left/Right 会同步 CLogin 索引，并自动切换每页三个角色。
                while active_index != desired_index:
                    expected_index = 0 if active_index == -1 else active_index + (1 if active_index < desired_index else -1)
                    key = "Right" if active_index < desired_index else "Left"
                    backend.desktop([{"action": "hold", "keys": [key], "seconds": 0.08},
                                     {"action": "wait", "seconds": 0.15}])
                    selection = backend.read("stage")
                    selected_login = selection.get("login")
                    if (selection["stage"] != "CHARACTER_SELECT" or not isinstance(selected_login, dict)
                            or selected_login.get("selected_index") != expected_index):
                        raise ClientError("character_selection_unconfirmed", "角色键盘选择未由客户端索引确认，未继续输入或开始游戏。", selection)
                    active_index = expected_index
                character = cast(str, selected["name"])
                directory = backend.root / "state"
                directory.mkdir(mode=0o700, exist_ok=True)
                client = cast(JsonObject, selection["client"])
                directory.joinpath("maple-selection.json").write_text(json.dumps({
                    "run_id": client["run_id"], "index": desired_index,
                    "id": selected["id"], "name": character,
                }, ensure_ascii=False) + "\n")
                backend.desktop([{"action": "click", "x": x + 866, "y": y + 223}])
                completed.append("character")
        time.sleep(0.5)
        stage = backend.read("stage")
