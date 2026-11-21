"""本容器的启动身份；运行数据不依赖宿主 Docker 或开发源码。"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import TypedDict, cast

from .errors import ClientError
from .profile import LoginProfile


class TargetConfig(TypedDict):
    project: str
    service: str
    network: str


@dataclass(frozen=True)
class ContainerRuntime:
    backend: str
    instance: str
    run_id: str
    container_id: str
    image: str
    source_revision: str
    pid: int
    run_dir: Path
    character_id: int | None
    world: int
    channel: int
    target: TargetConfig
    target_ip: str
    target_container_id: str
    started_at: str

    @property
    def running(self) -> bool:
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # GUI 初始化后才降权；无权限发送信号仍证明该进程存在。
            return True
        return True

    def verify_request(self, profile: LoginProfile, server: Path | None = None) -> None:
        if server is not None:
            try:
                requested = json.loads(server.read_text())
            except (OSError, ValueError) as error:
                raise ClientError("server_unreadable", "无法读取服务器配置，保留本容器。") from error
            if (
                not isinstance(requested, dict)
                or not {"project", "service"}.issubset(requested)
                or requested.keys() - {"project", "service", "network"}
                or any(not isinstance(value, str) or not value for value in requested.values())
            ):
                raise ClientError("server_invalid", "服务器配置须提供 project、service，可选 network。")
            if (
                any(requested[key] != self.target[key] for key in ("project", "service"))
                or "network" in requested
                and requested["network"] != self.target["network"]
            ):
                raise ClientError("server_mismatch", "本容器的服务器与请求不同，未切换客户端。")


def load_runtime(root: Path, backend: str, instance: str = "default") -> ContainerRuntime:
    try:
        value = json.loads((root / "state/container.json").read_text())
    except (OSError, ValueError) as error:
        raise ClientError("container_runtime_unavailable", "请通过 Docker 工作台入口执行客户端 CLI。") from error
    if (
        value["backend"] != backend
        or value["instance"] != instance
        or value["run_id"] != os.environ.get("RUN_ID")
        or value["container_id"] != os.environ.get("HOSTNAME", value["container_id"])
    ):
        raise ClientError("container_identity_changed", "请求实例或启动登记不属于当前容器。")
    return ContainerRuntime(
        value["backend"],
        value["instance"],
        value["run_id"],
        value["container_id"],
        value["image"],
        value["source_revision"],
        value["pid"],
        Path(value["run_dir"]),
        value["character_id"],
        value["world"],
        value["channel"],
        cast(TargetConfig, value["target"]),
        value["target_ip"],
        value["target_container_id"],
        value["started_at"],
    )
