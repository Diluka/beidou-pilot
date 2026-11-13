"""编译真实GUI运动读取器；只替换进程内存读取边界，不代表真实GUI验收。"""

from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


class GuiMotionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        cls.project = root / "beidou-ijl15/ezorsia"
        temporary = tempfile.TemporaryDirectory(prefix="gui-motion-contract-")
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        cls.executable = build / "gui-motion-contract"
        subprocess.run(
            [
                "g++",
                "-std=c++14",
                "-O0",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic",
                f"-I{root / 'shared/lua-runtime'}",
                f"-I{cls.project}",
                str(cls.project / "NativeMotion.cpp"),
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(root / "cli/test/gui_motion_contract.cpp"),
                "-o",
                str(cls.executable),
            ],
            cwd=build,
            check=True,
        )

    def test_external_native_layout_velocity_and_continuous_reference(self) -> None:
        subprocess.run([str(self.executable), "normal"], check=True, timeout=10)

    def test_missing_native_fields_keep_independent_unknowns(self) -> None:
        subprocess.run([str(self.executable), "missing"], check=True, timeout=10)

    def test_both_native_secure_layouts_authenticate_every_field(self) -> None:
        subprocess.run([str(self.executable), "checksums"], check=True, timeout=10)

    def test_nonfinite_invalid_coefficients_and_overflow_are_unknown(self) -> None:
        subprocess.run([str(self.executable), "numeric"], check=True, timeout=10)

    def test_only_read_errors_are_recovered_as_unknown(self) -> None:
        subprocess.run([str(self.executable), "boundary"], check=True, timeout=10)

    def test_windows_project_registers_the_motion_source_once(self) -> None:
        namespace = {"ms": "http://schemas.microsoft.com/developer/msbuild/2003"}
        for filename in ("ezorsia.vcxproj", "ezorsia.vcxproj.filters"):
            project = ET.parse(self.project / filename)
            for tag, source in (("ClCompile", "NativeMotion.cpp"), ("ClInclude", "NativeMotion.h")):
                entries = project.findall(f".//ms:{tag}[@Include='{source}']", namespace)
                self.assertEqual(len(entries), 1, f"{filename} includes {source} once")
