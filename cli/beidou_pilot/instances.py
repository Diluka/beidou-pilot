"""客户端实例选择与其持有的运行文件。"""

from dataclasses import dataclass
import os
from pathlib import Path
import re

from .errors import ClientError


def selected_instance() -> str:
    return os.environ.get("MAPLE_INSTANCE", "default")


@dataclass(frozen=True)
class InstancePaths:
    root: Path
    backend: str = "beidou"
    name: str = "default"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", self.name):
            raise ClientError("invalid_instance", "实例名须为1至48位小写字母、数字、下划线或连字符，并以字母或数字开头。")
        if self.backend != "beidou":
            raise ClientError("unsupported_backend", "客户端后端仅为原版 GUI。")
        if self.name != "default":
            raise ClientError("unsupported_instance", "原版 GUI 仅支持 default 实例。")

    @property
    def state_directory(self) -> Path:
        return self.root / "state"

    @property
    def runtime_directory(self) -> Path:
        return self.root / "runtime"

    @property
    def bridge(self) -> Path:
        return self.runtime_directory / "bridge"

    @property
    def runs(self) -> Path:
        return self.runtime_directory / "runs"

    @property
    def input_lock(self) -> Path:
        return self.state_directory / "maple-input.lock"
