"""真实共享任务传输与Runtime合同；原生适配器替身只确认输入与释放边界。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class TaskTransportContract(unittest.TestCase):
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
        cls.executable = build / "task-transport-contract"
        subprocess.run([
            "g++", "-std=c++20", "-O0", f"-I{lua}", f"-I{root / 'shared/lua-runtime'}",
            f"-I{root / 'third_party/json/single_include'}",
            str(root / "shared/lua-runtime/Runtime.cpp"),
            str(root / "shared/lua-runtime/Observation.cpp"),
            str(root / "shared/lua-runtime/TaskTransport.cpp"),
            str(root / "cli/test/task_transport_contract.cpp"), *map(str, sorted(build.glob("*.o"))),
            "-lm", "-ldl", "-o", str(cls.executable),
        ], check=True)

    def test_add_and_stop_keep_original_session_and_wait_for_native_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([str(self.executable), "add-stop", directory], check=True, timeout=10)

    def test_foreign_and_invalid_requests_preserve_current_task_and_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run([str(self.executable), "reject", directory], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
