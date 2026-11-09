#!/usr/bin/env python3
"""准备客户端目标/internal网络，关闭客户端后释放自己登记的资源。"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import uuid


def docker_json(*args):
    return json.loads(subprocess.check_output(["docker", *args], text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--project", required=True)
    prepare.add_argument("--service", required=True)
    prepare.add_argument("--workspace-server", action="store_true")
    prepare.add_argument("--plan", action="store_true")
    finish = commands.add_parser("finish")
    finish.add_argument("target_file", type=Path)
    args = parser.parse_args()
    root = Path(os.environ.get("CLIENT_ROOT", Path(__file__).resolve().parents[2])).resolve()
    if not (root / "clientctl.py").is_file():
        parser.error("CLIENT_ROOT须指向客户端运行目录。")
    if args.action == "prepare":
        if args.project == "beidou-ms" and not args.workspace_server:
            parser.error("工作区常驻服务须有用户授权，并显式传--workspace-server。")
        if args.workspace_server and (args.project, args.service) != ("beidou-ms", "beidou-server-all"):
            parser.error("--workspace-server仅匹配本工作区常驻服务。")
        ids = subprocess.check_output([
            "docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=" + args.project,
            "--filter", "label=com.docker.compose.service=" + args.service,
        ], text=True).split()
        if len(ids) != 1:
            raise SystemExit("目标须唯一匹配一个已确认的服务。")
        app = docker_json("inspect", ids[0])[0]
        config = app["HostConfig"]
        if not app["State"]["Running"]:
            raise SystemExit("目标已停止；未创建网络或启动客户端。")
        if config["NetworkMode"] == "host" or (config["PortBindings"] and not args.workspace_server):
            raise SystemExit("目标不符合host网络/宿主端口边界。")
        identity = {"project": args.project, "service": args.service,
                    "container_id": app["Id"], "image": app["Image"]}
        if args.plan:
            print(json.dumps(identity, ensure_ascii=False, indent=2))
            return
        token = uuid.uuid4().hex[:12]
        directory = root / "state" / ("graphical-session-" + token)
        directory.mkdir(mode=0o700)
        network = "beidou-client-play-" + token
        state = dict(identity, client_root=str(root), network=network, session_tag=token,
                     created_at=datetime.now(timezone.utc).isoformat())
        (directory / "session.json").write_text(json.dumps(state, indent=2) + "\n")
        target = {"project": args.project, "service": args.service,
                  "network": network, "expected_image": app["Image"]}
        path = directory / "target.json"
        path.write_text(json.dumps(target, indent=2) + "\n")
        # 先返回恢复入口，准备命令失败时也能按同一文件释放已创建资源。
        print(path, flush=True)
        subprocess.run([
            "docker", "network", "create", "--internal",
            "--label", "com.docker.compose.project=" + args.project,
            "--label", "beidou.client.root=" + str(root),
            "--label", "beidou.skill.session=" + token, network,
        ], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["docker", "network", "connect", network, app["Id"]], check=True)
        return

    path = args.target_file.resolve()
    state = json.loads((path.parent / "session.json").read_text())
    if state["client_root"] != str(root):
        raise SystemExit("会话不属于CLIENT_ROOT，未清理。")
    networks = subprocess.check_output([
        "docker", "network", "ls", "-q", "--filter", "label=beidou.skill.session=" + state["session_tag"],
    ], text=True).split()
    if not networks:
        print("本次网络已经释放。")
        return
    if len(networks) != 1:
        raise SystemExit("会话网络不唯一，保留现场。")
    net = docker_json("network", "inspect", networks[0])[0]
    if net["Name"] != state["network"] or net["Labels"].get("beidou.client.root") != str(root):
        raise SystemExit("网络身份变化，未清理。")
    ids = subprocess.check_output([
        "docker", "ps", "-aq", "--filter", "label=beidou.task=client-v17-maintained",
        "--filter", "label=beidou.client.root=" + str(root),
    ], text=True).split()
    for cid in ids:
        client = docker_json("inspect", cid)[0]
        if net["Name"] not in client["NetworkSettings"]["Networks"]:
            continue
        if client["State"]["Running"] or client["State"]["Pid"] != 0:
            raise SystemExit("本次客户端仍运行；先由主会话执行clientctl.py stop。")
        subprocess.run(["docker", "rm", cid], check=True, stdout=subprocess.DEVNULL)
    app_ids = subprocess.check_output([
        "docker", "ps", "-aq", "--filter", "id=" + state["container_id"],
    ], text=True).split()
    if app_ids:
        app = docker_json("inspect", app_ids[0])[0]
        if net["Name"] in app["NetworkSettings"]["Networks"]:
            subprocess.run(["docker", "network", "disconnect", "--force", net["Name"], app["Id"]], check=True)
    if docker_json("network", "inspect", net["Id"])[0]["Containers"]:
        raise SystemExit("本次网络仍有未解释成员，保留现场。")
    subprocess.run(["docker", "network", "rm", net["Id"]], check=True, stdout=subprocess.DEVNULL)
    print("本次客户端网络已释放，服务未停止。")


if __name__ == "__main__":
    main()
