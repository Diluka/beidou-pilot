"""Exercise AutoAp session arbitration through the shared tick runtime."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class AutoApRuntimeArbitration(unittest.TestCase):
    def test_shared_draft_arbitration(self) -> None:
        root = Path(__file__).resolve().parents[2]
        lua = root / "third_party/lua"
        sources = sorted(path for path in lua.glob("*.c")
                         if path.name not in {"lua.c", "luac.c", "ltests.c", "onelua.c"})
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            subprocess.run(["gcc", "-DLUA_USE_LINUX", "-O0", "-c", *map(str, sources)], cwd=build, check=True)
            executable = build / "auto-ap-runtime"
            subprocess.run([
                "g++", "-std=c++14", "-Wall", "-Wextra", "-Werror",
                f"-I{root / 'beidou-ijl15/ezorsia'}", f"-I{root / 'shared/lua-runtime'}", f"-I{lua}",
                str(root / "shared/lua-runtime/TickRuntime.cpp"),
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(root / "beidou-ijl15/tests/native_auto_ap_runtime_contract.cpp"),
                *map(str, sorted(build.glob("*.o"))), "-lm", "-ldl", "-o", str(executable),
            ], check=True)
            subprocess.run([str(executable)], check=True, timeout=10)
