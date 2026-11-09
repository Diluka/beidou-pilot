#!/usr/bin/env python3
"""管理本目录客户端的限时或持续会话；check 与 plan 不启动任何进程。"""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import time

ROOT = Path(os.environ.get("CLIENT_ROOT", Path(__file__).resolve().parent)).resolve()
IMAGE = os.environ.get("CLIENT_IMAGE", "sha256:bf4b20282017d6e9d28d31147ec65492697800895c034575747e03fe38dee251")
PROJECT = "beidou-v17-client-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:10]


def read_docker(*args):
    return json.loads(subprocess.check_output(["docker", *args], text=True))


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def containers():
    ids = subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=beidou.task=client-v17-maintained", "--filter", "label=beidou.client.root=" + str(ROOT)], text=True).split()
    return read_docker("inspect", *ids) if ids else []


def target(path, running, workspace_server):
    cfg = json.loads(path.read_text())
    require(set(cfg) == {"project", "service", "network", "expected_image"}, "目标配置必须包含 project/service/network/expected_image。")
    if workspace_server:
        require((cfg["project"], cfg["service"]) == ("beidou-ms", "beidou-server-all"), "工作区服务器模式仅接受本工作区服务。")
    else:
        require(cfg["project"] != "beidou-ms", "工作区服务器需要用户授权后显式使用 --workspace-server。")
    require(all(isinstance(v, str) and v for v in cfg.values()), "目标配置必须为非空字符串。")
    ids = subprocess.check_output(["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + cfg["project"], "--filter", "label=com.docker.compose.service=" + cfg["service"]], text=True).split()
    require(len(ids) == 1, "目标必须精确匹配一个隔离应用容器。")
    app = read_docker("inspect", ids[0])[0]
    net = read_docker("network", "inspect", cfg["network"])[0]
    require(net["Internal"] and net["Labels"].get("com.docker.compose.project") == cfg["project"], "目标网络必须是同项目 internal 网络。")
    require(app["Image"] == cfg["expected_image"], "隔离应用镜像与已确认身份不符。")
    require(app["HostConfig"]["NetworkMode"] != "host", "拒绝 host 网络目标。")
    require(workspace_server or not app["HostConfig"]["PortBindings"], "隔离目标不得发布宿主端口。")
    require(cfg["network"] in app["NetworkSettings"]["Networks"], "应用未加入指定网络。")
    require(not running or app["State"]["Running"], "隔离应用当前关闭，不能启动客户端。")
    ip = app["NetworkSettings"]["Networks"][cfg["network"]]["IPAddress"]
    if ip:
        address = ipaddress.IPv4Address(ip)
        require(address.is_private and not address.is_loopback, "目标必须是隔离网络内部 IPv4 地址。")
    require(not running or ip, "运行目标没有内部 IP。")
    return {"project": cfg["project"], "service": cfg["service"], "network": cfg["network"], "container_id": app["Id"], "image": app["Image"], "running": app["State"]["Running"], "ip": ip}


def compose_env(seconds, run_id, resolved=None):
    return dict(os.environ, CLIENT_ROOT=str(ROOT), CLIENT_IMAGE=IMAGE, TARGET_IP=(resolved or {}).get("ip") or "192.0.2.1", TARGET_NETWORK=(resolved or {}).get("network", "client-static-check-only"), RENDER_GID=str(Path("/dev/dri/renderD128").stat().st_gid), CLIENT_SECONDS=str(seconds), RUN_ID=run_id)


def compose_args():
    return ["docker", "compose", "--project-name", PROJECT, "-f", str(ROOT / "compose.json")]


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("action", choices=["check", "plan", "start", "stop", "status"])
parser.add_argument("--target", type=Path, default=ROOT / "config/target.json")
duration = parser.add_mutually_exclusive_group()
duration.add_argument("--seconds", type=int, default=20, help="限时会话，默认20秒，可选5至600秒。")
duration.add_argument("--continuous", action="store_true", help="持续游玩，无强制到期；任务完成后执行 stop。")
parser.add_argument("--workspace-server", action="store_true", help="经用户授权使用本工作区运行服务；客户端仍需独立 internal 网络。")
args = parser.parse_args()
require(args.continuous or 5 <= args.seconds <= 600, "限时会话必须为5至600秒；持续游玩请使用 --continuous。")
seconds = 0 if args.continuous else args.seconds

if args.action == "check":
    for name in ["runtime/client/BeiDou.exe", "runtime/prefix/user.reg", "runtime/bootstrap-intel.sh", "environment/entrypoint.sh", "compose.json"]:
        require((ROOT / name).is_file(), "缺少文件：" + name)
    image_check = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
    for name in ["runtime/bootstrap-intel.sh", "environment/entrypoint.sh"]:
        subprocess.run(["bash", "-n", str(ROOT / name)], check=True)
    subprocess.run(compose_args() + ["config", "--quiet"], env=compose_env(seconds, "static-check"), check=True)
    print(json.dumps({"static_configuration_valid": True, "image_available": image_check.returncode == 0, "client_started": False}, ensure_ascii=False))
elif args.action in {"plan", "start"}:
    resolved = target(args.target.resolve(), args.action == "start", args.workspace_server)
    print(json.dumps(resolved, ensure_ascii=False, indent=2), flush=True)
    if args.action == "start":
        image_check = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)
        require(image_check.returncode == 0, "硬件镜像当前不可用；本入口不会自动拉取或构建。")
        require(not any(c["State"]["Running"] for c in containers()), "该目录已有运行中的客户端。")
        try:
            with socket.create_connection((resolved["ip"], 8484), timeout=3):
                pass
        except OSError as error:
            raise SystemExit("目标登录服务 8484 不可用，未创建客户端容器：" + str(error)) from error
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        out = ROOT / "runtime/runs" / run_id
        out.mkdir(parents=True, mode=0o700)
        (out / "target.json").write_text(json.dumps(resolved, indent=2) + "\n")
        subprocess.run(compose_args() + ["up", "-d", "--no-build", "--no-deps", "--pull", "never", "client"], env=compose_env(seconds, run_id, resolved), check=True)
        print(("客户端持续运行，任务完成后请执行 stop。记录：" if args.continuous else "客户端将在限时结束后关闭；提前结束请执行 stop。记录：") + str(out))
elif args.action == "stop":
    for c in containers():
        if c["State"]["Running"]:
            env = dict(v.split("=", 1) for v in c["Config"]["Env"])
            subprocess.run(["docker", "exec", "--user", "1000:1000", c["Id"], "touch", "/work/runs/" + env["RUN_ID"] + "/finish"], check=True)
            if (ROOT / "runtime/runs" / env["RUN_ID"] / "supervisor-paused").is_file():
                subprocess.run(["docker", "kill", "--signal", "CONT", c["Id"]], check=True)
            for attempt in range(60):
                if not read_docker("inspect", c["Id"])[0]["State"]["Running"]:
                    break
                time.sleep(0.2)
            else:
                print("正常退出期限已到，向本目录客户端容器发送停止信号。")
                subprocess.run(["docker", "stop", "--time", "5", c["Id"]], check=True)
        state = read_docker("inspect", c["Id"])[0]["State"]
        require(not state["Running"] and state["Pid"] == 0, "客户端容器尚未完全退出。")
    print("本目录客户端已关闭；State.Running=false，Pid=0。")
else:
    rows = [{"id": c["Id"], "running": c["State"]["Running"], "pid": c["State"]["Pid"], "exit_code": c["State"]["ExitCode"]} for c in containers()]
    print(json.dumps(rows, ensure_ascii=False, indent=2))
