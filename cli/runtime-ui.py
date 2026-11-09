#!/usr/bin/env python3
"""只操作本目录已启动的客户端；秘密仅由0600文件经stdin传入。"""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(os.environ.get("CLIENT_ROOT", Path(__file__).resolve().parent)).resolve()
p = argparse.ArgumentParser(description=__doc__)
sub = p.add_subparsers(dest="action", required=True)
sub.add_parser("windows")
s = sub.add_parser("screenshot"); s.add_argument("name")
s = sub.add_parser("click"); s.add_argument("x", type=int); s.add_argument("y", type=int)
s = sub.add_parser("key"); s.add_argument("keys", nargs="+")
s = sub.add_parser("type-private"); s.add_argument("field", choices=["name", "password"])
a = p.parse_args()
ids = subprocess.check_output(["docker", "ps", "-q", "--filter", "label=beidou.task=client-v17-maintained", "--filter", "label=beidou.client.root=" + str(ROOT)], text=True).split()
if len(ids) != 1:
    raise SystemExit("本目录必须恰有一个运行中的客户端。")
c = json.loads(subprocess.check_output(["docker", "inspect", ids[0]], text=True))[0]
if c["HostConfig"]["Privileged"] or c["HostConfig"]["PortBindings"] or c["HostConfig"]["NetworkMode"] == "host":
    raise SystemExit("客户端容器边界与约定不符。")
env = dict(v.split("=", 1) for v in c["Config"]["Env"])
run = ROOT / "runtime/runs" / env["RUN_ID"]

def invoke(args, secret=None):
    command = ["docker", "exec"] + (["-i"] if secret is not None else []) + ["--user", "1000:1000", c["Id"], "env", "DISPLAY=:97"] + args
    return subprocess.run(command, input=secret, capture_output=True, check=True)

if a.action == "windows":
    print(invoke(["xwininfo", "-root", "-tree"]).stdout.decode())
elif a.action == "screenshot":
    if not a.name.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("截图名只允许字母、数字、短横线和下划线。")
    target = run / (a.name + ".png")
    if target.exists():
        raise SystemExit("截图已存在，拒绝覆盖。")
    invoke(["import", "-window", "root", "/work/runs/" + env["RUN_ID"] + "/" + target.name])
    print(target)
elif a.action == "click":
    if not (0 <= a.x < 1920 and 0 <= a.y < 1080):
        raise SystemExit("点击坐标超出桌面范围。")
    invoke(["xdotool", "mousemove", str(a.x), str(a.y), "click", "1"])
elif a.action == "key":
    invoke(["xdotool", "key", "--clearmodifiers", *a.keys])
else:
    path = ROOT / "account.private.json"
    if path.stat().st_mode & 0o777 != 0o600:
        raise SystemExit("私密账号文件必须为0600。")
    value = json.loads(path.read_text())[a.field]
    if not isinstance(value, str) or not value or any(ord(c) < 32 for c in value):
        raise SystemExit("私密字段格式无效。")
    invoke(["xdotool", "type", "--clearmodifiers", "--delay", "60", "--file", "-"], value.encode())
    print(json.dumps({"typed_field": a.field, "value_logged": False}))
