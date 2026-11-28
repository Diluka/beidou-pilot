"""单一客户端入口，原生桥承接已验证的游戏动作。"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import sys
from typing import Iterator, cast

from .backend import Backend, ClientError, JsonObject
from .catalog import Catalog
from . import dialogs
from .rules import advancement
from .snapshot import collect, format_snapshot
from .strategies import (
    compile_strategy,
    describe_strategy,
    parse_options,
    override_tick_budget,
    parse_script_execution,
    read_strategy_entry,
    read_strategy_file,
)
from . import __version__


WORKBENCH_SCRIPTS = Path("/work/scripts")


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ClientError("usage", message)


def map_number(text: str) -> int:
    try:
        value = int(text, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("地图号须为正整数。") from error
    if value <= 0:
        raise argparse.ArgumentTypeError("地图号须为正整数。")
    return value


def script_path(text: str) -> Path:
    if not text:
        raise argparse.ArgumentTypeError("须指定 tick Lua 文件或目录脚本包。")
    return WORKBENCH_SCRIPTS / text


def find_script_package_root(path: Path) -> Path | None:
    """Find the nearest Lua module package containing lib/ around a script file."""
    resolved = path.resolve()
    if resolved.is_dir():
        return resolved
    for parent in (resolved.parent, *resolved.parent.parents):
        if parent == Path(parent.anchor):
            break
        library = parent / "lib"
        inside_scripts = parent == WORKBENCH_SCRIPTS or WORKBENCH_SCRIPTS in parent.parents
        if library.is_dir() and (inside_scripts or any(library.rglob("*.lua"))):
            return parent
        if parent == WORKBENCH_SCRIPTS:
            break
    return None


def parser() -> Parser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="单个JSON结果；watch与events watch使用JSONL"
    )
    common.add_argument("--root", type=Path, default=argparse.SUPPRESS, help="本容器运行目录，默认CLIENT_ROOT")
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help="保留引擎原始来源和布局细节")
    common.add_argument("--instance", default=argparse.SUPPRESS, help="核对本容器实例名，默认MAPLE_INSTANCE")
    p = Parser(prog="beidou-pilot", description="北斗客户端：登录、状态观察、tick Lua脚本与GUI操作。", parents=[common])
    p.add_argument("--version", action="version", version="beidou-pilot " + __version__)
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)

    def command(name: str, help_text: str, *, allow_abbrev: bool = True) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common], allow_abbrev=allow_abbrev)

    q = command("login", "观察登录状态，或显式授权 GUI 登录")
    q.add_argument("--timeout", type=float, default=None, help="等待秒数；观察默认一次，GUI 动作默认30秒")
    q.add_argument("--accept-terms", action="store_true", help="按需授权同意协议（GUI）")
    q.add_argument("--gender", choices=["female", "male"], help="显式指定账号性别（GUI）")
    q = command("character", "创建角色或查询既有建角请求")
    actions = q.add_subparsers(dest="character_action", required=True, parser_class=Parser)
    create = actions.add_parser("create", parents=[common], allow_abbrev=False)
    create.add_argument("--name", required=True)
    for option in ("job", "face", "hair", "hair-color", "skin", "top", "bottom", "shoes", "weapon"):
        create.add_argument("--" + option, type=int, required=True)
    create.add_argument("--gender", choices=["male", "female"], required=True)
    create.add_argument("--timeout", type=float, default=None, help="等待秒数；GUI默认90秒")
    result = actions.add_parser("result", parents=[common])
    result.add_argument("request_id")
    result.add_argument("--run-id", required=True, help="提交时的原运行身份")
    result.add_argument("--instance-id", required=True, help="提交时的原生实例身份")
    command("status", "当前客户端阶段与角色，不启动、不输入")
    command("capabilities", "读取原生动作能力与静态观察支持范围，不启动客户端")
    command("_cash-probe", "临时研究探针：只读商城候选对象")
    q = command("world-map", "只读查询原生世界地图的跨图路线，不控制客户端")
    actions = q.add_subparsers(dest="world_map_action", required=True, parser_class=Parser)
    route = actions.add_parser("route", parents=[common], allow_abbrev=False)
    route.add_argument("start", type=map_number, help="起点地图号")
    route.add_argument("goal", type=map_number, help="终点地图号")
    command("doctor", "检查本地运行条件与读取能力，不启动客户端")
    q = command("bridge", "读取原生桥状态，或停止桥持有的按键")
    q.add_argument("action", choices=["status", "stop"], nargs="?", default="status")
    q = command("script", "运行tick Lua脚本，或只读当前脚本状态", allow_abbrev=False)
    q.add_argument("action", choices=["run", "start", "status", "cancel", "describe"])
    q.add_argument("--session", help="cancel必须指定script.id；status可按script.id查询指定会话")
    q.add_argument(
        "file",
        type=script_path,
        nargs="?",
        help="含 main(context) 的 tick Lua 文件或含 main.lua 的包目录；相对路径从 /work/scripts 解析，也接受容器绝对路径",
    )
    q.add_argument("--package-root", type=script_path, help="显式指定 require 模块搜索根目录")
    q.add_argument("--budget-ms", help="覆盖脚本的单次 tick 执行预算（正有限十进制毫秒数）")
    duration = q.add_mutually_exclusive_group()
    duration.add_argument("--seconds", type=float, default=30, help="客户端内脚本时限，默认30秒")
    duration.add_argument(
        "--continuous", action="store_true", help="明确持续执行；结束等待保留任务，取消须script cancel"
    )
    q = command("open", "完成本容器登录并确认已有角色入图")
    q.add_argument("--server", type=Path, help="本实例对应的服务器配置")
    q.add_argument("--account", type=Path, required=True, help="已有账号和角色的 0600 配置")
    q.add_argument("--timeout", type=float, default=90)
    command("close", "提示通过宿主工作台生命周期入口关闭本容器")
    command("stop", "显式释放当前客户端遗留控制")
    command("revive", "提交一次正常复活请求并核对同角色恢复；存活时跳过")
    q = command("skill-up", "逐点分配技能点并核对结果", allow_abbrev=False)
    q.add_argument("skill_id", type=int)
    q.add_argument("--points", type=int, default=1)
    q = command("skill-up-reconcile", "显式核对未知的原生加点请求，不发加点事件", allow_abbrev=False)
    q.add_argument("skill_id", type=int)
    q.add_argument("--request-id", required=True, help="原加点请求 ID")
    command("auto-ap", "一次自动分配全部AP并核对实际属性")
    q = command("snapshot", "场景、角色、对话与可操作引用")
    q.add_argument("--all", action="store_true", help="含画外实体")
    q.add_argument("-i", "--interactive", action="store_true", help="简洁列出NPC/对话/掉落")
    q = command("watch", "持续只读角色变化，输出JSONL")
    q.add_argument("--seconds", type=float, default=10)
    q.add_argument("--interval", type=float, default=0.5)
    q = command("events", "只读原生事件序列，或持续监听新事件")
    q.add_argument("action", nargs="?", choices=["read", "watch"], default="read")
    q.add_argument("--cursor", help="包含 instance_id、run_id、seq 的 JSON 游标")
    q.add_argument("--seconds", type=float, help="watch 的可选监听时长；省略则持续监听")
    q.add_argument("--interval", type=float, default=0.025, help="watch 读取间隔，0.01 至 1 秒")
    q = command("inspect", "按需读取一个领域或静态资源")
    q.add_argument(
        "kind",
        choices=["character", "scene", "inventory", "quests", "skills", "stage", "ui", "item", "npc", "monster", "map"],
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
    q = command("notifications", "读取所有原生通知气泡，按当前引用响应真实按钮")
    q.add_argument("action", choices=["read", "respond"], default="read", nargs="?")
    q.add_argument("reference", nargs="?", help="notifications read返回的当前@notification引用")
    q.add_argument("--button", type=int, help="respond必须指定当前气泡实际存在的control_id")
    q = command("batch", "从JSON文件或stdin执行一组CLI命令，任一步失败立即停止")
    q.add_argument("--file", type=Path)
    q = command("ui", "只读当前已识别窗口与场景焦点")
    q.add_argument("action", choices=["read"], default="read", nargs="?")
    q = command("equip", "按GUI背包路径装备物品，并核对身上负槽")
    q.add_argument("item")
    command("hotkeys", "读取客户端当前键位及快捷栏映射")
    q = command("bind", "正常拖动技能或物品到指定快捷键，并核对映射")
    q.add_argument("kind", choices=["item", "skill"])
    q.add_argument("id", type=int)
    q.add_argument("key")
    q = command("shop", "读取当前普通商店商品，并执行已指定的买卖")
    q.add_argument("action", choices=["read", "buy", "sell", "close"], default="read", nargs="?")
    q.add_argument("item", nargs="?", type=int)
    q.add_argument("--count", type=int, default=1)
    q.add_argument("--slot", type=int)
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
    path = backend.paths.input_lock
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
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
    stage = backend.read("stage")
    result: JsonObject = {
        "stage": stage["stage"],
        "running": stage["running"],
        "channel": stage.get("channel"),
        "character": stage.get("character"),
        "unavailable": stage.get("unavailable", []),
        "image": backend.runtime.image,
        "source_revision": backend.runtime.source_revision,
        "run_id": backend.runtime.run_id,
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


def dispatch(backend: Backend, args: argparse.Namespace) -> JsonObject | None:
    cmd = args.command
    if cmd in {"login", "character"}:
        from .first_character import execute

        if cmd == "login" and args.timeout is None:
            args.timeout = 30 if (args.accept_terms or args.gender is not None) else 0
        if cmd == "login" and (args.accept_terms or args.gender is not None):
            if args.gender is None:
                raise ClientError("usage", "GUI 登录动作必须明确指定性别。")
            with control(backend, "login"):
                return execute(backend, args)
        if cmd == "character" and args.character_action == "create":
            with control(backend, "character create"):
                return execute(backend, args)
        return execute(backend, args)
    if cmd in {
        "revive",
        "auto-ap",
        "skill-up",
        "skill-up-reconcile",
        "click",
        "talk",
        "dialog",
        "ui",
        "equip",
        "bind",
        "shop",
        "notifications",
    } and not (cmd in {"dialog", "ui", "shop", "notifications"} and args.action == "read"):
        from .bridge import BridgeClient

        bridge = BridgeClient(backend.root, backend.name, backend.instance)
        if (bridge.directory / "state.json").exists():
            state = bridge.snapshot()
            script = next((item for item in state.get("scripts", []) if item["status"] == "running"), None)
            if script is not None:
                raise ClientError(
                    "input_busy",
                    "Lua仍在控制客户端；先显式取消对应脚本再操作窗口。",
                    {"script_id": script["id"]},
                )
    if cmd == "_cash-probe":
        from .observations import NativeObserver

        result, _ = NativeObserver(backend.root, backend.name, backend.instance)._read("cash-probe", 3)
        return result
    if cmd == "status":
        return status(backend)
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
        domains = DOMAINS - {"interaction"}
        return {
            "connected": state is not None,
            "ready": state["ready"] if state is not None else False,
            "observation_domains": sorted(domains),
            "native_actions": cast(JsonObject | None, state.get("capabilities")) if state is not None else None,
        }
    if cmd == "world-map":
        from .observations import NativeObserver

        return NativeObserver(backend.root, backend.name, backend.instance).route(args.start, args.goal)
    if cmd == "doctor":
        from .resources import load_resources

        resources = load_resources(backend.root)
        available = resources.gui_client.is_dir()
        return {
            "backend": backend.name,
            "root": str(backend.root),
            "image": backend.runtime.image,
            "source_revision": backend.runtime.source_revision,
            "check": {"static_configuration_valid": available, "image_available": True, "client_started": False},
            "state": status(backend),
        }
    if cmd == "bridge":
        from .bridge import BridgeClient

        bridge = BridgeClient(backend.root, backend.name, backend.instance)
        return cast(JsonObject, bridge.stop() if args.action == "stop" else bridge.snapshot())
    if cmd == "script":
        if args.action == "cancel":
            if args.session is None or args.file is not None:
                raise ClientError("usage", "script cancel需要--session，不接收Lua文件。")
            from .bridge import BridgeClient

            bridge = BridgeClient(backend.root, backend.name, backend.instance)
            return bridge.cancel_script(args.session, admission_control=control(backend, "script cancel"))
        if args.session is not None and args.action != "status":
            raise ClientError("usage", "--session仅用于script cancel/status。")
        if args.action == "status":
            if args.file is not None:
                raise ClientError("usage", "script status不接收脚本文件。")
            from .bridge import BridgeClient
            from .bridge import script_by_id

            bridge = BridgeClient(backend.root, backend.name, backend.instance)
            state = bridge.snapshot()
            script = state.get("script")
            if args.session is not None:
                if not re.fullmatch(r"[0-9a-fA-F]{32}", args.session):
                    raise ClientError("invalid_bridge_options", "--session须为script status中的32位脚本ID。")
                script = script_by_id(state, args.session)
                if script is None:
                    raise ClientError(
                        "script_session_mismatch", "当前原生状态没有指定脚本会话。", {"script_id": args.session}
                    )
            report: JsonObject = {
                "source": "client-native-bridge",
                "supported": "scripts" in state,
                "instance_id": state["instance_id"],
                "run_id": state["run_id"],
                "script": cast(JsonObject | None, script),
                "command": cast(JsonObject, state["command"]),
                "held_keys": state["held_keys"],
            }
            if "scripts" in state:
                report["scripts"] = cast(list[JsonObject], state["scripts"])
            return report
        if args.file is None:
            raise ClientError("usage", "script run/start需要UTF-8 Lua文件或含main.lua的目录脚本包。")
        from .bridge import BridgeClient
        from .strategy_scene import scene_context

        bridge = BridgeClient(backend.root, backend.name, backend.instance)
        consumer_file = args.file
        package = args.script_package
        if args.package_root is not None:
            if not args.package_root.is_dir():
                raise ClientError(
                    "script_package_root_invalid",
                    "显式 --package-root 必须是容器内可读的现存目录。",
                    {"path": str(args.package_root)},
                )
            package_root = args.package_root.resolve()
        else:
            package_root = find_script_package_root(cast(Path, consumer_file))
        if package is not None and args.package_root is None:
            package_root = package.resolve()
        source = cast(str, args.strategy_source)
        if package_root is None and re.search(r"\brequire\s*(?:\(\s*)?['\"]lib[./]", source):
            raise ClientError(
                "script_package_root_missing",
                "无法从脚本目录或父级识别包含 lib/ 的包根；请放入带 Lua 模块的 lib/，或显式传入 --package-root。",
                {"script_file": str(consumer_file)},
            )
        if args.budget_ms is not None:
            source = override_tick_budget(source, args.budget_ms)
        entry_file = cast(Path, package) / "main.lua" if package is not None else consumer_file
        scene = scene_context(bridge.snapshot())
        code = compile_strategy(source, args.strategy_options, scene)
        report = bridge.run_script(
            None,
            seconds=None if args.continuous else args.seconds,
            code=code,
            package_root=str(package_root) if package_root is not None else None,
            wait_for_start=args.action == "start",
            admission_control=control(backend, "script " + args.action),
        )
        return {**report, "script_file": str(entry_file), "policy_entry": "main(context)"}
    if cmd == "notifications":
        from .notifications import read_notifications, respond

        if args.action == "read":
            if args.reference is not None or args.button is not None:
                raise ClientError("usage", "notifications read不接收气泡引用或按钮。")
            return read_notifications(backend)
        if args.reference is None or args.button is None:
            raise ClientError("usage", "notifications respond需要当前引用和--button CONTROL_ID。")
        return respond(backend, args.reference, args.button)
    if cmd == "open":
        from .profile import load_profile

        profile = load_profile(args.account)

        from .session import open_game

        opened = open_game(
            backend,
            profile=profile,
            server=args.server,
            timeout=args.timeout,
        )
        character = cast(JsonObject, opened["character"])
        opened["playable"] = cast(int, character["hp"]) > 0
        if not opened["playable"]:
            opened["next_action"] = "revive"
        return opened
    if cmd == "close":
        raise ClientError("host_lifecycle_required", "请通过宿主工作台入口 close 关闭并确认所属容器退出。")
    if cmd == "stop":
        from .bridge import BridgeClient

        return BridgeClient(backend.root, backend.name, backend.instance).stop()
    if cmd == "skill-up-reconcile":
        from .skill_up import reconcile_skill_up

        return reconcile_skill_up(backend, args.skill_id, args.request_id)
    if cmd == "skill-up":
        if args.skill_id <= 0 or args.points <= 0:
            raise ClientError("usage", "技能 ID 和点数须为正整数。")
        from .skill_up import preflight_skill_up, skill_up_once

        confirmed = []
        identity = None
        try:
            for remaining in range(args.points, 0, -1):
                if args.points == 1:
                    expected = preflight_skill_up(backend, args.skill_id, remaining)
                    if expected is None:
                        raise ClientError("skill_state_changed", "预检身份不可用。")
                    confirmed.append(skill_up_once(backend, args.skill_id, expected))
                else:
                    expected = preflight_skill_up(backend, args.skill_id, remaining, batch=True)
                    if expected is None:
                        raise ClientError("skill_state_changed", "批量预检身份不可用。")
                    if identity is None:
                        identity = expected[:3]
                    elif identity != expected[:3]:
                        raise ClientError("skill_state_changed", "批量加点期间角色或实例发生变化。")
                    confirmed.append(skill_up_once(backend, args.skill_id, expected))
        except ClientError as error:
            raise ClientError(error.code, error.message, {**error.details, "confirmed": confirmed}) from error
        if args.points == 1:
            return confirmed[0]
        return {"skill_id": args.skill_id, "confirmed_points": len(confirmed), "allocations": confirmed}
    if cmd == "auto-ap":
        from .auto_ap import auto_ap

        return auto_ap(backend)
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
    if cmd == "events":
        from .events import EventReader, parse_cursor

        cursor = parse_cursor(args.cursor)
        reader = EventReader(backend.root, backend.name, backend.instance)
        if args.action == "read":
            return reader.read(cursor)
        if getattr(args, "_batch", False):
            raise ClientError("usage", "events watch须独立运行，不进入动作批次。")
        for event in reader.watch(cursor, seconds=args.seconds, interval=args.interval):
            print(json.dumps(event, ensure_ascii=False, separators=(",", ":")), flush=True)
        return None
    if cmd == "inspect":
        kind = args.kind
        if kind == "character":
            if args.id is not None:
                raise ClientError("usage", "角色观察不接受 ID。")
            return backend.read("observe")
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
            raise ClientError(
                "unsupported_capability", "GUI 物品引用只保留换装；消耗品使用已退役。", {"item_id": target["item_id"]}
            )
        raise ClientError("unsupported_click", "这个引用只用于观察；当前没有对应输入命令。", {"target": target})
    if cmd == "batch":
        raw = json.loads(args.file.read_text()) if args.file else json.load(sys.stdin)
        if not isinstance(raw, list) or not raw:
            raise ClientError("usage", 'batch需要非空JSON命令数组，例如[["status"],["snapshot"]]。')
        commands = []
        for index, words in enumerate(raw):
            if not isinstance(words, list) or not words or not all(type(v) in (str, int, float) for v in words):
                raise ClientError("usage", "每项命令须为字符串/数字参数数组。", {"index": index})
            parsed = parser().parse_args([str(v) for v in words])
            if parsed.command == "batch":
                raise ClientError("usage", "batch不支持嵌套；持续控制请使用tick脚本。", {"index": index})
            if parsed.command == "script" and parsed.action in {"run", "start", "describe"}:
                raise ClientError(
                    "usage",
                    "batch不执行需要先读文件的script动作；请独立运行script " + parsed.action + "。",
                    {"index": index},
                )
            if (
                getattr(parsed, "root", backend.root).resolve() != backend.root
                or getattr(parsed, "instance", backend.instance) != backend.instance
            ):
                raise ClientError("usage", "一批命令只控制同一客户端目录和实例。", {"index": index})
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
    if cmd == "ui":
        return backend.read("ui")
    if cmd == "equip":
        from . import items

        return items.equip(backend, resolve_item(backend, args.item))
    if cmd in ("hotkeys", "bind"):
        from . import hotkeys

        if cmd == "hotkeys":
            return hotkeys.read_hotkeys(backend)
        return (hotkeys.bind_item if args.kind == "item" else hotkeys.bind_skill)(backend, args.id, args.key)
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
    if isinstance(dialog, dict) and "dialog_type" in dialog:
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
        args, unrecognized = parser().parse_known_args(arguments)
        args.strategy_metadata = None
        args.strategy_source = None
        args.strategy_options = {}
        args.script_package = None
        if args.command == "script":
            if args.budget_ms is not None:
                try:
                    parse_script_execution("-- @tick.budget_ms " + args.budget_ms)
                except ClientError as error:
                    raise ClientError("invalid_bridge_options", "--budget-ms 须为正有限十进制毫秒数。") from error
            if args.action not in {"run", "start"} and (args.budget_ms is not None or args.package_root is not None):
                raise ClientError("usage", "--budget-ms 与 --package-root 仅用于script run/start。")
        if args.command == "script" and args.action in {"run", "start", "describe"} and args.file is not None:
            if args.file.is_dir():
                args.script_package = args.file
                entry = args.file / "main.lua"
                if not entry.is_file():
                    raise ClientError(
                        "script_package_entry_missing",
                        "目录脚本包缺少入口 main.lua，未发布执行请求。",
                        {"path": str(args.file)},
                    )
                args.strategy_source, args.strategy_metadata = read_strategy_entry(entry)
            else:
                args.strategy_source, args.strategy_metadata = read_strategy_file(args.file)
            if args.action in {"run", "start"}:
                args.strategy_options = parse_options(args.strategy_metadata, unrecognized)
                unrecognized = []
        if args.command == "script" and args.action in {"run", "start", "describe"} and args.file is None:
            raise ClientError("usage", "script " + args.action + " 需要UTF-8 Lua文件或目录脚本包。")
        if unrecognized:
            raise ClientError("usage", "unrecognized arguments: " + " ".join(unrecognized))
        if args.command == "script" and args.action == "describe":
            if args.session is not None or args.continuous or args.seconds != 30:
                raise ClientError("usage", "script describe只接收Lua文件和通用选择选项。")
            entry = (
                cast(Path, args.script_package) / "main.lua"
                if args.script_package is not None
                else cast(Path, args.file)
            )
            data = describe_strategy(entry, args.strategy_metadata, package_root=args.script_package)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": "script",
                        "backend": "beidou",
                        "instance": getattr(args, "instance", os.environ.get("MAPLE_INSTANCE", "default")),
                        "data": data,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            return 0
        backend = Backend(
            getattr(args, "root", Path(os.environ.get("CLIENT_ROOT", "/work"))),
            os.environ.get("MAPLE_BACKEND", "beidou"),
            getattr(args, "instance", os.environ.get("MAPLE_INSTANCE", "default")),
        )
        readonly = (
            args.command
            in (
                "status",
                "login",
                "character",
                "capabilities",
                "world-map",
                "doctor",
                "snapshot",
                "watch",
                "events",
                "inspect",
                "screenshot",
                "record",
                "hotkeys",
                "_cash-probe",
            )
            or (args.command == "bridge" and args.action == "status")
            or (args.command == "script" and args.action in {"status", "describe"})
            or (args.command == "notifications" and args.action == "read")
            or (args.command == "dialog" and args.action == "read")
            or (args.command == "ui" and args.action == "read")
            or (args.command == "shop" and args.action == "read")
        )
        if args.command == "close":
            result = dispatch(backend, args)
        elif args.command == "script" and not readonly or args.command == "events" and args.action == "watch":
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
            if args.command == "snapshot" and not json_output:
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
        return 2
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
