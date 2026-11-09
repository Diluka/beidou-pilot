#!/usr/bin/env python3
"""通过原生观察API读取角色金币与技能记录。"""

import argparse
import json
from typing import TypedDict, cast

from ..observations import observe_domain


class LearnedSkill(TypedDict):
    level: int
    master_level: int | None


class CharacterSnapshot(TypedDict):
    observed_at: str
    source: str
    readonly: bool
    character_id: int
    mesos: int | None
    mesos_checksum_valid: bool | None
    native_values_valid: bool
    skills: dict[str, LearnedSkill]
    skills_complete: bool
    unavailable: list[str]
    not_covered: list[str]
    read_seconds: float


def read_character() -> CharacterSnapshot:
    return cast(CharacterSnapshot, observe_domain("character"))


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(read_character(), ensure_ascii=False))


if __name__ == '__main__':
    main()
