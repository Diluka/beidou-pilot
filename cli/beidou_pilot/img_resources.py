"""Read original IMG trees through the native parser shared with the headless client."""

from ctypes import CDLL, POINTER, Structure, byref, c_char_p, c_double, c_int, c_int32, c_int64, c_size_t, c_uint16, c_uint32, c_void_p, create_string_buffer, string_at
from functools import cache
import os
from pathlib import Path
import weakref
import xml.etree.ElementTree as ET

from .errors import ClientError


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


@cache
def _library() -> CDLL:
    configured = os.environ.get("BEIDOU_IMG_LIBRARY")
    root = Path(__file__).resolve().parents[2]
    candidates = [Path(configured).expanduser()] if configured else [
        root / "headless/build/libbeidou-img.so",
        root / "lib/libbeidou-img.so",
    ]
    path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise ClientError(
            "img_parser_unavailable",
            "共享 IMG 解析库不可用。",
            {"configured_library": configured, "searched": [str(candidate) for candidate in candidates]},
        )
    try:
        library = CDLL(str(path))
    except OSError as error:
        raise ClientError(
            "img_parser_unavailable", "共享 IMG 解析库无法载入。", {"path": str(path), "reason": str(error)}
        ) from error
    library.beidou_img_directory_open.argtypes = [c_char_p, c_int, POINTER(c_void_p), c_char_p, c_size_t]
    library.beidou_img_directory_open.restype = c_int
    library.beidou_img_directory_close.argtypes = [c_void_p]
    library.beidou_img_directory_close.restype = None
    library.beidou_img_directory_node_count.argtypes = [c_void_p]
    library.beidou_img_directory_node_count.restype = c_size_t
    library.beidou_img_directory_string_count.argtypes = [c_void_p]
    library.beidou_img_directory_string_count.restype = c_size_t
    library.beidou_img_directory_source_count.argtypes = [c_void_p]
    library.beidou_img_directory_source_count.restype = c_size_t
    library.beidou_img_directory_node.argtypes = [c_void_p, c_size_t, POINTER(_NodeInfo)]
    library.beidou_img_directory_node.restype = c_int
    library.beidou_img_directory_string.argtypes = [c_void_p, c_size_t, POINTER(c_size_t)]
    library.beidou_img_directory_string.restype = c_void_p
    library.beidou_img_directory_source.argtypes = [c_void_p, c_size_t, POINTER(c_size_t)]
    library.beidou_img_directory_source.restype = c_void_p
    return library


class ImgDirectory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._library = _library()
        self._handle = c_void_p()
        error = create_string_buffer(4096)
        if not self._library.beidou_img_directory_open(
            os.fsencode(path), 0, byref(self._handle), error, len(error)
        ):
            reason = error.value.decode("utf-8", errors="replace")
            raise ClientError("metadata_unreadable", "原版 IMG 目录无法读取。", {"path": str(path), "reason": reason})
        self._finalizer = weakref.finalize(self, self._library.beidou_img_directory_close, self._handle)
        self._node_count = self._library.beidou_img_directory_node_count(self._handle)
        self._string_count = self._library.beidou_img_directory_string_count(self._handle)
        self._strings: dict[int, str] = {}
        self._sources = tuple(
            Path(self._read_path(self._library.beidou_img_directory_source, index))
            for index in range(self._library.beidou_img_directory_source_count(self._handle))
        )

    def _read_path(self, getter, index: int) -> str:
        length = c_size_t()
        pointer = getter(self._handle, index, byref(length))
        return string_at(pointer, length.value).decode("utf-8")

    def _string(self, index: int) -> str:
        if index not in self._strings:
            self._strings[index] = self._read_path(self._library.beidou_img_directory_string, index)
        return self._strings[index]

    def _node(self, index: int) -> _NodeInfo:
        if index >= self._node_count:
            raise ClientError("metadata_unreadable", "原版 IMG 解析器返回了无效节点索引。", {"path": str(self.path)})
        result = _NodeInfo()
        if not self._library.beidou_img_directory_node(self._handle, index, byref(result)):
            raise ClientError("metadata_unreadable", "原版 IMG 解析器无法读取节点。", {"path": str(self.path)})
        return result

    def _find_child(self, parent: _NodeInfo, name: str) -> int | None:
        first = parent.children
        last = first + parent.child_count
        while first < last:
            middle = (first + last) // 2
            candidate = self._node(middle)
            candidate_name = self._string(candidate.name_string_id)
            if candidate_name < name:
                first = middle + 1
            else:
                last = middle
        if first == parent.children + parent.child_count:
            return None
        return first if self._string(self._node(first).name_string_id) == name else None

    def _element(self, index: int, sources: list[int]) -> ET.Element:
        node = self._node(index)
        name = self._string(node.name_string_id)
        attributes = {"name": name, "sourceOrder": str(node.source_order)}
        if node.source_file_id != 0xFFFFFFFF and node.source_file_id not in sources:
            sources.append(node.source_file_id)
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
            element.append(self._element(child, sources))
        return element

    def read_tree(self, parts: tuple[str, ...]) -> tuple[ET.Element | None, tuple[Path, ...]]:
        index = 0
        for part in parts:
            parent = self._node(index)
            child = self._find_child(parent, part)
            if child is None:
                return None, ()
            index = child
        sources: list[int] = []
        tree = self._element(index, sources)
        return tree, tuple(self._sources[source_id] for source_id in sources)
