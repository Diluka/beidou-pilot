"""通过公共 Lua API 核对真实共享运行时，适配器仅提供原生输入与释放边界。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class LuaRuntimeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        root = Path(__file__).resolve().parents[2]
        lua = root / "third_party/lua"
        sources = sorted(path for path in lua.glob("*.c")
                         if path.name not in {"lua.c", "luac.c", "ltests.c", "onelua.c"})
        subprocess.run(["gcc", "-DLUA_USE_LINUX", "-O0", "-c", *map(str, sources)], cwd=build, check=True)
        cls.executable = build / "lua-runtime-contract"
        subprocess.run([
            "g++", "-std=c++20", "-O0", f"-I{lua}", f"-I{root / 'shared/lua-runtime'}",
            str(root / "shared/lua-runtime/Runtime.cpp"),
            str(root / "cli/test/lua_runtime_contract.cpp"), *map(str, sorted(build.glob("*.o"))),
            "-lm", "-ldl", "-o", str(cls.executable),
        ], check=True)

    def test_tasks_handoff_replan_and_cancel_without_releasing_successor(self) -> None:
        subprocess.run([str(self.executable), "collaboration"], check=True, timeout=10)

    def test_session_cancel_waits_for_native_release_and_stops_all_tasks(self) -> None:
        subprocess.run([str(self.executable), "cancel"], check=True, timeout=10)

    def test_single_script_can_move_after_stop_and_runtime_can_start_again(self) -> None:
        subprocess.run([str(self.executable), "single"], check=True, timeout=10)

    def test_raw_keys_stop_waits_for_its_release_and_preserves_successor(self) -> None:
        subprocess.run([str(self.executable), "raw-keys"], check=True, timeout=10)
