"""Small original-format IMG files for offline parser contracts."""

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import TypeAlias


@dataclass(frozen=True)
class Vector:
    x: int
    y: int


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    children: dict[str, "ImgValue"]


@dataclass(frozen=True)
class Uol:
    path: str


ImgValue: TypeAlias = int | str | dict[str, "ImgValue"] | Vector | Canvas | Uol


def _cint(value: int) -> bytes:
    return bytes([value & 0xFF]) if -127 <= value <= 127 else b"\x80" + struct.pack("<i", value)


def _encoded_string(value: str) -> bytes:
    if value.isascii():
        encoded = value.encode("ascii")
        length = bytes([(-len(encoded)) & 0xFF]) if len(encoded) < 128 else b"\x80" + struct.pack("<I", len(encoded))
        return length + bytes(character ^ ((0xAA + index) & 0xFF) for index, character in enumerate(encoded))
    encoded = value.encode("utf-16le")
    count = len(encoded) // 2
    length = bytes([count]) if count < 127 else b"\x7f" + struct.pack("<I", count)
    words = struct.unpack("<" + "H" * count, encoded)
    return length + b"".join(struct.pack("<H", word ^ ((0xAAAA + index) & 0xFFFF))
                               for index, word in enumerate(words))


def _property_string(value: str) -> bytes:
    return b"\x73" + _encoded_string(value)


def _property_entries(properties: dict[str, ImgValue], base: int) -> bytearray:
    output = bytearray(_cint(len(properties)))
    for name, value in properties.items():
        output.extend(_property_string(name))
        if isinstance(value, int):
            output.extend(b"\x03" + _cint(value))
        elif isinstance(value, str):
            output.extend(b"\x08" + _property_string(value))
        else:
            output.extend(b"\x09")
            offset_field = len(output)
            output.extend(b"\0\0\0\0")
            nested = _extended(value, base + len(output))
            struct.pack_into("<i", output, offset_field, len(nested))
            output.extend(nested)
    return output


def _extended(value: ImgValue, base: int) -> bytearray:
    if isinstance(value, dict):
        output = bytearray(_property_string("Property") + b"\0\0")
        output.extend(_property_entries(value, base + len(output)))
        return output
    if isinstance(value, Vector):
        return bytearray(_property_string("Shape2D#Vector2D") + _cint(value.x) + _cint(value.y))
    if isinstance(value, Uol):
        return bytearray(_property_string("UOL") + b"\0" + _property_string(value.path))
    output = bytearray(_property_string("Canvas") + b"\0")
    if value.children:
        output.extend(b"\x01\0\0")
        output.extend(_property_entries(value.children, base + len(output)))
    else:
        output.extend(b"\0")
    output.extend(_cint(value.width) + _cint(value.height))
    return output


def write_img(path: Path, properties: dict[str, ImgValue]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_extended(properties, 0))
    return path
