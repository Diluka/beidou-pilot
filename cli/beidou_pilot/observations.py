"""通过客户端原生只读通道观察状态，不读取其他进程的内存。"""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Iterator, cast
import uuid

from .binaries import CLIENT_SHA256, verify_binaries
from .errors import ClientError, JsonObject, JsonValue
from .instances import InstancePaths, selected_instance


DOMAINS = frozenset({"stage", "scene", "inventory", "character", "quests", "hotkeys", "dialog", "interaction", "ui", "shop",
                     "notifications"})


def client_root() -> Path:
    return Path(os.environ.get("CLIENT_ROOT", Path(__file__).resolve().parents[1])).resolve()


def selected_backend() -> str:
    return os.environ.get("MAPLE_BACKEND", "beidou")


def _docker(*arguments: str) -> str:
    try:
        return subprocess.run(["docker", *arguments], text=True, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        raise ClientError("observation_runtime_unavailable", "无法核验客户端观察目标。", {"reason": detail}) from error


@dataclass(frozen=True)
class Session:
    container_id: str
    run_id: str
    run_dir: Path
    backend: str
    image: str


def active_session(root: Path, backend: str, instance: str = "default") -> Session | None:
    if backend not in {"beidou", "headless"}:
        raise ClientError("unsupported_backend", "未知客户端后端。", {"backend": backend})
    task = "client-v17-maintained" if backend == "beidou" else "maple-headless-maintained"
    filters = ["label=beidou.task=" + task, "label=beidou.client.root=" + str(root)]
    registration = None
    if backend == "headless":
        try:
            registration = json.loads(InstancePaths(root, backend, instance).registration.read_text())
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as error:
            raise ClientError("observation_session_unavailable", "无法读取当前无头会话登记。") from error
        if (not isinstance(registration, dict) or any(not isinstance(registration.get(field), str)
                for field in ("container_id", "run_id", "image", "run_dir"))):
            raise ClientError("observation_session_unavailable", "无头会话登记字段无效。")
        if not registration["container_id"]:
            return None
        filters.append("id=" + registration["container_id"])
    identifiers = _docker("ps", "-q", *(value for condition in filters for value in ("--filter", condition))).split()
    if not identifiers:
        return None
    if len(identifiers) != 1:
        raise ClientError("observation_target_not_unique", "当前后端有多个客户端，未选择观察目标。")
    container = json.loads(_docker("inspect", identifiers[0]))[0]
    host = container["HostConfig"]
    if host["Privileged"] or host["PortBindings"] or host["NetworkMode"] == "host":
        raise ClientError("observation_target_invalid", "客户端容器不符合观察边界。")
    if backend == "beidou":
        if not verify_binaries(root):
            raise ClientError("native_observation_unsupported", "当前客户端未登记原生观察构建。")
        environment = dict(entry.split("=", 1) for entry in container["Config"]["Env"])
        run_id = environment["RUN_ID"]
        directory = root / "runtime/runs" / run_id
    else:
        assert registration is not None
        if (registration.get("container_id") != container["Id"]
                or registration.get("image") != container["Image"]
                or container["Config"]["Labels"].get("beidou.client.instance", "default") != instance):
            raise ClientError("observation_session_mismatch", "无头客户端与会话登记不符。")
        run_id = registration["run_id"]
        directory = Path(registration["run_dir"])
    return Session(container["Id"], run_id, directory, backend, container["Image"])


class NativeObserver:
    def __init__(self, root: Path | None = None, backend: str | None = None, instance: str | None = None) -> None:
        self.root = (root or client_root()).resolve()
        self.backend = backend or selected_backend()
        self.instance = instance if instance is not None else selected_instance()
        self.directory = InstancePaths(self.root, self.backend, self.instance).bridge
        self.session = active_session(self.root, self.backend, self.instance)

    def _snapshot(self, max_age: float) -> JsonObject:
        assert self.session is not None
        try:
            raw = json.loads((self.directory / "state.json").read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ClientError("native_observation_not_ready", "原生观察状态尚未发布。") from error
        if (not isinstance(raw, dict) or raw.get("protocol") != 1
                or not isinstance(raw.get("instance_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_-]+", raw["instance_id"])
                or raw.get("run_id") != self.session.run_id
                or any(type(raw.get(field)) is not int for field in ("seq", "observed_at_ms", "scene_generation"))):
            raise ClientError("native_observation_not_ready", "原生观察状态不属于当前运行会话。")
        if any(raw.get(field) is not None and type(raw[field]) is not bool
               for field in ("dead", "revive_requestable")):
            raise ClientError("native_observation_not_ready", "原生死亡观察字段无效。")
        age = time.time() - raw["observed_at_ms"] / 1000
        if not -.1 <= age <= max_age:
            raise ClientError("native_observation_not_ready", "原生观察状态尚未恢复有效采样。",
                              {"age_seconds": round(age, 4)})
        return cast(JsonObject, raw)

    def snapshot(self, timeout: float = 3) -> JsonObject:
        if self.session is None:
            raise ClientError("client_not_running", "当前后端没有运行中的客户端。")
        until = time.monotonic() + timeout
        while True:
            try:
                return self._snapshot(max_age=1)
            except ClientError as error:
                if error.code != "native_observation_not_ready" or time.monotonic() >= until:
                    raise
            time.sleep(.01)

    def metadata(self, state: JsonObject) -> JsonObject:
        assert self.session is not None
        client: JsonObject = {"container_id": self.session.container_id[:12], "run_id": self.session.run_id,
                              "run_dir": str(self.session.run_dir), "instance_id": state["instance_id"],
                              "runtime_image": self.session.image}
        if self.backend == "beidou":
            client["binary_sha256"] = CLIENT_SHA256
        return {"source": "client-native-api", "readonly": True, "backend": self.backend, "instance": self.instance,
                "observed_at": datetime.fromtimestamp(cast(int, state["observed_at_ms"]) / 1000,
                                                       timezone.utc).isoformat(),
                "instance_id": state["instance_id"], "seq": state["seq"],
                "scene_generation": state["scene_generation"], "client": client}

    @contextmanager
    def _read_lane(self, until: float) -> Iterator[None]:
        try:
            handle = (self.directory / "observation.lock").open("a")
        except OSError as error:
            raise ClientError("native_observation_unavailable", "无法打开原生只读观察通道。") from error
        with handle:
            while True:
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as error:
                    if time.monotonic() >= until:
                        raise ClientError("native_observation_busy", "原生只读观察通道正在被其他查询使用。") from error
                    time.sleep(.01)
            yield

    def observe(self, domain: str, timeout: float = 3) -> JsonObject:
        if domain not in DOMAINS:
            raise ClientError("unsupported_observation", "没有这个原生观察领域。", {"domain": domain})
        if not math.isfinite(timeout) or timeout <= 0:
            raise ClientError("invalid_observation_options", "观察期限须为正数。")
        before = self.snapshot(timeout)
        until = time.monotonic() + timeout
        request_id = uuid.uuid4().hex
        started = time.monotonic()
        with self._read_lane(until):
            temporary = self.directory / ("observation-" + request_id + ".tmp")
            line = " ".join(("1", cast(str, before["instance_id"]), request_id, domain)) + "\n"
            try:
                with temporary.open("x", encoding="ascii") as stream:
                    stream.write(line)
                temporary.replace(self.directory / "observation-request.txt")
            except OSError as error:
                raise ClientError("native_observation_write_failed", "无法发布原生只读观察请求。",
                                  {"request_id": request_id}) from error
            while True:
                try:
                    result = json.loads((self.directory / "observation.json").read_text())
                except FileNotFoundError:
                    result = None
                except (OSError, json.JSONDecodeError) as error:
                    raise ClientError("native_observation_invalid", "原生观察响应无法读取或不是有效JSON。") from error
                if isinstance(result, dict) and result.get("request_id") == request_id:
                    if (result.get("protocol") != 1 or result.get("instance_id") != before["instance_id"]
                            or result.get("run_id") != before["run_id"] or result.get("domain") != domain
                            or any(type(result.get(field)) is not int for field in
                                   ("seq", "scene_generation", "observed_at_ms"))
                            or result.get("status") not in {"ok", "unsupported", "unavailable"}):
                        raise ClientError("native_observation_invalid", "原生观察响应的请求或进程身份无效。")
                    if result["status"] != "ok":
                        code = "unsupported_capability" if result["status"] == "unsupported" else "observation_unavailable"
                        raise ClientError(code, "客户端未能提供该观察领域。",
                                          {"domain": domain, "reason": result.get("error")})
                    if not isinstance(result.get("data"), dict):
                        raise ClientError("native_observation_invalid", "原生观察响应缺少领域对象。")
                    current = self._snapshot(timeout + 1)
                    if current["instance_id"] != before["instance_id"]:
                        raise ClientError("observation_identity_changed", "观察期间原生客户端实例已变化。")
                    report = cast(JsonObject, result["data"])
                    if "source" in report:
                        report["data_source"] = report["source"]
                    if domain == "inventory" and self.backend == "beidou":
                        report["native_values_valid"] = report["checksums_valid"] is True and not report["unavailable"]
                        report["validation_source"] = "native_secure_values"
                    elif domain == "character" and self.backend == "beidou":
                        report["native_values_valid"] = (report["mesos_checksum_valid"] is True
                                                         and report["skills_complete"] is True
                                                         and not report["unavailable"])
                        report["validation_source"] = "native_secure_values"
                    report.update(self.metadata(cast(JsonObject, result)))
                    report["read_seconds"] = round(time.monotonic() - started, 6)
                    return report
                if time.monotonic() >= until:
                    raise ClientError("native_observation_timeout", "原生客户端未在期限内返回观察结果。",
                                      {"domain": domain, "request_id": request_id})
                time.sleep(.01)


def observe_domain(domain: str, root: Path | None = None, backend: str | None = None) -> JsonObject:
    return NativeObserver(root, backend).observe(domain)


def content_geometry(container_id: str) -> JsonObject | None:
    tree = _docker("exec", "--user", "1000:1000", container_id,
                   "env", "DISPLAY=:97", "xwininfo", "-root", "-tree")
    windows = [match for line in tree.splitlines() if (match := re.match(
        r'^(\s*)(0x[0-9a-f]+)\s+.*?\s+(\d+)x(\d+)[+-]\d+[+-]\d+\s+([+-]\d+)([+-]\d+)\s*$', line))]
    games = [window for window in windows if '("beidou.exe" "beidou.exe")' in window[0]
             and int(window[3]) > 1 and int(window[4]) > 1]
    if len(games) != 1:
        return None
    outer = games[0]
    children = []
    for child in windows[windows.index(outer) + 1:]:
        if len(child[1]) <= len(outer[1]):
            break
        if int(child[3]) > 1 and int(child[4]) > 1:
            children.append(child)
    if not children:
        return None
    content = max(children, key=lambda child: int(child[3]) * int(child[4]))
    return {"window": content[2], "x": int(content[5]), "y": int(content[6]),
            "width": int(content[3]), "height": int(content[4])}


def project_geometry(report: JsonObject) -> JsonObject:
    """将原生游戏区坐标投影到桌面；窗口树查询不读取游戏进程内存。"""
    if report.get("backend", selected_backend()) != "beidou":
        return report
    client = report.get("client")
    if not isinstance(client, dict) or not isinstance(client.get("container_id"), str):
        raise ClientError("observation_identity_unavailable", "原生观察结果缺少当前容器身份。")
    try:
        geometry = content_geometry(client["container_id"])
    except ClientError as error:
        geometry = None
        unavailable = report.setdefault("unavailable", [])
        cast(list[JsonValue], unavailable).append(error.message)
    report["game_geometry"] = geometry

    def project(value: JsonValue) -> None:
        if isinstance(value, list):
            for item in value:
                project(item)
        elif isinstance(value, dict):
            if "game_geometry" in value:
                value["game_geometry"] = geometry
            rect = value.get("game_rect")
            if isinstance(rect, dict):
                value["root_rect"] = None if geometry is None else {
                    edge: cast(int | float, rect[edge]) + cast(int, geometry["x" if edge in {"left", "right"} else "y"])
                    for edge in ("left", "top", "right", "bottom")}
            if ("game_x" in value and "game_y" in value and "width" in value and "height" in value):
                if geometry is not None and value["game_x"] is not None and value["game_y"] is not None:
                    left = cast(int | float, value["game_x"]) + cast(int, geometry["x"])
                    top = cast(int | float, value["game_y"]) + cast(int, geometry["y"])
                    value["root_rect"] = {"left": left, "top": top,
                                          "right": left + cast(int, value["width"]),
                                          "bottom": top + cast(int, value["height"])}
                elif "root_rect" in value:
                    value["root_rect"] = None
            for key, item in list(value.items()):
                if key not in {"root_rect", "game_geometry"}:
                    project(item)

    project(report)
    if geometry is None:
        cast(list[JsonValue], report.setdefault("unavailable", [])).append("当前游戏窗口几何位置不可用，未换算桌面坐标。")
    return report
