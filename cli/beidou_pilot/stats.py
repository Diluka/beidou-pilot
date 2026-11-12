"""读取客户端原生角色属性；养成控制由共享Lua原生执行。"""

from typing import TypedDict, cast

from .backend import Backend, ClientError


class Character(TypedDict):
    id: int
    level: int
    job: int
    hp: int
    max_hp: int
    mp: int
    max_mp: int
    strength: int
    dexterity: int
    intelligence: int
    luck: int
    ability_points: int
    skill_points: int


class CharacterSnapshot(TypedDict):
    character: Character | None
    native_values_valid: bool
    unavailable: list[str]


def read_character(backend: Backend) -> Character:
    snapshot = cast(CharacterSnapshot, backend.read("observe"))
    if snapshot["native_values_valid"] is not True or snapshot["character"] is None:
        raise ClientError("character_unavailable", "当前角色属性读数不可用。",
                          {"unavailable": snapshot["unavailable"]})
    return snapshot["character"]
