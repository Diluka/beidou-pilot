#!/usr/bin/env python3
"""初始化本容器的配置和登记，然后交给原版 GUI 客户端。"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

from beidou_pilot.errors import ClientError
from beidou_pilot.instances import InstancePaths
from beidou_pilot.profile import load_account_profile, load_profile


def main() -> None:
    os.umask(0o077)
    root = Path(os.environ["CLIENT_ROOT"]).resolve()
    os.environ["CLIENT_ROOT"] = str(root)
    os.environ["MAPLE_RESOURCES_CONFIG"] = str(root / "config/resources.json")
    backend = os.environ.get("MAPLE_BACKEND", "beidou")
    if backend != "beidou":
        raise ClientError("unsupported_backend", "客户端后端仅为原版 GUI。")
    paths = InstancePaths(root, backend, os.environ["MAPLE_INSTANCE"])
    run_id = os.environ["RUN_ID"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id):
        raise ClientError("invalid_run_id", "容器运行 ID 格式无效。")
    mode = os.environ.get("MAPLE_LOGIN_MODE", "character")
    if mode not in {"character", "account"}:
        raise ClientError("login_invalid", "登录模式必须为 character 或 account。")
    if mode == "account":
        print(
            json.dumps(
                {"event": "login_awaiting_request", "message": "GUI 账号模式等待显式 login 请求；尚未确认登录。"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        profile = load_account_profile(root / "account.json")
    else:
        profile = load_profile(root / "account.json")
    if profile.world != 0 or profile.channel >= 20:
        raise ClientError("unsupported_login_destination", "原版 GUI 登录只支持世界 0 和第 1 至 20 频道。")
    target = json.loads((root / "server.json").read_text())
    if (
        not isinstance(target, dict)
        or set(target) != {"project", "service", "network"}
        or any(not isinstance(value, str) or not value for value in target.values())
    ):
        raise ClientError("server_invalid", "本次服务器配置须提供 project、service 和 network。")
    run_dir = paths.runs / run_id
    directories = {
        root / "state",
        root / "config",
        paths.state_directory,
        paths.runtime_directory,
        paths.bridge,
        paths.runs,
        run_dir,
        paths.runtime_directory / "prefix",
    }
    owner = (1000, 1000)
    for directory in directories:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if os.getuid() == 0:
            os.chown(directory, *owner)
    manifest = root / "state/agent-bridge-build.json"
    manifest.unlink(missing_ok=True)
    manifest.symlink_to("/opt/beidou-pilot/native/manifest.json")
    resources = {
        "game_data": "/data",
        "gui_client": "/client",
        "gui_dll": "/opt/beidou-pilot/native/ijl15.dll",
    }
    outputs = [(root / "config/resources.json", resources)]
    registration = {
        "backend": backend,
        "instance": paths.name,
        "run_id": run_id,
        "container_id": os.environ["HOSTNAME"],
        "image": os.environ["CLIENT_IMAGE_ID"],
        "source_revision": Path("/opt/beidou-pilot/REVISION").read_text().strip(),
        "pid": os.getpid(),
        "run_dir": str(run_dir),
        "character_id": profile.character_id if mode == "character" else None,
        "world": profile.world,
        "channel": profile.channel,
        "target": target,
        "target_ip": os.environ["TARGET_IP"],
        "target_container_id": os.environ["TARGET_CONTAINER_ID"],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    outputs.append((root / "state/container.json", registration))
    for path, value in outputs:
        pending = path.with_name(path.name + ".new")
        pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        pending.chmod(0o600)
        if os.getuid() == 0:
            os.chown(pending, *owner)
        pending.replace(path)
    os.environ["MAPLE_BRIDGE_DIR"] = "Z:" + str(paths.bridge).replace("/", "\\")
    os.environ["MAPLE_DATA_ROOT"] = "Z:" + resources["game_data"].replace("/", "\\")
    os.execv("/opt/beidou/entrypoint.sh", ["/opt/beidou/entrypoint.sh"])


if __name__ == "__main__":
    try:
        main()
    except ClientError as error:
        print(
            json.dumps({"event": "startup_failed", "code": error.code, "message": error.message}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(2)
    except (OSError, json.JSONDecodeError, UnicodeError, KeyError):
        print(
            '{"event":"startup_failed","code":"runtime_configuration_invalid",'
            '"message":"容器启动配置不可用；请检查启动参数和挂载。"}',
            file=sys.stderr,
        )
        raise SystemExit(2)
