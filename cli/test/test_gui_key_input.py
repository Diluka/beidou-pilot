"""真实Runtime与GUI输入消费核心合同；外部原生回调仅模拟消息泵与角色更新。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class GuiKeyInputContract(unittest.TestCase):
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
        cls.executable = build / "gui-key-input-contract"
        subprocess.run([
            "g++", "-std=c++20", "-O0", f"-I{lua}", f"-I{root / 'shared/lua-runtime'}",
            f"-I{root / 'beidou-ijl15/ezorsia'}", str(root / "shared/lua-runtime/Runtime.cpp"),
            str(root / "shared/lua-runtime/Observation.cpp"),
            str(root / "cli/test/gui_key_input_contract.cpp"), *map(str, sorted(build.glob("*.o"))),
            "-lm", "-ldl", "-o", str(cls.executable),
        ], check=True)

    def test_modal_native_dispatch_allows_vm_and_real_release_ack_to_progress(self) -> None:
        subprocess.run([str(self.executable), "modal"], check=True, timeout=10)

    def test_modal_cancel_and_handoff_do_not_replay_old_down_or_drop_keyups(self) -> None:
        subprocess.run([str(self.executable), "slot-changes"], check=True, timeout=10)

    def test_cancelled_or_returned_pending_requests_keep_dispatched_false(self) -> None:
        subprocess.run([str(self.executable), "undispatched"], check=True, timeout=10)
