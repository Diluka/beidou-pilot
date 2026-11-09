"""显式配置外部资源，源码目录不发现或依赖其他工作区。"""

from dataclasses import dataclass
import json
import os
from pathlib import Path

from .errors import ClientError


@dataclass(frozen=True)
class ResourcePaths:
    metadata_root: Path
    headless_resources: Path
    gui_client: Path
    gui_dll: Path
    config_file: Path | None


def load_resources(client_root: Path) -> ResourcePaths:
    root = client_root.resolve()
    defaults = {
        "metadata_root": root / "resources/wz",
        "headless_resources": root.parent / "headless/resources",
        "gui_client": root / "assets/client",
        "gui_dll": root / "assets/ijl15.dll",
    }
    configured_file = os.environ.get("MAPLE_RESOURCES_CONFIG")
    config_file = Path(configured_file).expanduser().resolve() if configured_file else root / "config/resources.json"
    if not configured_file and not config_file.is_file():
        return ResourcePaths(**defaults, config_file=None)
    try:
        configured = json.loads(config_file.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ClientError("resources_config_invalid", "资源配置无法读取或不是有效 JSON。",
                          {"path": str(config_file), "reason": str(error)}) from error
    if (not isinstance(configured, dict) or configured.keys() - defaults.keys()
            or any(not isinstance(value, str) or not value.strip() for value in configured.values())):
        raise ClientError("resources_config_invalid", "资源配置仅接受 metadata_root、headless_resources、gui_client 和 gui_dll 路径。",
                          {"path": str(config_file)})
    for name, value in configured.items():
        path = Path(value).expanduser()
        defaults[name] = (path if path.is_absolute() else config_file.parent / path).resolve()
    return ResourcePaths(**defaults, config_file=config_file)
