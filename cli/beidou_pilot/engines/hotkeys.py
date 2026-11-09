"""通过原生观察API读取功能键和快捷栏，补充输入键名称。"""

import argparse
import json
from typing import Literal, TypedDict, cast

from ..observations import observe_domain, project_geometry


BindingKind = Literal["skill", "item"]


class Binding(TypedDict):
    key_code: int
    key: str | None
    type: int
    id: int


class QuickSlot(TypedDict):
    index: int
    key_code: int
    key: str | None
    local_x: int
    local_y: int


class DragObject(TypedDict):
    address: str
    vtable: str
    inventory_type: int | None
    slot: int | None


class HotkeysSnapshot(TypedDict):
    observed_at: str
    source: str
    readonly: bool
    character_id: int
    bindings: list[Binding]
    quickslots: list[QuickSlot]
    origin_x: int
    origin_y: int
    quickslots_open: bool
    drag_object: DragObject | None
    unavailable: list[str]
    not_covered: list[str]


def read_hotkeys() -> HotkeysSnapshot:
    return cast(HotkeysSnapshot, project_geometry(observe_domain("hotkeys")))


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(read_hotkeys(), ensure_ascii=False))


if __name__ == "__main__":
    main()
