"""单一客户端入口，原生桥承接已验证的游戏动作。"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
from typing import Iterator, cast

from .backend import Backend, ClientError, JsonObject, JsonValue
from .catalog import Catalog
from . import dialogs
from .rules import advancement
from .snapshot import collect, format_snapshot
from . import __version__


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ClientError("usage", message)


def parser() -> Parser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="单个JSON结果；仅独立watch使用JSONL"
    )
    common.add_argument("--root", type=Path, default=argparse.SUPPRESS, help="客户端目录，默认入口所在目录")
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help="保留引擎原始来源和布局细节")
    common.add_argument(
        "--backend",
        choices=["beidou", "headless"],
        default=argparse.SUPPRESS,
        help="明确选择北斗原版或开源无头客户端，默认beidou",
    )
    common.add_argument(
        "--instance", default=argparse.SUPPRESS, help="无头实例名，默认default；每个实例拥有独立控制与运行目录"
    )
    p = Parser(prog="beidou-pilot", description="北斗客户端：登录、状态观察、Lua脚本与游戏操作。", parents=[common])
    p.add_argument("--version", action="version", version="beidou-pilot " + __version__)
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    command("status", "当前客户端阶段与角色，不启动、不输入")
    command("instances", "列出本目录已登记的无头实例，不启动客户端")
    command("capabilities", "读取原生动作能力与静态观察支持范围，不启动客户端")
    command("doctor", "检查本地运行条件与读取能力，不启动客户端")
    q = command("bridge", "读取原生桥状态，或停止桥持有的按键")
    q.add_argument("action", choices=["status", "stop"], nargs="?", default="status")
    q = command("script", "在客户端内运行Lua控制脚本，或只读当前脚本状态")
    q.add_argument("action", choices=["run", "status"])
    source = q.add_mutually_exclusive_group()
    source.add_argument("file", type=Path, nargs="?", help="受信UTF-8 Lua文件")
    source.add_argument("--code", help="直接执行受信Lua源码，与文件输入互斥")
    duration = q.add_mutually_exclusive_group()
    duration.add_argument("--seconds", type=float, default=30, help="客户端内脚本时限，默认30秒")
    duration.add_argument("--continuous", action="store_true", help="明确持续执行，Ctrl+C取消并等待放键")
    q = command("task", "向活动Lua会话新增、替换或停止独立任务，或查询管理结果")
    q.add_argument("action", choices=["add", "replace", "stop", "result"])
    q.add_argument("name", help="任务名称；result操作填写管理request_id")
    source = q.add_mutually_exclusive_group()
    source.add_argument("file", type=Path, nargs="?", help="任务主体的UTF-8 Lua文件")
    source.add_argument("--code", help="任务主体的直接Lua源码")
    q.add_argument("--session", help="script status中的script.id")
    q.add_argument("--revision", type=int, help="替换或停止的预期任务revision")
    q.add_argument("--priority", type=int, help="新增或替换任务的优先级")
    q.add_argument("--timeout", type=float, default=3, help="管理结果等待秒数，不改变会话期限")
    q = command("skill", "通过Lua调用原版原生技能入口，仅报告原始调用结果")
    q.add_argument("id", type=int)
    q = command("open", "启动并正常登录入图；已就绪时自动复用")
    q.add_argument("--channel", type=int, help="新会话默认CH1；复用游戏中会话时默认保留当前频道")
    character = q.add_mutually_exclusive_group()
    character.add_argument("--character")
    character.add_argument("--character-index", type=int)
    q.add_argument("--target", type=Path)
    q.add_argument("--profile", type=Path, help="无头端已有账号/角色的0600私密运行配置")
    q.add_argument("--workspace-server", action="store_true", help="显式使用已授权的工作区服务")
    q.add_argument("--project", default="beidou-ms")
    q.add_argument("--service", default="beidou-server-all")
    q.add_argument("--timeout", type=float, default=90)
    command("close", "正常结束本目录客户端并核验释放")
    q = command("walk", "原生语义移动；方向与有界时间")
    q.add_argument("direction", choices=["left", "right", "up", "down"])
    q.add_argument("--seconds", type=float, default=0.3)
    q = command("face", "原生朝向动作，允许伴随少量位置变化")
    q.add_argument("direction", choices=["left", "right"])
    command("jump", "尝试一次原生跳跃")
    command("attack", "尝试一次普通攻击，命中另行确认")
    command("pickup", "尝试近距离拾取，库存与金币结果另行确认")
    q = command("use_item", "按物品ID尝试原生使用；按客户端能力准入")
    q.add_argument("id", type=int)
    command("stop", "释放当前客户端遗留控制；活动命令用Ctrl+C取消")
    command("revive", "请求一次本端正常复活并核对恢复；存活时跳过")
    q = command("snapshot", "场景、角色、对话与可操作引用")
    q.add_argument("--all", action="store_true", help="含画外实体")
    q.add_argument("-i", "--interactive", action="store_true", help="简洁列出NPC/对话/掉落")
    q = command("watch", "持续只读角色变化，输出JSONL")
    q.add_argument("--seconds", type=float, default=10)
    q.add_argument("--interval", type=float, default=0.5)
    q = command("inspect", "按需读取一个领域或静态资源")
    q.add_argument(
        "kind", choices=["scene", "inventory", "quests", "skills", "stage", "ui", "item", "npc", "monster", "map"]
    )
    q.add_argument("id", nargs="?", type=int)
    q = command("talk", "按当前NPC名称、模板ID或引用打开对话")
    q.add_argument("target")
    q = command("click", "激活当前控件引用；GUI另可点击根桌面坐标")
    q.add_argument("target", help="当前控件引用；GUI也接受既有引用或x坐标")
    q.add_argument("y", nargs="?", type=int, help="仅GUI坐标点击")
    q.add_argument("--double", action="store_true", help="仅GUI桌面双击")
    q = command("dialog", "读当前对话、选文字、下一页或确认")
    q.add_argument(
        "action",
        nargs="?",
        default="read",
        choices=["read", "select", "next", "confirm", "yes", "no", "back", "end", "advance"],
    )
    q.add_argument("selector", nargs="?")
    q.add_argument("--accept", action="store_true", help="advance遇Yes/No时明确接受")
    q.add_argument("--seconds", type=float, default=20)
    q = command("batch", "从JSON文件或stdin执行一组CLI命令，任一步失败立即停止")
    q.add_argument("--file", type=Path)
    q = command("key", "通过Lua按住并释放原版客户端按键")
    q.add_argument("keys", nargs="+")
    q.add_argument("--seconds", type=float, default=0.15, help="单次按住0.05～30秒，结束后释放")
    q = command("move", "客户端内Lua按实际坐标在当前层水平移动")
    q.add_argument("x", type=int)
    q.add_argument("--seconds", type=float, default=20)
    q.add_argument("--tolerance", type=int, default=8)
    q = command("climb", "对齐绳梯并爬到指定世界y")
    q.add_argument("x", type=int)
    q.add_argument("--to-y", type=int, required=True)
    q.add_argument("--seconds", type=float, default=20)
    q = command("portal", "按当前地图门户名正常靠近并进入")
    q.add_argument("name")
    q.add_argument("--seconds", type=float, default=20)
    q = command("ui", "读取/打开/关闭已识别窗口，或恢复场景焦点")
    q.add_argument("action", choices=["read", "open", "close", "focus"], default="read", nargs="?")
    q.add_argument("window", nargs="?", choices=["inventory", "stats", "skills", "shop", "all"])
    q = command("equip", "装备背包中的物品，并核对身上负槽")
    q.add_argument("item")
    q.add_argument("--slot", type=int, help="无头：明确装备背包源正槽")
    q.add_argument("--to-slot", type=int, help="无头：明确身上目的负槽")
    q.add_argument("--seconds", type=float, default=3, help="无头换装确认期限，默认3秒")
    q = command("unequip", "无头正常卸下指定身上装备到空背包槽，并核对结果")
    q.add_argument("--slot", type=int, required=True, help="身上源负槽")
    q.add_argument("--to-slot", type=int, required=True, help="装备背包目的正槽，必须为空")
    q.add_argument("--seconds", type=float, default=3, help="换装确认期限，默认3秒")
    q = command("use", "正常使用消费品，核对数量与实际恢复")
    q.add_argument("item")
    q.add_argument("--count", type=int, default=1)
    q.add_argument("--until-hp", type=int)
    q.add_argument("--until-mp", type=int)
    q.add_argument("--seconds", type=float)
    q = command("stats", "正常UI分配AP")
    q.add_argument("stat", choices=["str", "dex", "int", "luk"])
    q.add_argument("count", type=int)
    q = command("skills", "正常UI给指定技能加点")
    q.add_argument("skill", type=int)
    q.add_argument("count", type=int, nargs="?", default=1)
    command("hotkeys", "读取客户端当前键位及快捷栏映射")
    q = command("bind", "正常拖动技能或物品到指定快捷键，并核对映射")
    q.add_argument("kind", choices=["item", "skill"])
    q.add_argument("id", type=int)
    q.add_argument("key")
    q = command("press", "按当前绑定的物品或技能键，不臆测命中")
    q.add_argument("kind", choices=["item", "skill"])
    q.add_argument("id", type=int)
    q = command("shop", "读取当前普通商店商品，并执行已指定的买卖")
    q.add_argument("action", choices=["read", "buy", "sell", "close"], default="read", nargs="?")
    q.add_argument("item", nargs="?", type=int)
    q.add_argument("--count", type=int, default=1)
    q.add_argument("--slot", type=int)
    q = command("fight", "客户端内Lua策略：接近、攻击、补给、停级并退回锚点")
    q.add_argument("mob", help="当前地图怪物名或模板ID")
    q.add_argument("--seconds", type=float, default=60)
    q.add_argument("--until-level", type=int)
    q.add_argument("--floor-y", type=int)
    q.add_argument("--bounds", type=int, nargs=2, metavar=("MIN", "MAX"))
    q.add_argument("--retreat-x", type=int)
    q.add_argument("--loot", action="store_true", help="启用同层落地物品定向拾取")
    q = command("screenshot", "保存原图及游戏裁剪，不直接向会话加载图片")
    q.add_argument("name", nargs="?")
    q = command("record", "有界采集当前游戏画面与逐帧时间戳，不发送输入")
    q.add_argument("name")
    q.add_argument("--seconds", type=float, default=10)
    q.add_argument("--fps", type=int, default=10)
    return p


@contextmanager
def control(backend: Backend, name: str) -> Iterator[None]:
    backend.paths.state_directory.mkdir(parents=True, exist_ok=True)
    lifecycle = backend.name == "headless" and name in {"open", "close"}
    path = backend.paths.state_directory / "container.lock" if lifecycle else backend.paths.input_lock
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            if lifecycle:
                raise ClientError("lifecycle_busy", "另一个命令正在启动或关闭该客户端容器。") from error
            raise ClientError("input_busy", "另一个beidou-pilot命令正在控制客户端；只读命令仍可使用。") from error
        handle.seek(0)
        handle.truncate()
        json.dump({"pid": os.getpid(), "command": name}, handle)
        handle.flush()
        previous_handler = signal.signal(signal.SIGTERM, signal.default_int_handler)
        try:
            yield
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
            fcntl.flock(handle, fcntl.LOCK_UN)


def status(backend: Backend) -> JsonObject:
    if backend.name == "headless":
        from .headless import status as native_status

        return native_status(backend.root, backend.instance)
    stage = backend.read("stage")
    result: JsonObject = {
        "stage": stage["stage"],
        "running": stage["running"],
        "channel": stage.get("channel"),
        "character": stage.get("character"),
        "unavailable": stage.get("unavailable", []),
    }
    if stage["stage"] == "IN_GAME":
        state = backend.read("observe")
        result.update(
            character=state["character"],
            position=state["position"],
            map_id=state["map_id"],
            advancement=advancement(cast(JsonObject, state["character"])),
        )
    return result


def resolve_item(backend: Backend, selector: str) -> int:
    if selector.isdecimal():
        return int(selector)
    state = collect(backend, all_entities=True)
    if selector.startswith("@"):
        target = cast(JsonObject, cast(JsonObject, state["refs"]).get(selector))
        if not target or target["kind"] != "item":
            raise ClientError("stale_reference", "物品引用已失效，请重新 snapshot。", {"ref": selector})
    else:
        target = dialogs.choose(cast(list[JsonObject], state["inventory"]), selector, "name")
    return cast(int, target["item_id"])


def floor_bounds(metadata: JsonObject, x: int, y: int) -> list[int] | None:
    segments = cast(list[JsonObject], metadata["footholds"])
    flat = [
        f
        for f in segments
        if abs(cast(int, f["y1"]) - y) <= 35 and abs(cast(int, f["y2"]) - y) <= 35 and f["x1"] != f["x2"]
    ]
    connected = [
        f
        for f in flat
        if min(cast(int, f["x1"]), cast(int, f["x2"])) <= x <= max(cast(int, f["x1"]), cast(int, f["x2"]))
    ]
    if not connected:
        return None
    low = min(min(cast(int, f["x1"]), cast(int, f["x2"])) for f in connected)
    high = max(max(cast(int, f["x1"]), cast(int, f["x2"])) for f in connected)
    changed = True
    while changed:
        changed = False
        for f in flat:
            a, b = sorted((cast(int, f["x1"]), cast(int, f["x2"])))
            if a <= high and b >= low and (a < low or b > high):
                low, high, changed = min(low, a), max(high, b), True
    return [low + 5, high - 5]


def dispatch(backend: Backend, args: argparse.Namespace) -> JsonObject | None:
    cmd = args.command
    if backend.name == "headless" and cmd not in {
        "status",
        "instances",
        "capabilities",
        "doctor",
        "bridge",
        "script",
        "task",
        "skill",
        "open",
        "close",
        "snapshot",
        "watch",
        "inspect",
        "click",
        "walk",
        "face",
        "jump",
        "attack",
        "pickup",
        "use_item",
        "revive",
        "stop",
        "move",
        "climb",
        "portal",
        "fight",
        "batch",
        "use",
        "equip",
        "unequip",
    }:
        raise ClientError("unsupported_capability", "该客户端尚未提供这个窗口、原始按键或玩法接口。", {"command": cmd})
    if cmd == "status":
        return status(backend)
    if cmd == "instances":
        from .headless import list_instances

        return {"instances": list_instances(backend.root)}
    if cmd == "capabilities":
        from .bridge import BridgeClient
        from .observations import DOMAINS

        try:
            state = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
        except ClientError as error:
            if error.code not in {
                "bridge_unavailable",
                "bridge_session_unavailable",
                "stale_bridge_state",
                "bridge_session_mismatch",
            }:
                raise
            state = None
        domains = (
            DOMAINS - {"interaction"} if backend.name == "beidou" else DOMAINS - {"hotkeys", "dialog", "ui", "shop"}
        )
        return {
            "connected": state is not None,
            "ready": state["ready"] if state is not None else False,
            "observation_domains": sorted(domains),
            "native_actions": cast(JsonObject | None, state.get("capabilities")) if state is not None else None,
        }
    if cmd == "doctor":
        if backend.name == "headless":
            from .headless import docker

            return {
                "backend": "headless",
                "root": str(backend.root),
                "image": docker(
                    "image",
                    "inspect",
                    os.environ.get("HEADLESS_CLIENT_IMAGE", "local/beidou-pilot:local"),
                    "--format",
                    "{{.Id}}",
                ).strip(),
                "state": status(backend),
            }
        return {
            "root": str(backend.root),
            "check": json.loads(backend.text("clientctl", "check")),
            "stage": backend.read("stage"),
        }
    if cmd == "bridge":
        from .bridge import BridgeClient

        bridge = BridgeClient(backend.root, backend.name, backend.instance)
        return cast(JsonObject, bridge.stop() if args.action == "stop" else bridge.snapshot())
    if cmd == "skill":
        from .control_scripts import skill

        return skill(backend, args.id)
    if cmd == "script":
        from .bridge import BridgeClient

        bridge = BridgeClient(backend.root, backend.name, backend.instance)
        if args.action == "status":
            if args.file is not None or args.code is not None:
                raise ClientError("usage", "script status不接收脚本文件或源码。")
            state = bridge.snapshot()
            return {
                "source": "client-native-bridge",
                "supported": "script" in state,
                "instance_id": state["instance_id"],
                "script": cast(JsonObject | None, state.get("script")),
                "command": cast(JsonObject, state["command"]),
                "held_keys": state["held_keys"],
            }
        if args.file is None and args.code is None:
            raise ClientError("usage", "script run需要UTF-8本地Lua文件或--code源码。")
        return bridge.run_script(args.file, seconds=None if args.continuous else args.seconds, code=args.code)
    if cmd == "task":
        from .task_management import change_task, task_result

        if args.action == "result":
            if any(value is not None for value in (args.file, args.code, args.session, args.revision, args.priority)):
                raise ClientError("usage", "task result只接收管理request_id与公共选项。")
            return task_result(backend, args.name)
        if args.session is None:
            raise ClientError("usage", "任务管理需要--session明确目标script.id。")
        if args.action in {"add", "replace"}:
            if args.file is None and args.code is None or args.priority is None:
                raise ClientError("usage", "新增或替换任务需要Lua文件或--code，以及--priority。")
        elif args.file is not None or args.code is not None or args.priority is not None:
            raise ClientError("usage", "task stop不接收源码或优先级。")
        if (
            args.action == "add"
            and args.revision is not None
            or args.action in {"replace", "stop"}
            and args.revision is None
        ):
            raise ClientError("usage", "新增任务不接收--revision；替换或停止需要预期--revision。")
        return change_task(
            backend,
            args.action,
            args.name,
            script_id=args.session,
            expected_revision=args.revision,
            priority=args.priority or 0,
            path=args.file,
            code=args.code,
            timeout=args.timeout,
        )
    if cmd == "open":
        from .headless import any_running as headless_running

        if backend.name == "headless":
            if args.character is not None or args.character_index is not None or args.channel is not None:
                raise ClientError("unsupported_capability", "无头端选角和频道由私密profile声明；不使用GUI选角参数。")
            from .headless import open_game as open_native

            return open_native(
                backend.root,
                target=args.target,
                profile=args.profile,
                timeout=args.timeout,
                workspace_server=args.workspace_server,
                instance=backend.instance,
            )
        if headless_running(backend.root):
            raise ClientError("client_already_running", "无头客户端仍在运行；先正常关闭再切换客户端。")
        from .session import open_game

        channel = args.channel
        if channel is None:
            current = backend.read("stage")
            channel = current.get("channel") if current["stage"] == "IN_GAME" else 1
            if channel is None:
                raise ClientError("channel_unavailable", "现有游戏频道尚未确认，请重新 status。")
        opened = open_game(
            backend,
            channel=channel,
            character=args.character,
            character_index=args.character_index,
            target=args.target,
            project=args.project,
            service=args.service,
            timeout=args.timeout,
        )
        character = cast(JsonObject, opened["character"])
        opened["playable"] = cast(int, character["hp"]) > 0
        if not opened["playable"]:
            opened["next_action"] = "revive"
        return opened
    if cmd == "close":
        if backend.name == "headless":
            from .headless import close_game as close_native

            return close_native(backend.root, backend.instance)
        from .session import close_game

        return close_game(backend)
    if cmd in {"walk", "face", "jump", "attack", "pickup", "use_item"}:
        from .control_scripts import action

        return action(
            backend,
            "move" if cmd == "walk" else cmd,
            direction=getattr(args, "direction", None),
            seconds=getattr(args, "seconds", 0.3),
            item_id=getattr(args, "id", None),
        )
    if cmd == "stop":
        from .bridge import BridgeClient

        return BridgeClient(backend.root, backend.name, backend.instance).stop()
    if cmd == "revive":
        from .recovery import revive

        return revive(backend)
    if cmd == "snapshot":
        return collect(backend, all_entities=args.all, debug=getattr(args, "debug", False))
    if cmd == "watch":
        report = backend.stream(
            "observe",
            ["--watch", "--seconds", str(args.seconds), "--interval", str(args.interval)],
            stdout=not getattr(args, "_batch", False),
        )
        return {"state": report} if getattr(args, "_batch", False) else None
    if cmd == "inspect":
        kind = args.kind
        if kind in ("item", "npc", "monster", "map"):
            identifier = args.id
            if identifier is None and kind == "map":
                identifier = backend.read("observe")["map_id"]
            if identifier is None:
                raise ClientError("usage", "资源检查需要ID。")
            return getattr(Catalog(backend.root), kind)(identifier)
        engine = "character" if kind == "skills" else kind
        values = (
            ["--type", "1", "--type", "2", "--type", "3", "--type", "4", "--type", "5", "--equipped"]
            if kind == "inventory"
            else []
        )
        if args.id is not None and kind == "quests":
            values += ["--quest-id", str(args.id)]
        return backend.read(engine, *values)
    if cmd == "talk":
        return dialogs.talk(backend, args.target)
    if cmd == "dialog":
        if args.action == "read":
            return backend.read("dialog")
        if args.action == "advance":
            return dialogs.advance(backend, accept=args.accept, seconds=args.seconds)
        if args.action == "select" and args.selector is None:
            raise ClientError("usage", "dialog select需要文字、索引或当前引用。")
        return dialogs.act(backend, args.action, args.selector)
    if cmd == "click":
        if backend.name == "headless":
            if args.y is not None or args.double:
                raise ClientError("unsupported_capability", "无头端只激活当前原生控件引用，不提供桌面坐标或双击。")
            from .control_scripts import _lua_literal, run_source

            report = run_source(backend, "game.activate(" + _lua_literal(args.target) + ")\n", 3)
            state = cast(JsonObject, report["last_state"])
            return {**report, "action": "activate", "action_result": state["action_result"]}
        if args.y is not None:
            return backend.desktop(
                [{"action": "double-click" if args.double else "click", "x": int(args.target), "y": args.y}]
            )
        snapshot = collect(backend, all_entities=True)
        target = cast(JsonObject | None, cast(JsonObject, snapshot["refs"]).get(args.target))
        if target is None:
            raise ClientError("stale_reference", "引用已失效或不属于当前场景，请重新 snapshot。", {"ref": args.target})
        kind = target["kind"]
        if kind == "npcs":
            return dialogs.talk(backend, args.target)
        if kind == "choice":
            return dialogs.act(backend, "select", args.target)
        if kind == "button":
            return dialogs.act(backend, cast(str, target["action"]))
        if kind == "item":
            from . import items

            if target["inventory_type"] == 1:
                return items.equip(backend, cast(int, target["item_id"]))
            return items.use(backend, cast(int, target["item_id"]))
        raise ClientError("unsupported_click", "这个引用用于观察；请使用对应的战斗或拾取命令。", {"target": target})
    if cmd == "batch":
        raw = json.loads(args.file.read_text()) if args.file else json.load(sys.stdin)
        if not isinstance(raw, list) or not raw:
            raise ClientError("usage", 'batch需要非空JSON命令数组，例如[["status"],["move",100]]。')
        commands = []
        for index, words in enumerate(raw):
            if not isinstance(words, list) or not words or not all(type(v) in (str, int, float) for v in words):
                raise ClientError("usage", "每项命令须为字符串/数字参数数组。", {"index": index})
            parsed = parser().parse_args([str(v) for v in words])
            if parsed.command == "batch":
                raise ClientError("usage", "batch不支持嵌套；持续控制请使用Lua脚本。", {"index": index})
            if (
                getattr(parsed, "root", backend.root).resolve() != backend.root
                or getattr(parsed, "backend", backend.name) != backend.name
                or getattr(parsed, "instance", backend.instance) != backend.instance
            ):
                raise ClientError("usage", "一批命令只控制同一客户端目录、后端和实例。", {"index": index})
            commands.append(parsed)
        completed: list[JsonObject] = []
        for index, parsed in enumerate(commands):
            print(
                json.dumps({"event": "batch_step", "index": index, "command": parsed.command}, ensure_ascii=False),
                file=sys.stderr,
                flush=True,
            )
            parsed._batch = True
            try:
                result = dispatch(backend, parsed)
            except ClientError as error:
                raise ClientError(
                    error.code, error.message, {"index": index, "completed": completed, "cause": error.details}
                ) from error
            completed.append({"command": parsed.command, "result": concise(result) if result is not None else None})
        return {"status": "completed", "steps": completed}
    if cmd == "key":
        from .control_scripts import press_keys

        return press_keys(backend, args.keys, seconds=args.seconds)
    if cmd in ("move", "climb", "portal"):
        if cmd == "move":
            from .control_scripts import move_to_x

            return move_to_x(backend, args.x, seconds=args.seconds, tolerance=args.tolerance)
        from . import travel

        if cmd == "climb":
            return travel.climb(backend, args.x, args.to_y, seconds=args.seconds)
        return travel.portal(backend, args.name, seconds=args.seconds)
    if cmd == "ui":
        from . import ui

        if args.action == "read":
            return backend.read("ui")
        if args.action == "focus":
            return ui.focus_game(backend)
        if args.window is None:
            raise ClientError("usage", "ui open/close需要窗口名。")
        if args.window == "all":
            if args.action != "close":
                raise ClientError("usage", "all仅用于ui close。")
            from .shop import close_shop

            closed_shop = close_shop(backend)
            return {
                "shop": closed_shop,
                "windows": [ui.close_window(backend, w) for w in ("skills", "stats", "inventory")],
            }
        if args.window == "shop":
            if args.action != "close":
                raise ClientError("usage", "商店通过talk商人打开；ui close shop可关闭。")
            from .shop import close_shop

            return close_shop(backend)
        return (ui.open_window if args.action == "open" else ui.close_window)(backend, args.window)
    if cmd == "unequip" or cmd == "equip" and backend.name == "headless":
        from .control_scripts import change_equipment

        if backend.name != "headless":
            raise ClientError("unsupported_capability", "该客户端尚未提供明确槽位的原生卸下操作。")
        if cmd == "equip":
            if args.slot is None or args.to_slot is None:
                raise ClientError("usage", "无头 equip 需要 --slot 明确背包源槽和 --to-slot 明确身上目的槽。")
            if not args.item.isdecimal():
                raise ClientError("usage", "无头 equip 需要数字物品ID，并同时指定实际背包槽。")
        return change_equipment(
            backend,
            args.slot,
            args.to_slot,
            unequip=cmd == "unequip",
            item_id=int(args.item) if cmd == "equip" else None,
            seconds=args.seconds,
        )
    if cmd in ("equip", "use"):
        if cmd == "equip" and (args.slot is not None or args.to_slot is not None or args.seconds != 3):
            raise ClientError(
                "unsupported_capability", "GUI equip 沿用物品选择与窗口流程；明确原生槽位参数仅支持无头端。"
            )
        if backend.name == "headless" and not args.item.isdecimal():
            raise ClientError("unsupported_capability", "无头端use需要数字物品ID。")
        from . import items

        item = resolve_item(backend, args.item)
        if cmd == "equip":
            return items.equip(backend, item)
        return items.use(
            backend, item, count=args.count, until_hp=args.until_hp, until_mp=args.until_mp, seconds=args.seconds
        )
    if cmd in ("stats", "skills"):
        from . import stats

        if args.count < 1:
            raise ClientError("usage", "点数必须为正整数。")
        attributes = {"str": "strength", "dex": "dexterity", "int": "intelligence", "luk": "luck"}
        return (
            stats.allocate_ap(backend, attributes[args.stat], args.count)
            if cmd == "stats"
            else stats.allocate_sp(backend, args.skill, args.count)
        )
    if cmd in ("hotkeys", "bind", "press"):
        from . import hotkeys

        if cmd == "hotkeys":
            return hotkeys.read_hotkeys(backend)
        if cmd == "bind":
            return (hotkeys.bind_item if args.kind == "item" else hotkeys.bind_skill)(backend, args.id, args.key)
        return hotkeys.press_bound(backend, args.kind, args.id)
    if cmd == "shop":
        from . import shop

        if args.action == "read":
            return shop.read_shop(backend)
        if args.action == "close":
            return shop.close_shop(backend)
        if args.item is None:
            raise ClientError("usage", "shop buy/sell需要物品ID。")
        return (
            shop.buy(backend, args.item, args.count)
            if args.action == "buy"
            else shop.sell(backend, args.item, args.count, slot=args.slot)
        )
    if cmd == "fight":
        from .bridge import BridgeClient
        from .control_scripts import fight as lua_fight

        state = BridgeClient(backend.root, backend.name, backend.instance).snapshot()
        if not state["ready"] or state["character"] is None or state["position"] is None:
            raise ClientError("not_ready", "角色状态尚未就绪，未开始战斗。")
        char, pos = state["character"], state["position"]
        if char["hp"] <= 0:
            raise ClientError("dead", "角色已死亡，请先恢复角色。")
        catalog = Catalog(backend.root)
        monsters = state.get("monsters")
        if monsters is None:
            raise ClientError("observation_unavailable", "怪物观察尚不可用。")
        mob_id = int(args.mob) if args.mob.isdecimal() else None
        if mob_id is None:
            matching = {
                m["template_id"]
                for m in monsters
                if m["template_id"] is not None and args.mob in (m.get("name"), catalog.monster_name(m["template_id"]))
            }
            if len(matching) != 1:
                raise ClientError("mob_not_found", "请按当前怪物名称或模板ID指定。", {"name": args.mob})
            mob_id = matching.pop()
        y = args.floor_y if args.floor_y is not None else pos["y"]
        bounds = args.bounds or floor_bounds(catalog.map(state["map_id"]), pos["x"], y)
        if bounds is None:
            raise ClientError("floor_unknown", "请用--bounds明确本次同层战斗范围。")
        milestone = advancement(cast(JsonObject, char))
        if milestone and milestone["due"]:
            raise ClientError("advancement_due", "先完成当前阶段转职，再继续战斗。", milestone)
        stop_level = args.until_level or (cast(int, milestone["level"]) if milestone else char["level"] + 1)
        if milestone:
            stop_level = min(stop_level, cast(int, milestone["level"]))
        return lua_fight(
            backend,
            mob_id=mob_id,
            seconds=args.seconds,
            stop_level=stop_level,
            floor_y=y,
            bounds=(bounds[0], bounds[1]),
            retreat_x=args.retreat_x if args.retreat_x is not None else int(pos["x"]),
            loot=args.loot,
        )
    if cmd == "screenshot":
        name = args.name or datetime.now(timezone.utc).strftime("shot-%Y%m%dT%H%M%S-") + str(os.getpid())
        return backend.read("desktop", "screenshot", name, "--game-crop")
    if cmd == "record":
        report = backend.read("record", args.name, "--seconds", str(args.seconds), "--fps", str(args.fps))
        if report["status"] != "completed":
            raise ClientError("record_incomplete", "画面录制未完整结束，保留已有帧与失败记录。", report)
        return report
    raise ClientError("unknown_command", "未知命令。")


def concise(result: JsonObject) -> JsonObject:
    result = dict(result)
    stage = result.get("stage")
    if isinstance(stage, dict):
        result["stage"] = stage["stage"]
    dialog = result.get("dialog")
    if isinstance(dialog, dict) and "dialog_open" in dialog:
        result["dialog"] = {
            "open": dialog["dialog_open"],
            "npc_id": dialog["npc_id"],
            "type": dialog["dialog_type"],
            "lines": dialog["lines"],
            "choices": [{"id": x["link_id"], "text": x["text"]} for x in cast(list[JsonObject], dialog["choices"])],
            "buttons": [
                dialogs.BUTTONS.get(cast(int, x["control_id"]), str(x["control_id"]))
                for x in cast(list[JsonObject], dialog["buttons"])
            ],
        }
    state = result.get("state")
    if isinstance(state, dict) and "character" in state:
        result["state"] = {
            k: state[k] for k in ("map_id", "position", "character", "observed_at", "observed_at_ms") if k in state
        }
    target = result.get("target")
    if isinstance(target, dict) and "link_id" in target:
        result["target"] = {"id": target["link_id"], "text": target["text"]}
    if "refs" in result:
        del result["refs"]
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    json_output = "--json" in arguments
    try:
        args = parser().parse_args(arguments)
        backend = Backend(
            getattr(args, "root", Path(__file__).resolve().parents[1]),
            getattr(args, "backend", "beidou"),
            getattr(args, "instance", "default"),
        )
        readonly = (
            args.command
            in (
                "status",
                "instances",
                "capabilities",
                "doctor",
                "snapshot",
                "watch",
                "inspect",
                "screenshot",
                "record",
                "hotkeys",
            )
            or (args.command == "bridge" and args.action == "status")
            or (args.command == "script" and args.action == "status")
            or (args.command == "dialog" and args.action == "read")
            or (args.command == "ui" and args.action == "read")
            or (args.command == "shop" and args.action == "read")
        )
        if args.command == "task":
            previous_handler = signal.signal(signal.SIGTERM, signal.default_int_handler)
            try:
                result = dispatch(backend, args)
            finally:
                signal.signal(signal.SIGTERM, previous_handler)
        elif readonly:
            result = dispatch(backend, args)
        else:
            with control(backend, args.command):
                result = dispatch(backend, args)
        if result is not None:
            if args.command == "snapshot" and not json_output and backend.name == "beidou":
                print(format_snapshot(result, interactive_only=args.interactive))
            else:
                data = result if getattr(args, "debug", False) or args.command in ("inspect", "ui") else concise(result)
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "command": args.command,
                            "backend": backend.name,
                            "instance": backend.instance,
                            "data": data,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                )
        return 0
    except ClientError as error:
        print(
            json.dumps(
                {"ok": False, "error": {"code": error.code, "message": error.message, "details": error.details}},
                ensure_ascii=False,
            ),
            file=sys.stdout if json_output else sys.stderr,
        )
        return 130 if error.code == "task_request_interrupted" else 2
    except json.JSONDecodeError as error:
        print(
            json.dumps({"ok": False, "error": {"code": "invalid_json", "message": error.msg}}, ensure_ascii=False),
            file=sys.stdout if json_output else sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        print(
            json.dumps(
                {"ok": False, "error": {"code": "interrupted", "message": "操作已中断，请 snapshot 确认当前场景。"}},
                ensure_ascii=False,
            ),
            file=sys.stdout if json_output else sys.stderr,
        )
        return 130
