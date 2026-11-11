"""通过原生观察 API 读取活动窗口、布局与键盘焦点。"""

import json
from typing import NotRequired, TypedDict, cast

from .dialog import DialogRect, DialogSnapshot
from ..observations import observe_domain, project_geometry


class ContentGeometry(TypedDict):
    x: int
    y: int
    width: int
    height: int


class UIButton(TypedDict):
    control_id: int
    layout_x: int
    layout_y: int
    width: int
    height: int
    enabled: NotRequired[bool | None]


class SkillsView(TypedDict):
    ids: list[int]
    first_index: int
    selected_tab: int
    tab_count: int


class InventoryView(TypedDict):
    first_slot: int
    selected_type: int
    expanded: bool


class UIWindow(TypedDict):
    address: str
    instance_ref: NotRequired[str]
    vtables: list[str]
    type_name: str | None
    width: int
    height: int
    game_rect: DialogRect | None
    root_rect: DialogRect | None
    buttons: list[UIButton]
    skills: SkillsView | None
    inventory: InventoryView | None


class UISnapshot(TypedDict):
    observed_at: str
    source: str
    readonly: bool
    windows: list[UIWindow]
    dialog: DialogSnapshot
    game_geometry: ContentGeometry | None
    unavailable: list[str]


def read_ui() -> UISnapshot:
    """窗口与对话来自同一次原生采样；根坐标沿用桌面窗口投影。"""
    snapshot = cast(UISnapshot, project_geometry(observe_domain("ui")))
    # The native UI report contains its dialog from the same game-thread sample.
    dialog = snapshot["dialog"]
    dialog["observed_at"] = snapshot["observed_at"]
    dialog["source"] = snapshot["source"]
    dialog["readonly"] = snapshot["readonly"]
    return snapshot


if __name__ == "__main__":
    print(json.dumps(read_ui(), ensure_ascii=False))
