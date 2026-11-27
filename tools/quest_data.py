#!/usr/bin/env python3
"""读取原版客户端 Quest.wz 的任务目标（击杀怪物/收集物品）与 NPC 信息。

只读原版 IMG（通过共享 libbeidou-img.so），供 `tools/bot_quest.py` 生成
"按任务条件打怪"的目标；不读取客户端运行状态。
"""

from __future__ import annotations

import argparse
from ctypes import (
    CDLL,
    POINTER,
    Structure,
    byref,
    c_char_p,
    c_double,
    c_int,
    c_int32,
    c_int64,
    c_size_t,
    c_uint16,
    c_uint32,
    c_void_p,
    create_string_buffer,
    string_at,
)
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


class QuestDataError(Exception):
    """任务资料读取失败。"""


class _NodeInfo(Structure):
    _fields_ = [
        ("name_string_id", c_uint32),
        ("children", c_uint32),
        ("value_string_id", c_uint32),
        ("source_file_id", c_uint32),
        ("source_order", c_uint32),
        ("bitmap_id", c_uint32),
        ("audio_id", c_uint32),
        ("audio_length", c_uint32),
        ("child_count", c_uint16),
        ("type", c_uint16),
        ("bitmap_width", c_uint16),
        ("bitmap_height", c_uint16),
        ("integer", c_int64),
        ("real", c_double),
        ("vector_x", c_int32),
        ("vector_y", c_int32),
    ]


def _library(path: Path | None) -> CDLL:
    candidates = (
        [path]
        if path
        else [
            Path(__file__).resolve().parents[1] / "shared/img/build/libbeidou-img.so",
            Path(__file__).resolve().parents[1] / "lib/libbeidou-img.so",
        ]
    )
    library_path = next((candidate for candidate in candidates if candidate and candidate.is_file()), None)
    if library_path is None:
        raise QuestDataError(f"共享 IMG 解析库不可用：{candidates}")
    library = CDLL(str(library_path))
    library.beidou_img_directory_open.argtypes = [c_char_p, c_int, POINTER(c_void_p), c_char_p, c_size_t]
    library.beidou_img_directory_open.restype = c_int
    library.beidou_img_directory_node_count.argtypes = [c_void_p]
    library.beidou_img_directory_node_count.restype = c_size_t
    library.beidou_img_directory_node.argtypes = [c_void_p, c_size_t, POINTER(_NodeInfo)]
    library.beidou_img_directory_node.restype = c_int
    library.beidou_img_directory_string.argtypes = [c_void_p, c_size_t, POINTER(c_size_t)]
    library.beidou_img_directory_string.restype = c_void_p
    return library


class QuestImages:
    """打开一个原版 Quest 目录并读取其中 IMG 的节点树。"""

    def __init__(self, quest_directory: Path, library_path: Path | None = None) -> None:
        self.path = quest_directory
        self._library = _library(library_path)
        self._handle = c_void_p()
        error = create_string_buffer(4096)
        if not self._library.beidou_img_directory_open(
            os.fsencode(quest_directory), 0, byref(self._handle), error, len(error)
        ):
            raise QuestDataError(f"Quest 目录无法读取：{quest_directory}（{error.value.decode(errors='replace')}）")
        self._node_count = self._library.beidou_img_directory_node_count(self._handle)

    def _string(self, index: int) -> str:
        length = c_size_t()
        pointer = self._library.beidou_img_directory_string(self._handle, index, byref(length))
        return string_at(pointer, length.value).decode("utf-8")

    def _node(self, index: int) -> _NodeInfo:
        result = _NodeInfo()
        if index >= self._node_count or not self._library.beidou_img_directory_node(self._handle, index, byref(result)):
            raise QuestDataError(f"IMG 节点读取失败：{self.path}")
        return result

    def _element(self, index: int) -> ET.Element:
        node = self._node(index)
        attributes = {"name": self._string(node.name_string_id)}
        if node.type == 1:
            element = ET.Element("long", {**attributes, "value": str(node.integer)})
        elif node.type == 2:
            element = ET.Element("double", {**attributes, "value": repr(node.real)})
        elif node.type == 3:
            element = ET.Element("string", {**attributes, "value": self._string(node.value_string_id)})
        elif node.type == 4:
            element = ET.Element("vector", {**attributes, "x": str(node.vector_x), "y": str(node.vector_y)})
        elif node.type == 5:
            element = ET.Element(
                "canvas", {**attributes, "width": str(node.bitmap_width), "height": str(node.bitmap_height)}
            )
        elif node.type == 6:
            element = ET.Element("sound", {**attributes, "length": str(node.audio_length)})
        elif node.type == 7:
            element = ET.Element("uol", {**attributes, "path": self._string(node.value_string_id)})
        else:
            element = ET.Element("imgdir", attributes)
        for child in range(node.children, node.children + node.child_count):
            element.append(self._element(child))
        return element

    def tree(self, image: str, quest_id: int) -> ET.Element | None:
        root = self._node(0)
        image_index = next(
            (
                child
                for child in range(root.children, root.children + root.child_count)
                if self._string(self._node(child).name_string_id) == image
            ),
            None,
        )
        if image_index is None:
            return None
        image_node = self._node(image_index)
        target = str(quest_id)
        quest_index = next(
            (
                child
                for child in range(image_node.children, image_node.children + image_node.child_count)
                if self._string(self._node(child).name_string_id) == target
            ),
            None,
        )
        return self._element(quest_index) if quest_index is not None else None


def _values(element: ET.Element | None) -> dict[str, str]:
    result: dict[str, str] = {}
    if element is None:
        return result
    for child in element:
        name = child.get("name")
        if name is not None and child.tag in ("string", "long", "double"):
            result[name] = child.get("value", "")
    return result


def _mobs(check: ET.Element | None) -> list[dict[str, int]]:
    mobs: list[dict[str, int]] = []
    if check is None:
        return mobs
    for stage in check:
        for container in stage:
            if container.tag == "imgdir" and container.get("name") == "mob":
                for entry in container:
                    values = {child.get("name"): child.get("value") for child in entry}
                    try:
                        mob_id = int(values.get("id", ""))
                        count = int(values.get("count", "1"))
                    except (TypeError, ValueError):
                        continue
                    mobs.append({"mob_id": mob_id, "count": count})
    return mobs


def quest_definition(images: QuestImages, quest_id: int) -> dict[str, object]:
    info = _values(images.tree("QuestInfo.img", quest_id))
    check = images.tree("Check.img", quest_id)
    act_tree = images.tree("Act.img", quest_id)
    act = _values(act_tree)
    if act_tree is not None:
        exp = next((node.get("value") for node in act_tree.iter() if node.get("name") == "exp"), None)
        if exp is not None:
            act["exp"] = exp
    npc_ids: list[int] = []
    if check is not None:
        for stage in check:
            for child in stage:
                if child.get("name") == "npc":
                    try:
                        npc_ids.append(int(child.get("value", "")))
                    except (TypeError, ValueError):
                        continue
    return {
        "quest_id": quest_id,
        "name": info.get("name"),
        "objectives": _mobs(check),
        "npc_ids": sorted(set(npc_ids)),
        "exp": int(act.get("exp", "0") or 0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("quest_id", type=int, nargs="+", help="任务 ID")
    parser.add_argument("--quest-directory", type=Path, help="原版客户端 Data/Quest 目录")
    parser.add_argument("--library", type=Path, help="libbeidou-img.so 路径")
    args = parser.parse_args(argv)
    directory = args.quest_directory or Path(
        os.environ.get(
            "QUEST_WZ",
            Path(__file__).resolve().parents[1] / "private/client-assets/client/BeiDou-Client/Data/Quest",
        )
    )
    try:
        images = QuestImages(directory, args.library)
        definitions = [quest_definition(images, quest_id) for quest_id in args.quest_id]
    except QuestDataError as error:
        print(f"任务资料读取失败：{error}", file=sys.stderr)
        return 1
    import json

    print(json.dumps(definitions, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
