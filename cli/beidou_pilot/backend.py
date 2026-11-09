"""为命令层提供固定客户端根目录和受控引擎执行边界。"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import cast
import uuid

from .engines.desktop import DesktopActions
from .errors import ClientError, JsonObject, JsonValue
from .instances import InstancePaths


class Backend:
    def __init__(self, client_root: Path, name: str = "beidou", instance: str = "default") -> None:
        self.root = client_root.resolve()
        self.name = name
        self.paths = InstancePaths(self.root, name, instance)
        self.instance = instance
        if not self.root.joinpath("clientctl.py").is_file():
            raise ClientError("invalid_client_root", "CLIENT_ROOT 须指向客户端目录。")

    def _run(self, name: str, arguments: list[str], *, payload: str | None = None,
             stream: bool = False, stream_stdout: bool = False) -> str:
        if self.name != "beidou" and name not in {"observe", "scene", "inventory", "character", "quests", "stage"}:
            raise ClientError("unsupported_capability", "该客户端不提供此北斗窗口或原始输入能力。", {"engine": name})
        engines = {"observe", "scene", "dialog", "inventory", "quests", "desktop",
                   "session", "ui", "stage", "character", "hotkeys", "shop", "record"}
        if name in {"clientctl", "runtime-ui"}:
            command = [sys.executable, str(self.root / (name + ".py")), *arguments]
        elif name in engines:
            command = [sys.executable, "-m", "beidou_pilot.engines." + name.replace("-", "_"), *arguments]
        else:
            raise ClientError("unknown_engine", "未知客户端引擎。", {"engine": name})
        environment = os.environ.copy()
        environment["CLIENT_ROOT"] = str(self.root)
        environment["MAPLE_BACKEND"] = self.name
        environment["MAPLE_INSTANCE"] = self.instance
        environment["PYTHONPATH"] = os.pathsep.join((str(Path(__file__).resolve().parents[1]), str(self.root),
                                                    environment.get("PYTHONPATH", "")))
        cancel_path: Path | None = None
        if (name == "record" or (name == "desktop" and arguments and arguments[0] == "execute")) and "--cancel-file" not in arguments:
            stage = self.read("stage")
            client = cast(JsonObject | None, stage.get("client"))
            if client is None:
                raise ClientError("client_not_running", "操作前未确认运行中的客户端，请先 open。")
            cancel_name = "cli-" + name + "-cancel-" + uuid.uuid4().hex
            cancel_path = self.root / "runtime/runs" / cast(str, client["run_id"]) / cancel_name
            command += ["--cancel-file", cancel_name]
        try:
            if (name == "clientctl" and arguments[0] in {"check", "start"}
                    and not environment.get("CLIENT_IMAGE")):
                image = subprocess.run(["docker", "image", "inspect", "local/beidou-v17-client:intel",
                                        "--format", "{{.Id}}"], text=True, capture_output=True)
                if image.returncode:
                    raise ClientError("client_image_unavailable", "本地客户端镜像不可用；未自动拉取或构建。",
                                      {"image": "local/beidou-v17-client:intel", "stderr": image.stderr.strip()})
                environment["CLIENT_IMAGE"] = image.stdout.strip()
            if stream:
                process = subprocess.Popen(command, cwd=self.root, env=environment, text=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                lines: list[str] = []
                try:
                    assert process.stdout is not None
                    for line in process.stdout:
                        print(line, end="", file=sys.stdout if stream_stdout else sys.stderr, flush=True)
                        lines.append(line)
                    process.wait()
                except KeyboardInterrupt:
                    if process.poll() is None:
                        process.send_signal(signal.SIGINT)
                        process.wait(timeout=5)
                    raise
                finally:
                    if process.stdout is not None:
                        process.stdout.close()
                output = "".join(lines)
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, command, output=output, stderr="")
                return output
            if cancel_path is not None:
                process = subprocess.Popen(command, cwd=self.root, env=environment, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    output, errors = process.communicate(payload)
                except KeyboardInterrupt:
                    # 容器任务看到取消标记后收尾；桌面原语另在finally释放键鼠。
                    cancel_path.write_text("cli_interrupted")
                    process.communicate()
                    raise
                if process.returncode:
                    cancel_path.write_text(name + "_failed")
                    raise subprocess.CalledProcessError(process.returncode, command, output=output, stderr=errors)
                cancel_path.unlink(missing_ok=True)
                return output
            result = subprocess.run(command, cwd=self.root, env=environment, input=payload,
                                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        except OSError as error:
            raise ClientError("backend_unavailable", "客户端引擎无法启动。",
                              {"engine": name, "reason": str(error)}) from error
        except subprocess.CalledProcessError as error:
            raise ClientError("backend_failed", "客户端引擎执行失败。",
                              {"engine": name, "exit_code": error.returncode,
                               "stderr": error.stderr.strip(), "stdout": error.stdout or ""}) from error
        return result.stdout or ""

    def _json(self, name: str, arguments: list[str], *, payload: str | None = None) -> JsonObject:
        output = self._run(name, arguments, payload=payload)
        try:
            value = json.loads(output)
        except json.JSONDecodeError as error:
            raise ClientError("invalid_backend_output", "客户端引擎未返回单个 JSON 对象。",
                              {"engine": name, "reason": error.msg}) from error
        if not isinstance(value, dict):
            raise ClientError("invalid_backend_output", "客户端引擎未返回 JSON 对象。", {"engine": name})
        return cast(JsonObject, value)

    def read(self, name: str, *arguments: str) -> JsonObject:
        return self._json(name, list(arguments))

    def text(self, name: str, *arguments: str) -> str:
        return self._run(name, list(arguments))

    def desktop(self, actions: DesktopActions) -> JsonObject:
        """GUI的短线性桌面原语，不承接角色控制循环。"""
        return self._json("desktop", ["execute"], payload=json.dumps(actions))

    def stream(self, name: str, args: list[str], *, stdout: bool = False) -> JsonObject:
        output = self._run(name, args, stream=True, stream_stdout=stdout)
        try:
            value = json.loads(output.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as error:
            raise ClientError("invalid_backend_output", "流式命令没有可用的最终JSON结果。", {"engine": name}) from error
        if not isinstance(value, dict):
            raise ClientError("invalid_backend_output", "流式命令的最终结果不是JSON对象。", {"engine": name})
        return cast(JsonObject, value)
