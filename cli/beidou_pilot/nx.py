"""只读反序列化 PKG4 的属性与图像尺寸，供现有静态资料投影复用。"""

from functools import cache
import mmap
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

from .errors import ClientError


def read_nx(path: Path, parts: tuple[str | None, ...]) -> ET.Element | None:
    """读取一个节点子树；路径中的 None 仅匹配一层目录。"""
    try:
        with path.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if len(data) < 52:
                raise ValueError("NX header is truncated")
            magic, node_count, node_offset, string_count, string_offset = struct.unpack_from("<IIQIQ", data)
            if magic != 0x34474B50 or node_count == 0:
                raise ValueError("not a PKG4 NX file")
            if node_offset + node_count * 20 > len(data) or string_offset + string_count * 8 > len(data):
                raise ValueError("NX table is outside the file")

            @cache
            def string(index):
                if not 0 <= index < string_count:
                    raise ValueError("NX string index is outside the table")
                offset = struct.unpack_from("<Q", data, string_offset + index * 8)[0]
                if offset + 2 > len(data):
                    raise ValueError("NX string is outside the file")
                length = struct.unpack_from("<H", data, offset)[0]
                if offset + 2 + length > len(data):
                    raise ValueError("NX string is truncated")
                return data[offset + 2:offset + 2 + length].decode("utf-8")

            @cache
            def node(index):
                if not 0 <= index < node_count:
                    raise ValueError("NX node index is outside the table")
                name, start, count, kind, value = struct.unpack_from("<IIHHQ", data, node_offset + index * 20)
                if start + count > node_count or kind > 6:
                    raise ValueError("NX node has an invalid child range or type")
                return string(name), start, count, kind, value

            def select(index, remaining):
                if not remaining:
                    return index
                _, start, count, _, _ = node(index)
                for entry in range(start, start + count):
                    if remaining[0] is None or node(entry)[0] == remaining[0]:
                        found = select(entry, remaining[1:])
                        if found is not None:
                            return found
                return None

            def tree(index):
                name, start, count, kind, value = node(index)
                attributes = {"name": name}
                if kind == 1:
                    attributes["value"] = str(struct.unpack_from("<q", data, node_offset + index * 20 + 12)[0])
                elif kind == 2:
                    attributes["value"] = str(struct.unpack_from("<d", data, node_offset + index * 20 + 12)[0])
                elif kind == 3:
                    attributes["value"] = string(value & 0xFFFFFFFF)
                elif kind == 4:
                    x, y = struct.unpack_from("<ii", data, node_offset + index * 20 + 12)
                    attributes.update(x=str(x), y=str(y))
                elif kind == 5:
                    attributes.update(width=str((value >> 32) & 0xFFFF), height=str(value >> 48))
                element = ET.Element(("imgdir", "long", "double", "string", "vector", "canvas", "sound")[kind],
                                     attributes)
                element.extend(tree(entry) for entry in range(start, start + count))
                return element

            selected = select(0, parts)
            return tree(selected) if selected is not None else None
    except OSError as error:
        raise ClientError("metadata_unreadable", "本地 NX 无法读取。",
                          {"path": str(path), "reason": str(error)}) from error
    except (ValueError, struct.error) as error:
        raise ClientError("metadata_unreadable", "本地 NX 不是可读取的 PKG4 资料。",
                          {"path": str(path), "reason": str(error)}) from error
