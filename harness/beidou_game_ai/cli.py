"""客户端容器内的 Codex 消费者；通过本地 CLI 控制所属实例。"""

import argparse
import asyncio
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import sys
from typing import cast

from beidou_pilot.errors import ClientError
from beidou_pilot.runtime import load_runtime

from .client import GameClient, GameClientError
from .controller import Controller
from .protocol import AppServer, AppServerError, JsonObject


async def commands(controller: Controller) -> None:
    reader = asyncio.StreamReader()
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(
        lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
    )
    try:
        while line := await reader.readline():
            identifier = None
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict) or not isinstance(raw.get("command"), str):
                    raise ValueError("协作输入需要 command 字段。")
                request = cast(JsonObject, raw)
                identifier = request.get("id")
                command = request["command"]
                if command == "status":
                    result = controller.status()
                elif command in {"message", "task"}:
                    if not isinstance(request.get("text"), str):
                        raise ValueError("message 需要 text。")
                    text = cast(str, request["text"])
                    if command == "task":
                        await controller.update_task(text)
                    else:
                        controller.emit("developer_message", {"text": text})
                        await controller.message(text)
                    result = controller.status()
                elif command == "answer":
                    request_id = request.get("request_id")
                    answers = request.get("answers")
                    if type(request_id) not in (int, str) or request_id not in controller.questions:
                        raise ValueError("询问已结束或不属于当前会话。")
                    if not isinstance(answers, dict) or any(
                        not isinstance(value, dict)
                        or not isinstance(value.get("answers"), list)
                        or any(not isinstance(answer, str) for answer in value["answers"])
                        for value in answers.values()
                    ):
                        raise ValueError("answer 需要按问题ID提供 answers 字符串数组。")
                    await controller.server.respond(cast(int | str, request_id), {"answers": answers})
                    controller.questions.pop(cast(int | str, request_id), None)
                    result = controller.status()
                elif command in {"pause", "resume", "stop"}:
                    await controller.control(cast(str, command))
                    result = controller.status()
                else:
                    raise ValueError("协作命令仅支持 status/message/task/answer/pause/resume/stop。")
                controller.emit("command_result", {"id": identifier, "ok": True, "data": result})
                if command == "stop":
                    return
            except (json.JSONDecodeError, ValueError) as error:
                controller.emit(
                    "command_result",
                    {"id": identifier, "ok": False, "error": {"code": "invalid_command", "message": str(error)}},
                )
            except (GameClientError, AppServerError) as error:
                controller.emit(
                    "command_result",
                    {"id": identifier, "ok": False, "error": {"code": error.code, "message": error.message}},
                )
        await controller.control("stop")
    finally:
        transport.close()


async def run(args: argparse.Namespace) -> None:
    os.umask(0o077)
    runtime = load_runtime(
        Path(os.environ["CLIENT_ROOT"]), os.environ["MAPLE_BACKEND"], os.environ.get("MAPLE_INSTANCE", "default")
    )
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with ExitStack() as locks:
        state_lock = locks.enter_context((state / "harness.lock").open("a"))
        try:
            fcntl.flock(state_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GameClientError("harness_state_busy", "该游戏 AI 状态目录已由另一进程使用。") from error
        if not args.read_only:
            session_lock = locks.enter_context((Path(os.environ["CLIENT_ROOT"]) / "state/llm-session.lock").open("a"))
            try:
                fcntl.flock(session_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise GameClientError(
                    "harness_busy", "所属客户端已有可执行 CLI 的 LLM 会话，未启动第二个会话。"
                ) from error
        role = args.role.read_text(encoding="utf-8")
        codex_state = state / "codex"
        codex_state.mkdir(exist_ok=True, mode=0o700)
        (state / "home").mkdir(exist_ok=True, mode=0o700)
        environment = os.environ.copy()
        environment.pop("BEIDOU_EXEC_TOKEN", None)
        environment["CODEX_HOME"] = str(codex_state)
        environment["HOME"] = str(state / "home")
        environment["BEIDOU_GAME_AI_READ_ONLY"] = "1" if args.read_only else "0"
        if args.provider_config is not None:
            environment["BEIDOU_GAME_AI_PROVIDER_CONFIG"] = str(args.provider_config.resolve())
        else:
            environment.pop("BEIDOU_GAME_AI_PROVIDER_CONFIG", None)
        if args.auth_file is not None:
            environment["BEIDOU_GAME_AI_AUTH_FILE"] = str(args.auth_file.resolve())
        else:
            environment.pop("BEIDOU_GAME_AI_AUTH_FILE", None)
        server = await AppServer.start(
            ["/opt/beidou-game-ai/entrypoint.sh", "app-server", "--stdio", "--strict-config"],
            stderr=state / "codex.stderr.log",
            env=environment,
        )
        game = GameClient(args.cli)
        binding: JsonObject = {
            "cli": str(args.cli.resolve()),
            "workbench_id": os.environ["BEIDOU_WORKBENCH_ID"],
            "character_id": runtime.character_id,
            "world": runtime.world,
            "server": {"project": runtime.target["project"], "service": runtime.target["service"]},
            "read_only": args.read_only,
        }
        controller = Controller(
            server,
            game,
            state,
            args.model,
            role,
            args.task,
            binding,
            read_only=args.read_only,
        )
        initialized = False
        events: asyncio.Task[None] | None = None
        incoming: asyncio.Task[None] | None = None
        signal_wait: asyncio.Task[bool] | None = None
        stopped: asyncio.Task[bool] | None = None
        stop_signal = asyncio.Event()
        loop = asyncio.get_running_loop()
        for name in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(name, stop_signal.set)
        try:
            await controller.initialize()
            initialized = True
            events = asyncio.create_task(controller.events())
            if args.paused:
                controller.mode = "paused"
                controller.emit("ready", controller.status())
            else:
                observed = await game.observe()
                await controller.message(
                    "当前任务："
                    + args.task
                    + "\n先前经历不是当前状态，请以这次新鲜观察重新决策："
                    + json.dumps(observed, ensure_ascii=False)
                )
            incoming = asyncio.create_task(commands(controller))
            signal_wait = asyncio.create_task(stop_signal.wait())
            stopped = asyncio.create_task(controller.done.wait())
            finished, _ = await asyncio.wait(
                {events, incoming, signal_wait, stopped}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in finished:
                await task
        finally:
            try:
                if initialized and controller.mode != "stopped":
                    await controller.control("stop")
            finally:
                if incoming is not None and not incoming.done():
                    incoming.cancel()
                if signal_wait is not None:
                    signal_wait.cancel()
                if stopped is not None:
                    stopped.cancel()
                await controller.server.close()
                if events is not None:
                    await events
                for name in (signal.SIGINT, signal.SIGTERM):
                    loop.remove_signal_handler(name)


def main() -> int:
    parser = argparse.ArgumentParser(description="客户端容器内的 Codex 游戏 AI；stdin/stdout 为专用 JSONL 协作通道。")
    parser.add_argument("--cli", type=Path, default=Path(shutil.which("beidou-pilot") or "/usr/local/bin/beidou-pilot"))
    parser.add_argument("--state", type=Path, required=True, help="容器内专用私密状态目录；不要使用开发Codex目录")
    parser.add_argument("--role", type=Path, required=True, help="只包含角色及养成约束的UTF-8文本")
    parser.add_argument("--task", required=True)
    parser.add_argument("--model", choices=["gpt-6-luna", "gpt-6.1-terra"], default="gpt-6-luna")
    parser.add_argument("--read-only", action="store_true", help="只装载观察工具，不提交Lua或接管角色")
    parser.add_argument("--paused", action="store_true", help="初始化后等待resume，不立即开始模型turn或游戏操作")
    parser.add_argument("--provider-config", type=Path, help="专用运行时TOML，不使用开发config.toml")
    parser.add_argument("--auth-file", type=Path, help="专用认证副本，仅运行时初始化，不读取或打印其内容")
    args = parser.parse_args()
    for path in (args.cli, args.role, args.provider_config, args.auth_file):
        if path is not None and not path.is_file():
            parser.error("指定的入口或运行时文件不存在。")
    if any(not os.environ.get(name) for name in ("CLIENT_ROOT", "RUN_ID", "MAPLE_BACKEND", "BEIDOU_WORKBENCH_ID")):
        parser.error("须在已启动且提供固定工作目录绑定的所属客户端容器内运行。")
    try:
        asyncio.run(run(args))
        return 0
    except (GameClientError, AppServerError, ClientError) as error:
        print(
            json.dumps(
                {"event": "failed", "error": {"code": error.code, "message": error.message}}, ensure_ascii=False
            ),
            flush=True,
        )
        return 2
