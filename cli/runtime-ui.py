#!/usr/bin/env python3
"""操作本容器的 GUI；秘密仅经 stdin 传入。"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

from beidou_pilot.runtime import load_runtime

ROOT = Path(os.environ.get("CLIENT_ROOT", "/work")).resolve()
p = argparse.ArgumentParser(description=__doc__)
sub = p.add_subparsers(dest="action", required=True)
sub.add_parser("windows")
s = sub.add_parser("screenshot"); s.add_argument("name")
s = sub.add_parser("click"); s.add_argument("x", type=int); s.add_argument("y", type=int)
s = sub.add_parser("key"); s.add_argument("keys", nargs="+")
sub.add_parser("type-private")
a = p.parse_args()
runtime = load_runtime(ROOT, "beidou", os.environ.get("MAPLE_INSTANCE", "default"))
if not runtime.running:
    raise SystemExit("本容器客户端已经退出。")
run = runtime.run_dir

def invoke(args, secret=None):
    return subprocess.run(args, input=secret, capture_output=True, check=True,
                          env=dict(os.environ, DISPLAY=":97"))

if a.action == "windows":
    print(invoke(["xwininfo", "-root", "-tree"]).stdout.decode())
elif a.action == "screenshot":
    if not a.name.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("截图名只允许字母、数字、短横线和下划线。")
    target = run / (a.name + ".png")
    if target.exists():
        raise SystemExit("截图已存在，拒绝覆盖。")
    invoke(["import", "-window", "root", str(target)])
    print(target)
elif a.action == "click":
    if not (0 <= a.x < 1920 and 0 <= a.y < 1080):
        raise SystemExit("点击坐标超出桌面范围。")
    invoke(["xdotool", "mousemove", str(a.x), str(a.y), "click", "1"])
elif a.action == "key":
    invoke(["xdotool", "key", "--clearmodifiers", *a.keys])
else:
    invoke(["xdotool", "type", "--clearmodifiers", "--delay", "60", "--file", "-"], sys.stdin.buffer.read())
