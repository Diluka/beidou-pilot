#!/usr/bin/env python3
"""通过客户端原生观察 API 读取怪物、NPC、掉落物和朝向。"""

import json
from typing import Literal, TypedDict

from ..observations import observe_domain


class Monster(TypedDict):
    name: str | None
    address: str | None
    object_id: int
    template_id: int | None
    x: int | float
    y: int | float
    active: bool


class Drop(TypedDict):
    address: str | None
    object_id: int
    item_id: int | None
    money: int | None
    x: int | float
    y: int | float
    landed: bool


class Facing(TypedDict):
    player_facing: Literal["Left", "Right"]
    raw_flags: int | None
    pending_dynamic: bool


class Npc(TypedDict):
    name: str | None
    address: str | None
    object_id: int
    template_id: int
    x: int | float
    y: int | float


def main() -> None:
    print(json.dumps(observe_domain("scene"), ensure_ascii=False))


if __name__ == "__main__":
    main()
