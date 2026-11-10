#!/usr/bin/env python3
"""通过原生观察 API 读取对话与布局；未知状态保持未知。"""
import json
from typing import Literal, NotRequired, TypedDict, cast

from ..observations import observe_domain, project_geometry


class DialogTextToken(TypedDict):
    index: int
    row: int
    text: str
    layout_x: int
    layout_y: int
    dialog_x: int
    dialog_y: int
    game_x: int | None
    game_y: int | None
    width: int
    height: int
    link_id: int | None


class DialogRect(TypedDict):
    left: int
    top: int
    right: int
    bottom: int


class DialogChoice(TypedDict):
    link_id: int
    text: str
    token_indices: list[int]
    dialog_rect: NotRequired[DialogRect]
    game_rect: NotRequired[DialogRect | None]
    root_rect: DialogRect | None
    click_validation: NotRequired[Literal['verified-observed-case', 'not-covered']]


class DialogButton(TypedDict):
    control_id: int
    width: NotRequired[int]
    height: NotRequired[int]
    layout_x: NotRequired[int | None]
    layout_y: NotRequired[int | None]
    game_x: NotRequired[int | None]
    game_y: NotRequired[int | None]
    uncalibrated_vector_x: NotRequired[int | None]
    uncalibrated_vector_y: NotRequired[int | None]
    position_source: NotRequired[str | None]
    root_rect: DialogRect | None
    click_validation: NotRequired[Literal['verified-observed-case', 'not-covered']]


class GameGeometry(TypedDict):
    window: str
    x: int
    y: int
    width: int
    height: int


class WindowLayout(TypedDict):
    layer_rect: DialogRect | None
    uncalibrated_vector_rect: DialogRect | None
    game_rect: DialogRect | None
    root_rect: DialogRect | None
    window_position_source: str | None
    buttons: list[DialogButton]


class FocusObject(TypedDict):
    address: str
    vtables: list[str]
    type_name: str | None
    type_name_source: str | None
    rtti_name: str | None


class FocusWindow(FocusObject, WindowLayout):
    width: int
    height: int


class DialogSnapshot(TypedDict):
    observed_at: str
    source: str
    readonly: bool
    dialog_open: bool | None
    script_dialog_open: NotRequired[bool | None]
    focused_talk_dialog_open: NotRequired[bool | None]
    registered_talk_dialog_open: NotRequired[bool | None]
    registered_talk_count: NotRequired[int | None]
    dialog_reference: str | None
    dialog_address: NotRequired[str | None]
    focused_window: NotRequired[FocusWindow | None]
    keyboard_handler: NotRequired[FocusObject | None]
    npc_id: int | None
    dialog_type: int | None
    layout_validation: NotRequired[Literal['native-task-text-verified']]
    button_layout_validation: NotRequired[Literal[
        'camera-translation-unavailable', 'camera-projection-verified-click-pending',
        'observed-cases-verified',
    ]]
    camera_viewport: DialogRect | None
    camera_source: NotRequired[str | None]
    layer_rect: NotRequired[DialogRect | None]
    game_rect: NotRequired[DialogRect | None]
    uncalibrated_vector_rect: NotRequired[DialogRect | None]
    root_rect: NotRequired[DialogRect | None]
    game_geometry: NotRequired[GameGeometry | None]
    window_position_source: NotRequired[str | None]
    buttons: list[DialogButton] | None
    text_tokens: NotRequired[list[DialogTextToken]]
    lines: list[str] | None
    choices: list[DialogChoice] | None
    unavailable: list[str]
    not_covered: list[str]
    npc_object_id: NotRequired[int | None]
    npc_object_id_source: NotRequired[Literal["local_request"] | None]
    page_revision: NotRequired[int]
    response_pending: NotRequired[bool]
    closed_by: NotRequired[str | None]
    text_known: NotRequired[bool]
    speaker: NotRequired[int | None]


def read_dialog() -> DialogSnapshot:
    """采集在游戏线程完成，桌面坐标仅由窗口 API 投影。"""
    return cast(DialogSnapshot, project_geometry(observe_domain("dialog")))


if __name__ == "__main__":
    print(json.dumps(read_dialog(), ensure_ascii=False))
