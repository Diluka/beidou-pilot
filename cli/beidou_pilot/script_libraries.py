"""显式组合公共 Lua 函数与消费者源码；不解释或执行路线。"""

from pathlib import Path

from .errors import ClientError
from .strategies import split_script_header


def with_library(name: str, path: Path | None, code: str | None) -> str:
    if name not in {"travel", "island-supply"}:
        raise ClientError("unknown_script_library", "未知的公共 Lua 函数库。")
    if (path is None) == (code is None):
        raise ClientError("invalid_bridge_options", "Lua文件与直接源码须且只能提供一项。")
    try:
        source = path.read_text(encoding="utf-8") if path is not None else code
    except (OSError, UnicodeError) as error:
        raise ClientError(
            "invalid_script_file", "无法读取UTF-8 Lua消费者，未发布执行请求。", {"reason": str(error)}
        ) from error
    directory = Path(__file__).resolve().parents[2] / "shared/scripts"
    try:
        common = (directory / "travel/_common.lua").read_text(encoding="utf-8")
        route = (directory / "travel/_route.lua").read_text(encoding="utf-8")
        example = (
            (directory / "examples/island_supply.lua").read_text(encoding="utf-8") if name == "island-supply" else ""
        )
    except (OSError, UnicodeError) as error:
        raise ClientError(
            "strategy_script_unavailable", "无法装载公共 Lua 函数库，未发布执行请求。", {"reason": str(error)}
        ) from error
    header, body = split_script_header(str(source))
    return (
        header
        + ("\n" if header and not header.endswith("\n") else "")
        + "local travel\ndo\nlocal options\n"
        + common
        + "\n"
        + route
        + "\nend\n"
        + example
        + "\n"
        + body
    )
