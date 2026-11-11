"""读取两个客户端共用的已有角色登录配置。"""

from dataclasses import dataclass, field
import json
from pathlib import Path

from .errors import ClientError


@dataclass(frozen=True)
class LoginProfile:
    username: str = field(repr=False)
    password: str = field(repr=False)
    character_id: int
    world: int = 0
    channel: int = 0


def load_profile(path: Path) -> LoginProfile:
    try:
        if path.stat().st_mode & 0o777 != 0o600:
            raise ClientError("private_file_permissions", "登录 profile 须为 0600。")
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ClientError("profile_invalid", "登录 profile 无法读取或不是有效 JSON。") from error
    if (
        not isinstance(value, dict)
        or any(
            not isinstance(value.get(key), str) or not value[key] or any(ord(ch) < 32 for ch in value[key])
            for key in ("username", "password")
        )
        or type(value.get("character_id")) is not int
        or not 1 <= value["character_id"] <= 2**31 - 1
        or any(type(value.get(key, 0)) is not int or not 0 <= value.get(key, 0) <= 255 for key in ("world", "channel"))
    ):
        raise ClientError(
            "profile_invalid",
            "登录 profile 需要 username、password、已有角色 ID（正 int32）及 0 至 255 的整数 world/channel。",
        )
    if "max_seconds" in value:
        raise ClientError("profile_invalid", "客户端由 Docker 持续运行至关闭；请删除 profile 中的 max_seconds。")
    return LoginProfile(
        value["username"], value["password"], value["character_id"], value.get("world", 0), value.get("channel", 0)
    )
