#!/usr/bin/env python3
"""读取当前原生交互页面；控件引用保持原样。"""

import json
from typing import TypedDict, cast

from ..observations import observe_domain


class InteractionControl(TypedDict):
    role: str
    text: str
    enabled: bool | None
    ref: str


class InteractionPage(TypedDict):
    source: str
    title: str
    text: str | None
    controls: list[InteractionControl] | None


class InteractionSnapshot(TypedDict):
    page: InteractionPage | None


def read_interaction() -> InteractionSnapshot:
    return cast(InteractionSnapshot, observe_domain("interaction"))


if __name__ == "__main__":
    print(json.dumps(read_interaction(), ensure_ascii=False))
