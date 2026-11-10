"""真实Runtime与原生物品请求槽合同；不模拟药效或Windows调用约定。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class NativeItemUseContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        lua = root / "third_party/lua"
        sources = sorted(path for path in lua.glob("*.c")
                         if path.name not in {"lua.c", "luac.c", "ltests.c", "onelua.c"})
        subprocess.run(["gcc", "-DLUA_USE_LINUX", "-O0", "-c", *map(str, sources)], cwd=build, check=True)
        cls.executable = build / "native-item-use-contract"
        subprocess.run([
            "g++", "-std=c++20", "-O0", f"-I{lua}", f"-I{root / 'shared/lua-runtime'}",
            f"-I{root / 'beidou-ijl15/ezorsia'}", str(root / "shared/lua-runtime/Runtime.cpp"),
            str(root / "shared/lua-runtime/Observation.cpp"),
            str(root / "cli/test/native_item_use_contract.cpp"), *map(str, sorted(build.glob("*.o"))),
            "-lm", "-ldl", "-o", str(cls.executable),
        ], check=True)

    def test_world_slot_is_consumed_after_yield_and_cancellation_preserves_dispatch_facts(self) -> None:
        subprocess.run([str(self.executable), "runtime"], check=True, timeout=10)

    def test_native_callback_keeps_new_requests_and_rejects_foreign_contexts(self) -> None:
        subprocess.run([str(self.executable), "callback-identity"], check=True, timeout=10)
