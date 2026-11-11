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
        if self.backend != "headless" and self.name != "default":
            raise ClientError("unsupported_instance", "命名实例目前仅支持headless；北斗图形端使用default。")

    @property
    def state_directory(self) -> Path:
        return self.root / "state" if self.name == "default" else self.root / "state/instances" / self.name

    @property
    def runtime_directory(self) -> Path:
        if self.backend != "headless":
            return self.root / "runtime"
        directory = self.root / "runtime/headless"
        return directory if self.name == "default" else directory / "instances" / self.name

    @property
    def bridge(self) -> Path:
        return self.runtime_directory / "bridge"

    @property
    def runs(self) -> Path:
        return self.runtime_directory / "runs"

    @property
    def input_lock(self) -> Path:
        return self.state_directory / "maple-input.lock"
