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
from typing import Iterator, cast

from .backend import Backend, ClientError, JsonObject
from .catalog import Catalog
from . import dialogs
from .rules import FIRST_JOB_LEVELS, advancement, combat_stop_level
from .snapshot import collect, format_snapshot
from . import __version__


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ClientError("usage", message)


def parser() -> Parser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json", action="store_true", default=argparse.SUPPRESS, help="单个JSON结果；watch与events watch使用JSONL"
    )
    common.add_argument("--root", type=Path, default=argparse.SUPPRESS, help="本容器运行目录，默认CLIENT_ROOT")
    common.add_argument("--debug", action="store_true", default=argparse.SUPPRESS, help="保留引擎原始来源和布局细节")
    common.add_argument(
        "--backend",
        choices=["beidou", "headless"],
        default=argparse.SUPPRESS,
        help="核对本容器后端，默认MAPLE_BACKEND",
    )
    common.add_argument("--instance", default=argparse.SUPPRESS, help="核对本容器实例名，默认MAPLE_INSTANCE")
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
    q.add_argument("action", choices=["run", "start", "status", "cancel"])
    q.add_argument("--session", help="cancel必须指定当前script.id，只取消匹配脚本")
    q.add_argument("--library", choices=["travel", "island-supply"], help="为run/start显式装载公共Lua函数")
    source = q.add_mutually_exclusive_group()
    source.add_argument("file", type=Path, nargs="?", help="受信UTF-8 Lua文件")
    source.add_argument("--code", help="直接执行受信Lua源码，与文件输入互斥")
    duration = q.add_mutually_exclusive_group()
    duration.add_argument("--seconds", type=float, default=30, help="客户端内脚本时限，默认30秒")
    duration.add_argument(
        "--continuous", action="store_true", help="明确持续执行；结束等待保留任务，取消须script cancel"
    )
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
    q = command("skill", "通过Lua调用本后端支持的原生技能，分别报告派发与原始返回值")
    q.add_argument("id", type=int)
    q = command("open", "完成本容器登录并确认已有角色入图")
    q.add_argument("--server", type=Path, help="本实例对应的服务器配置")
    q.add_argument("--account", type=Path, required=True, help="已有账号和角色的 0600 配置")
    q.add_argument("--timeout", type=float, default=90)
    command("close", "提示通过宿主工作台生命周期入口关闭本容器")
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
    command("stop", "显式释放当前客户端遗留控制")
    command("revive", "请求一次本端正常复活并核对恢复；存活时跳过")
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
    q = command("notifications", "读取所有原生通知气泡，按当前引用响应真实按钮")
    q.add_argument("action", choices=["read", "respond"], default="read", nargs="?")
    q.add_argument("reference", nargs="?", help="notifications read返回的当前@notification引用")
    q.add_argument("--button", type=int, help="respond必须指定当前气泡实际存在的control_id")
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
    q = command("stats", "向明确基础属性分配AP，逐点核对目标与剩余点数")
    q.add_argument("stat", choices=["str", "dex", "int", "luk"])
    q.add_argument("count", type=int)
    q = command("skills", "向明确技能分配SP，逐点核对技能等级与剩余点数")
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
    q.add_argument("--first-job", choices=FIRST_JOB_LEVELS,
                   help="本次新手练级的首转路线；magician停8级，其余停10级")
    q.add_argument("--floor-y", type=int)
    q.add_argument("--bounds", type=int, nargs=2, metavar=("MIN", "MAX"))
    q.add_argument("--retreat-x", type=int)
    q.add_argument("--loot", action="store_true", help="启用同层落地物品定向拾取")
    q = command("hunt", "当前单一场景内自主找怪、换层和连续攻击；场景变化即停止")
    q.add_argument("mob", nargs="?", default="all", help="怪物名称、模板ID或all（默认全部怪物）")
    q.add_argument("--skill", type=int, help="指定已学且本后端支持的技能ID；省略时使用普攻")
    q.add_argument("--range", type=float, default=60, dest="attack_range", help="接近目标的攻击距离，默认60")
    duration = q.add_mutually_exclusive_group()
    duration.add_argument("--seconds", type=float, default=60, help="狩猎期限，默认60秒")
    duration.add_argument("--continuous", action="store_true", help="持续到明确取消或安全停止；Ctrl+C只结束等待")
    q.add_argument("--bounds", type=int, nargs=2, metavar=("MIN", "MAX"), help="限定本场景横向狩猎范围")
    q.add_argument("--until-level", type=int, help="到达指定等级停止；仍受当前转职节点限制")
    q.add_argument("--first-job", choices=FIRST_JOB_LEVELS,
                   help="本次新手练级的首转路线；magician停8级，其余停10级")
    q.add_argument("--min-hp-ratio", type=float, default=0.35, help="HP安全下限比例，默认0.35")
    q.add_argument("--hp-item", type=int, help="低HP时使用的明确回血物品ID，不自动买药")
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
    if backend.name == "headless":
        from .headless import status as native_status

        result = native_status(backend.root, backend.instance)
        if result["stage"] == "IN_GAME" and result["character"] is not None:
            result["advancement"] = advancement(cast(JsonObject, result["character"]))
        return result
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
        "events",
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
        "hunt",
        "batch",
        "use",
        "equip",
        "unequip",
        "stats",
        "skills",
    }:
        raise ClientError("unsupported_capability", "该客户端尚未提供这个窗口、原始按键或玩法接口。", {"command": cmd})
    if (
        backend.name == "beidou"
        and cmd
        in {
            "click",
            "talk",
            "dialog",
            "ui",
            "equip",
            "use",
            "stats",
            "skills",
            "bind",
            "press",
            "shop",
            "notifications",
        }
        and not (cmd in {"dialog", "ui", "shop", "notifications"} and args.action == "read")
    ):
        from .bridge import BridgeClient

        bridge = BridgeClient(backend.root, backend.name, backend.instance)
        if (bridge.directory / "state.json").exists():
            state = bridge.snapshot()
            script = state.get("script")
            if script is not None and script["status"] == "running":
                raise ClientError(
                    "input_busy",
                    "Lua仍在控制客户端；先显式取消对应脚本再操作窗口。",
                    {"script_id": script["id"]},
                )
    if cmd == "status":
        return status(backend)
    if cmd == "instances":
        runtime = backend.runtime
        return {
            "instances": [
                {
                    "name": runtime.instance,
                    "backend": runtime.backend,
                    "container_id": runtime.container_id,
                    "run_id": runtime.run_id,
                    "running": runtime.running,
                    "character_id": runtime.character_id,
                    "image": runtime.image,
                    "source_revision": runtime.source_revision,
                }
            ]
        }
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
            DOMAINS - {"interaction"}
            if backend.name == "beidou"
            else DOMAINS - {"hotkeys", "dialog", "ui", "shop", "notifications"}
        )
        return {
            "connected": state is not None,
            "ready": state["ready"] if state is not None else False,
            "observation_domains": sorted(domains),
            "native_actions": cast(JsonObject | None, state.get("capabilities")) if state is not None else None,
        }
    if cmd == "doctor":
        from .resources import load_resources

        resources = load_resources(backend.root)
        if backend.name == "beidou":
            from .binaries import verify_binaries

            available = verify_binaries(backend.root)
        else:
            available = resources.headless_resources.is_dir()
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
    if cmd == "skill":
        from .control_scripts import skill

        return skill(backend, args.id)
    if cmd == "script":
        from .bridge import BridgeClient

        bridge = BridgeClient(backend.root, backend.name, backend.instance)
        if args.library is not None and args.action not in {"run", "start"}:
            raise ClientError("usage", "--library仅用于script run/start。")
        if args.action == "cancel":
            if args.session is None or args.file is not None or args.code is not None:
                raise ClientError("usage", "script cancel需要--session，不接收Lua文件或源码。")
            return bridge.cancel_script(args.session)
        if args.session is not None:
            raise ClientError("usage", "--session仅用于script cancel。")
        if args.action == "status":
            if args.file is not None or args.code is not None:
                raise ClientError("usage", "script status不接收脚本文件或源码。")
            state = bridge.snapshot()
            return {
                "source": "client-native-bridge",
                "supported": "script" in state,
                "instance_id": state["instance_id"],
                "run_id": state["run_id"],
                "script": cast(JsonObject | None, state.get("script")),
                "command": cast(JsonObject, state["command"]),
                "held_keys": state["held_keys"],
            }
        if args.file is None and args.code is None:
            raise ClientError("usage", "script run/start需要UTF-8本地Lua文件或--code源码。")
        consumer_file = args.file
        if args.library is not None:
            from .script_libraries import with_library

            args.code = with_library(args.library, args.file, args.code)
            args.file = None
        if args.action == "start":
            report = bridge.run_script(
                args.file, seconds=None if args.continuous else args.seconds, code=args.code, wait_for_start=True
            )
        else:
            report = bridge.run_script(args.file, seconds=None if args.continuous else args.seconds, code=args.code)
        if args.library is not None:
            return {**report, "library": args.library, "consumer_file": str(consumer_file) if consumer_file else None}
        return report
    if cmd == "notifications":
        from .notifications import read_notifications, respond

        if args.action == "read":
            if args.reference is not None or args.button is not None:
                raise ClientError("usage", "notifications read不接收气泡引用或按钮。")
            return read_notifications(backend)
        if args.reference is None or args.button is None:
            raise ClientError("usage", "notifications respond需要当前引用和--button CONTROL_ID。")
        return respond(backend, args.reference, args.button)
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
        from .profile import load_profile

        profile = load_profile(args.account)

        if backend.name == "headless":
            from .headless import open_game as open_native

            return open_native(
                backend.root,
                server=args.server,
                profile=profile,
                timeout=args.timeout,
                instance=backend.instance,
            )
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
        from .control_scripts import window

        if args.action == "read":
            return backend.read("ui")
        if args.action == "focus":
            return window(backend, "game")
        if args.window is None:
            raise ClientError("usage", "ui open/close需要窗口名。")
        if args.window == "all":
            if args.action != "close":
                raise ClientError("usage", "all仅用于ui close。")
            from .shop import close_shop

            closed_shop = close_shop(backend)
            return {
                "shop": closed_shop,
                "windows": [window(backend, w, False) for w in ("skills", "stats", "inventory")],
            }
        if args.window == "shop":
            if args.action != "close":
                raise ClientError("usage", "商店通过talk商人打开；ui close shop可关闭。")
            from .shop import close_shop

            return close_shop(backend)
        return window(backend, args.window, args.action == "open")
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
        from .control_scripts import allocate

        if args.count < 1:
            raise ClientError("usage", "点数必须为正整数。")
        attributes = {"str": "strength", "dex": "dexterity", "int": "intelligence", "luk": "luck"}
        return allocate(backend, attributes[args.stat] if cmd == "stats" else args.skill, args.count)
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
    if cmd == "hunt":
        from .hunting import hunt

        return hunt(
            backend,
            args.mob,
            seconds=None if args.continuous else args.seconds,
            skill_id=args.skill,
            attack_range=args.attack_range,
            bounds=tuple(args.bounds) if args.bounds is not None else None,
            stop_level=args.until_level,
            first_job=args.first_job,
            min_hp_ratio=args.min_hp_ratio,
            hp_item_id=args.hp_item,
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
        stop_level, stop_level_source, milestone = combat_stop_level(
            cast(JsonObject, char), first_job=args.first_job, until_level=args.until_level,
            default_level=char["level"] + 1,
        )
        report = lua_fight(
            backend,
            mob_id=mob_id,
            seconds=args.seconds,
            stop_level=cast(int, stop_level),
            floor_y=y,
            bounds=(bounds[0], bounds[1]),
            retreat_x=args.retreat_x if args.retreat_x is not None else int(pos["x"]),
            loot=args.loot,
        )
        return {**report, "advancement": milestone, "stop_level_source": stop_level_source}
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
            getattr(args, "root", Path(os.environ.get("CLIENT_ROOT", "/work"))),
            getattr(args, "backend", os.environ.get("MAPLE_BACKEND", "beidou")),
            getattr(args, "instance", os.environ.get("MAPLE_INSTANCE", "default")),
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
                "events",
                "inspect",
                "screenshot",
                "record",
                "hotkeys",
            )
            or (args.command == "bridge" and args.action == "status")
            or (args.command == "script" and args.action == "status")
            or (args.command == "notifications" and args.action == "read")
            or (args.command == "dialog" and args.action == "read")
            or (args.command == "ui" and args.action == "read")
            or (args.command == "shop" and args.action == "read")
        )
        if args.command == "close":
            result = dispatch(backend, args)
        elif args.command == "task" or args.command == "events" and args.action == "watch":
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
