"""读取两个客户端共用的已有角色登录配置。"""

from dataclasses import dataclass, field
import argparse
import json
from pathlib import Path
from typing import Literal

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


@dataclass(frozen=True)
class AccountProfile:
    """受保护的账号身份及服务器选择，不包含登录决策或建角参数。"""

    username: str = field(repr=False)
    password: str = field(repr=False)
    world: int = 0
    channel: int = 0


def load_account_profile(path: Path) -> AccountProfile:
    try:
        if path.stat().st_mode & 0o777 != 0o600:
            raise ClientError("private_file_permissions", "账号 profile 须为 0600。")
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ClientError("profile_invalid", "账号 profile 无法读取或不是有效 JSON。") from error
    if not isinstance(value, dict) or any(
        not isinstance(value.get(key), str) or not value[key] or any(ord(ch) < 32 for ch in value[key])
        for key in ("username", "password")
    ):
        raise ClientError("profile_invalid", "账号 profile 需要有效的 username 和 password。")
    if any(
        type(value.get(key, 0)) is not int or not 0 <= value.get(key, 0) <= 255
        for key in ("world", "channel")
    ):
        raise ClientError("profile_invalid", "账号 profile 的 world/channel 必须为 0 至 255 的整数。")
    return AccountProfile(value["username"], value["password"], value.get("world", 0), value.get("channel", 0))


@dataclass(frozen=True)
class LoginRequest:
    mode: Literal["character", "account"]
    character_id: int | None = None
    accept_terms: bool = False
    female: bool | None = None


def validate_login_request(request: LoginRequest) -> None:
    """无 CID 登录只进入账号阶段，不授权创建角色。"""
    if request.mode not in ("character", "account"):
        raise ClientError("login_invalid", "登录模式必须为 character 或 account。")
    if request.mode == "character":
        if type(request.character_id) is not int or not 1 <= request.character_id <= 2**31 - 1:
            raise ClientError("login_invalid", "角色登录需要正 int32 角色 ID。")
    elif request.character_id is not None:
        raise ClientError("login_invalid", "账号登录不能指定角色 ID。")
    if type(request.accept_terms) is not bool or (
        request.female is not None and type(request.female) is not bool
    ):
        raise ClientError("login_invalid", "协议同意和首次性别必须显式使用布尔值。")


@dataclass(frozen=True)
class CharacterCreation:
    name: str
    job: int
    face: int
    hair: int
    hair_color: int
    skin: int
    top: int
    bottom: int
    shoes: int
    weapon: int
    female: bool


def validate_character_creation(request: CharacterCreation) -> None:
    if not isinstance(request.name, str) or not request.name or any(ord(ch) < 32 for ch in request.name):
        raise ClientError("character_creation_invalid", "角色名不能为空或包含控制字符。")
    values = (
        request.job, request.face, request.hair, request.hair_color, request.skin,
        request.top, request.bottom, request.shoes, request.weapon,
    )
    if any(type(value) is not int or not -(2**31) <= value < 2**31 for value in values):
        raise ClientError("character_creation_invalid", "建角外观和职业必须为有符号 int32。")
    if type(request.female) is not bool:
        raise ClientError("character_creation_invalid", "建角性别必须为布尔值。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="在镜像内核对并准备本次私密 profile。")
    parser.add_argument("profile", type=Path)
    parser.add_argument("--mode", choices=("account", "character"), default="character")
    args = parser.parse_args()
    if args.mode == "account":
        account = load_account_profile(args.profile)
        print(json.dumps({"mode": "account", "world": account.world, "channel": account.channel}))
    else:
        profile = load_profile(args.profile)
        print(json.dumps({"character_id": profile.character_id, "world": profile.world, "channel": profile.channel}))
