"""Restricted single-IMG C API contracts using original-format offline fixtures."""

from contextlib import contextmanager
from ctypes import CDLL, POINTER, byref, c_char_p, c_int, c_size_t, c_void_p, create_string_buffer, string_at
from pathlib import Path
import subprocess
import tempfile
import unittest

from beidou_pilot.img_resources import _NodeInfo
from test.img_fixture import Uol, write_img


class ImgFileContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="img-file-contract-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        root = Path(__file__).resolve().parents[2]
        library = cls.directory / "libbeidou-img.so"
        subprocess.run(
            [
                "g++",
                "-std=c++17",
                "-O2",
                "-fPIC",
                "-shared",
                str(root / "headless/src/ImgResources.cpp"),
                str(root / "headless/src/ImgKeys.cpp"),
                "-o",
                str(library),
            ],
            check=True,
            cwd=cls.directory,
            timeout=90,
        )
        cls.library = CDLL(str(library))
        cls.library.beidou_img_file_open.argtypes = [c_char_p, POINTER(c_void_p), c_char_p, c_size_t]
        cls.library.beidou_img_file_open.restype = c_int
        cls.library.beidou_img_directory_open.argtypes = [c_char_p, c_int, POINTER(c_void_p), c_char_p, c_size_t]
        cls.library.beidou_img_directory_open.restype = c_int
        cls.library.beidou_img_directory_close.argtypes = [c_void_p]
        cls.library.beidou_img_directory_close.restype = None
        cls.library.beidou_img_directory_node.argtypes = [c_void_p, c_size_t, POINTER(_NodeInfo)]
        cls.library.beidou_img_directory_node.restype = c_int
        for name in ("node_count", "source_count"):
            function = getattr(cls.library, "beidou_img_directory_" + name)
            function.argtypes = [c_void_p]
            function.restype = c_size_t
        for name in ("string", "source"):
            function = getattr(cls.library, "beidou_img_directory_" + name)
            function.argtypes = [c_void_p, c_size_t, POINTER(c_size_t)]
            function.restype = c_void_p

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(dir=self.directory)
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name)

    @contextmanager
    def opened(self, path: Path, *, directory: bool = False):
        handle = c_void_p()
        error = create_string_buffer(1024)
        arguments = [str(path).encode(), byref(handle), error, len(error)]
        if directory:
            opened = self.library.beidou_img_directory_open(arguments[0], 0, *arguments[1:])
        else:
            opened = self.library.beidou_img_file_open(*arguments)
        self.assertEqual(1, opened, error.value.decode())
        try:
            yield handle
        finally:
            self.library.beidou_img_directory_close(handle)

    def node(self, handle, index: int) -> _NodeInfo:
        node = _NodeInfo()
        self.assertEqual(1, self.library.beidou_img_directory_node(handle, index, byref(node)))
        return node

    def text(self, handle, index: int, *, source: bool = False) -> str:
        length = c_size_t()
        function = self.library.beidou_img_directory_source if source else self.library.beidou_img_directory_string
        pointer = function(handle, index, byref(length))
        self.assertIsNotNone(pointer)
        return string_at(pointer, length.value).decode()

    def child(self, handle, parent: int, name: str) -> int:
        node = self.node(handle, parent)
        return next(
            index
            for index in range(node.children, node.children + node.child_count)
            if self.text(handle, self.node(handle, index).name_string_id) == name
        )

    def test_single_file_has_image_root_and_only_its_actual_source(self) -> None:
        source = write_img(self.data / "000050000.img", {"info": {"link": 50001}, "x": -45})
        write_img(self.data / "000050001.img", {"x": 999})
        (self.data / "broken.img").write_bytes(b"PKG4")
        with self.opened(source) as handle:
            self.assertEqual("000050000.img", self.text(handle, self.node(handle, 0).name_string_id))
            self.assertEqual(-45, self.node(handle, self.child(handle, 0, "x")).integer)
            self.assertEqual(1, self.library.beidou_img_directory_source_count(handle))
            self.assertEqual(str(source), self.text(handle, 0, source=True))
            for index in range(self.library.beidou_img_directory_node_count(handle)):
                self.assertEqual(0, self.node(handle, index).source_file_id)
        # The directory API still visits the broken sibling and fails, proving
        # that single-file success is not a changed global directory policy.
        handle = c_void_p()
        error = create_string_buffer(1024)
        self.assertEqual(
            0, self.library.beidou_img_directory_open(str(self.data).encode(), 0, byref(handle), error, len(error))
        )
        self.assertIsNone(handle.value)
        self.assertTrue(error.value)

    def test_internal_uol_resolves_but_external_uol_cannot_read_siblings(self) -> None:
        source = write_img(
            self.data / "a.img",
            {
                "target": {"x": 42},
                "alias": Uol("target"),
                "external": Uol("../b.img/target"),
            },
        )
        write_img(self.data / "b.img", {"target": {"x": 888}})
        with self.opened(source) as handle:
            alias = self.child(handle, 0, "alias")
            self.assertEqual(42, self.node(handle, self.child(handle, alias, "x")).integer)
            external = self.node(handle, self.child(handle, 0, "external"))
            self.assertEqual(7, external.type)
            self.assertEqual("../b.img/target", self.text(handle, external.value_string_id))
            self.assertEqual(1, self.library.beidou_img_directory_source_count(handle))

    def test_existing_directory_api_keeps_cross_image_resolution(self) -> None:
        write_img(self.data / "a.img", {"external": Uol("../b.img/target")})
        write_img(self.data / "b.img", {"target": {"x": 888}})
        with self.opened(self.data, directory=True) as handle:
            image = self.child(handle, 0, "a.img")
            target = self.child(handle, image, "external")
            value = self.node(handle, self.child(handle, target, "x"))
            self.assertEqual(888, value.integer)
            self.assertEqual(str(self.data / "b.img"), self.text(handle, value.source_file_id, source=True))
            self.assertEqual(2, self.library.beidou_img_directory_source_count(handle))

    def test_missing_empty_wrong_kind_and_invalid_img_fail_explicitly(self) -> None:
        empty = self.data / "empty.img"
        empty.write_bytes(b"")
        invalid = self.data / "invalid.img"
        invalid.write_bytes(b"PKG4")
        other = write_img(self.data / "other.bin", {"x": 1})
        for source in (self.data / "missing.img", self.data, empty, invalid, other):
            with self.subTest(source=source.name):
                handle = c_void_p()
                error = create_string_buffer(1024)
                self.assertEqual(
                    0, self.library.beidou_img_file_open(str(source).encode(), byref(handle), error, len(error))
                )
                self.assertIsNone(handle.value)
                self.assertTrue(error.value)


if __name__ == "__main__":
    unittest.main()
