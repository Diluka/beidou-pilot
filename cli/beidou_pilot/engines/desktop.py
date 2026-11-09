#!/usr/bin/env python3
"""原版 GUI 所需的短桌面操作与截图；角色控制交给客户端内 Lua。"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal, TypedDict


class HoldAction(TypedDict):
    action: Literal["hold"]
    keys: list[str]
    seconds: float


class PointAction(TypedDict):
    action: Literal["click", "double-click"]
    x: int
    y: int


class WaitAction(TypedDict):
    action: Literal["wait"]
    seconds: float


class DragAction(TypedDict):
    action: Literal["drag"]
    from_x: int
    from_y: int
    to_x: int
    to_y: int


Action = HoldAction | PointAction | WaitAction | DragAction
DesktopActions = list[Action]

CONTAINER_DESKTOP = r'''
import json
from pathlib import Path
import os
import re
import signal
import subprocess
import sys
import time

payload = json.load(sys.stdin)
pressed = []
mouse_down = False
timings = []
game_geometry = None
keyboard_window = None
activation_point = None
keyboard_needs_release = False
release_keys = ["Left", "Right", "Up", "Down", "Alt_L", "Control_L", "Shift_L", "z"]
started = time.monotonic()
cancel_file = Path(payload["cancel_file"]) if payload["cancel_file"] else None
signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))

def cancel_requested():
    return cancel_file is not None and cancel_file.exists()

def sleep_checked(seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until and not cancel_requested():
        time.sleep(min(0.04, max(0, until - time.monotonic())))

def focus_keyboard():
    global keyboard_window, activation_point
    if keyboard_window is None:
        tree = subprocess.check_output(["xwininfo", "-root", "-tree"], text=True)
        windows = [match for line in tree.splitlines() if (match := re.match(
            r'^(\s*)(0x[0-9a-f]+)\s+.*?\s+(\d+)x(\d+)[+-]\d+[+-]\d+\s+([+-]\d+)([+-]\d+)\s*$', line))]
        game_windows = [window for window in windows if '("beidou.exe" "beidou.exe")' in window[0]
                        and int(window[3]) > 1 and int(window[4]) > 1]
        if len(game_windows) != 1:
            raise RuntimeError("未能唯一确认北斗游戏顶层窗口，未发送键盘输入。")
        outer = game_windows[0]
        keyboard_window = outer[2]
        stats = subprocess.check_output(["xwininfo", "-id", keyboard_window], text=True)
        if "Map State: IsViewable" not in stats:
            raise RuntimeError("北斗游戏顶层窗口当前不可见，未发送键盘输入。")
        children = []
        for child in windows[windows.index(outer) + 1:]:
            if len(child[1]) <= len(outer[1]):
                break
            if int(child[3]) > 1 and int(child[4]) > 1:
                children.append(child)
        if not children:
            raise RuntimeError("未找到北斗内容子窗口，不能安全定位标题栏。")
        content = max(children, key=lambda child: int(child[3]) * int(child[4]))
        outer_x, outer_y, width = int(outer[5]), int(outer[6]), int(outer[3])
        content_y = int(content[6])
        if content_y <= outer_y:
            raise RuntimeError("未找到可安全单击的标题栏区域。")
        points = [outer_x + width * 2 // 5, outer_x + width * 3 // 5]
        state_path = Path("/work/runs") / os.environ["RUN_ID"] / "keyboard-activation.json"
        previous = json.loads(state_path.read_text()) if state_path.exists() else None
        x = max(points, key=lambda point: abs(point - previous["x"])) if previous else points[0]
        activation_point = {"x": x, "y": (outer_y + content_y) // 2}
        subprocess.run(["xdotool", "mousemove", str(activation_point["x"]), str(activation_point["y"]),
                        "click", "1"], check=True)
        state_path.write_text(json.dumps(activation_point))
        time.sleep(0.06)
    subprocess.run(["xdotool", "windowfocus", keyboard_window], check=True)
    time.sleep(0.04)

def focus_and_release():
    focus_keyboard()
    subprocess.run(["xdotool", "keyup", "--delay", "0", *release_keys], check=True)

def execute(action):
    global pressed, mouse_down, keyboard_needs_release
    step_started = time.monotonic()
    kind = action["action"]
    if kind == "hold":
        if keyboard_window is None:
            focus_and_release()
        keyboard_needs_release = True
        if cancel_requested():
            return {"action": kind, "requested_seconds": action["seconds"], "held_seconds": 0}
        pressed = list(action["keys"])
        subprocess.run(["xdotool", "windowfocus", keyboard_window, "keydown", "--delay", "0", *pressed], check=True)
        held_since = time.monotonic()
        sleep_checked(action["seconds"])
        subprocess.run(["xdotool", "windowfocus", keyboard_window, "keyup", "--delay", "0", *reversed(pressed)], check=True)
        pressed = []
        held_seconds = round(time.monotonic() - held_since, 4)
        time.sleep(0.04)
        return {"action": kind, "requested_seconds": action["seconds"],
                "held_seconds": held_seconds}
    if kind == "wait":
        sleep_checked(action["seconds"])
    elif kind == "drag":
        command = ["xdotool", "mousemove", str(action["from_x"]), str(action["from_y"]),
                   "sleep", "0.12", "mousedown", "1", "sleep", "0.15"]
        for step in range(1, 5):
            x = round(action["from_x"] + (action["to_x"] - action["from_x"]) * step / 4)
            y = round(action["from_y"] + (action["to_y"] - action["from_y"]) * step / 4)
            command += ["sleep", "0.08", "mousemove", str(x), str(y)]
        mouse_down = True
        # 原生CWndMan在下一次左键按下时落下物品，mouseup只结束X11按住状态。
        subprocess.run([*command, "sleep", "0.12", "mouseup", "1",
                        "sleep", "0.12", "click", "1"], check=True)
        mouse_down = False
    else:
        command = ["xdotool", "mousemove", str(action["x"]), str(action["y"]), "click"]
        if kind == "double-click":
            command += ["--repeat", "2", "--delay", "100"]
        subprocess.run([*command, "1"], check=True)
    return {"action": kind, "elapsed_seconds": round(time.monotonic() - step_started, 4)}

try:
    for action in payload["actions"]:
        if cancel_requested():
            break
        timings.append(execute(action))
    if keyboard_needs_release:
        focus_and_release()
        keyboard_needs_release = False
    if payload["screenshot"]:
        subprocess.run(["import", "-window", "root", payload["screenshot"]], check=True)
        if payload["game_crop"]:
            tree = subprocess.check_output(["xwininfo", "-root", "-tree"], text=True)
            outer_indent = None
            outer_count = 0
            children = []
            for line in tree.splitlines():
                window = re.match(r"^(\s*)(0x[0-9a-f]+)\s+.*?\s+(\d+)x(\d+)[+-]\d+[+-]\d+\s+([+-]\d+)([+-]\d+)\s*$", line)
                if not window:
                    continue
                indent = len(window[1])
                if outer_indent is not None and indent <= outer_indent:
                    outer_indent = None
                width, height, x, y = map(int, window.group(3, 4, 5, 6))
                if '("beidou.exe" "beidou.exe")' in line and width > 1 and height > 1:
                    outer_count += 1
                    outer_indent = indent
                elif outer_indent is not None and width > 1 and height > 1:
                    children.append({"window": window[2], "x": x, "y": y,
                                     "width": width, "height": height})
            if outer_count != 1 or not children:
                raise RuntimeError("未能唯一确认北斗游戏内容窗口；原始桌面截图已保留。")
            game_geometry = max(children, key=lambda child: child["width"] * child["height"])
            geometry = "{width}x{height}{x:+d}{y:+d}".format(**game_geometry)
            subprocess.run(["convert", payload["screenshot"], "-crop", geometry,
                            "+repage", payload["game_crop"]], check=True)
finally:
    release_failures = []
    for key in reversed(pressed[:]):
        released = subprocess.run(["xdotool", "keyup", "--delay", "0", key], capture_output=True, text=True)
        if released.returncode:
            release_failures.append({"key": key, "reason": released.stderr.strip()})
        else:
            pressed.remove(key)
    if mouse_down:
        subprocess.run(["xdotool", "mouseup", "1"], check=True)
    if keyboard_needs_release:
        focus_and_release()
    if release_failures:
        raise RuntimeError("desktop_key_release_unconfirmed:" + json.dumps(release_failures))
print(json.dumps({"elapsed_seconds": round(time.monotonic() - started, 4), "timings": timings,
                  "game_geometry": game_geometry, "keyboard_window": keyboard_window,
                  "activation_point": activation_point, "cancelled": cancel_requested()}))
'''


def parse_actions(raw: object, parser: argparse.ArgumentParser) -> DesktopActions:
    """在内部桌面引擎的 JSON 边界校验有界 UI 原语。"""
    if not isinstance(raw, list) or not 1 <= len(raw) <= 16:
        parser.error("桌面操作须为含1至16项的短UI动作数组。")
    actions: DesktopActions = []
    duration = 0.0
    aliases = {"Ctrl": "Control_L", "Control": "Control_L", "Alt": "Alt_L", "Shift": "Shift_L"}
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            parser.error(f"第{index}项桌面动作须为JSON对象。")
        kind = item.get("action")
        if kind == "hold":
            if set(item) != {"action", "keys", "seconds"}:
                parser.error(f"第{index}项hold须且仅含action、keys、seconds。")
            keys, seconds = item["keys"], item["seconds"]
            if not isinstance(keys, list) or not keys or not all(
                    isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_]+", key) for key in keys):
                parser.error(f"第{index}项keys须为非空的xdotool键名数组。")
            if type(seconds) not in (int, float) or not 0.05 <= seconds <= 0.5:
                parser.error(f"第{index}项UI按键时间须为0.05至0.5秒；持续控制使用Lua。")
            actions.append({"action": "hold", "keys": list(dict.fromkeys(aliases.get(key, key) for key in keys)),
                            "seconds": float(seconds)})
            duration += seconds + 0.04
        elif kind in ("click", "double-click"):
            if set(item) != {"action", "x", "y"} or any(type(item.get(axis)) is not int for axis in ("x", "y")):
                parser.error(f"第{index}项点击须且仅含action及整数x、y。")
            if not 0 <= item["x"] < 1920 or not 0 <= item["y"] < 1080:
                parser.error(f"第{index}项点击坐标须在1920×1080桌面内。")
            actions.append({"action": kind, "x": item["x"], "y": item["y"]})
            duration += 0.2 if kind == "double-click" else 0.012
        elif kind == "wait":
            if set(item) != {"action", "seconds"} or type(item.get("seconds")) not in (int, float) or not 0 <= item["seconds"] <= 1:
                parser.error(f"第{index}项UI等待须为0至1秒。")
            actions.append({"action": "wait", "seconds": float(item["seconds"])})
            duration += item["seconds"]
        elif kind == "drag":
            fields = ("from_x", "from_y", "to_x", "to_y")
            if set(item) != {"action", *fields} or any(type(item.get(field)) is not int for field in fields):
                parser.error(f"第{index}项拖动须含action及四个整数坐标。")
            if not (0 <= item["from_x"] < 1920 and 0 <= item["to_x"] < 1920
                    and 0 <= item["from_y"] < 1080 and 0 <= item["to_y"] < 1080):
                parser.error(f"第{index}项拖动坐标须在1920×1080桌面内。")
            actions.append({"action": "drag", "from_x": item["from_x"], "from_y": item["from_y"],
                            "to_x": item["to_x"], "to_y": item["to_y"]})
            duration += 0.83
        else:
            parser.error(f"第{index}项不是桌面UI原语；循环与角色控制使用Lua脚本。")
    if duration > 5:
        parser.error("单次桌面UI操作合计不能超过5秒；持续控制使用Lua脚本。")
    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    execute = commands.add_parser("execute", help="内部GUI短线性操作，从stdin读取JSON")
    execute.add_argument("--cancel-file", help="本轮run目录内的取消标记名")
    screenshot = commands.add_parser("screenshot", help="只读当前画面")
    screenshot.add_argument("name")
    screenshot.add_argument("--game-crop", action="store_true")
    scroll = commands.add_parser("scroll", help="当前已定位GUI控件滚轮")
    scroll.add_argument("direction", choices=["up", "down"])
    scroll.add_argument("--ticks", type=int, default=1)
    args = parser.parse_args()
    root = Path(os.environ.get("CLIENT_ROOT", Path(__file__).resolve().parents[2])).resolve()
    if not (root / "clientctl.py").is_file():
        parser.error("CLIENT_ROOT须指向客户端运行目录。")
    actions: DesktopActions = []
    if args.action == "execute":
        try:
            actions = parse_actions(json.load(sys.stdin), parser)
        except json.JSONDecodeError as error:
            parser.error(f"桌面操作JSON无效：{error.msg}。")
    if args.action == "scroll" and not 1 <= args.ticks <= 40:
        parser.error("每次滚动须为1至40格。")
    cancel_name = args.cancel_file if args.action == "execute" else None
    if cancel_name and not re.fullmatch(r"[A-Za-z0-9_-]+", cancel_name):
        parser.error("取消标记名只允许字母、数字、短横线和下划线。")
    ids = subprocess.check_output([
        "docker", "ps", "-q", "--filter", "label=beidou.task=client-v17-maintained",
        "--filter", "label=beidou.client.root=" + str(root),
    ], text=True).split()
    if len(ids) != 1:
        raise SystemExit("本目录必须恰有一个运行中的客户端，未发送桌面输入。")
    container = json.loads(subprocess.check_output(["docker", "inspect", ids[0]], text=True))[0]
    config = container["HostConfig"]
    if config["Privileged"] or config["PortBindings"] or config["NetworkMode"] == "host":
        raise SystemExit("客户端容器边界不符合约定，未发送桌面输入。")
    if args.action == "scroll":
        subprocess.run(["docker", "exec", "--user", "1000:1000", container["Id"], "env", "DISPLAY=:97",
                        "xdotool", "click", "--repeat", str(args.ticks), "--delay", "50",
                        "4" if args.direction == "up" else "5"], capture_output=True, check=True)
        print(json.dumps({"action": "scroll", "input_dispatched": True, "secret_logged": False}))
        return
    env = dict(value.split("=", 1) for value in container["Config"]["Env"])
    target = None
    crop_target = None
    screenshot_path = None
    crop = None
    if args.action == "screenshot":
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
            parser.error("截图名只允许字母、数字、短横线和下划线。")
        target = root / "runtime/runs" / env["RUN_ID"] / (args.name + ".png")
        if target.exists():
            raise SystemExit("截图已存在，拒绝覆盖。")
        screenshot_path = "/work/runs/" + env["RUN_ID"] + "/" + target.name
        if args.game_crop:
            crop_target = target.with_name(target.stem + "-game.png")
            if crop_target.exists():
                raise SystemExit("游戏裁剪图已存在，拒绝覆盖。")
            crop = "/work/runs/" + env["RUN_ID"] + "/" + crop_target.name
    payload = json.dumps({"actions": actions, "screenshot": screenshot_path, "game_crop": crop,
                          "cancel_file": "/work/runs/" + env["RUN_ID"] + "/" + cancel_name if cancel_name else None}).encode()
    result = subprocess.run([
        "docker", "exec", "-i", "--user", "1000:1000", container["Id"], "env", "DISPLAY=:97",
        "python3", "-c", CONTAINER_DESKTOP,
    ], input=payload, capture_output=True, check=True)
    report = json.loads(result.stdout)
    report.update({"action": args.action, "input_dispatched": bool(actions), "secret_logged": False,
                   "screenshot": str(target) if target else None,
                   "game_screenshot": str(crop_target) if crop_target else None})
    print(json.dumps(report))


if __name__ == "__main__":
    main()
