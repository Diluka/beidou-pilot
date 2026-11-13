"""以真实 Lua 和共享 tick 引擎验证公开 API；替身仅提供原生 I/O。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class TickRuntimeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        root = Path(__file__).resolve().parents[2]
        lua = root / "third_party/lua"
        sources = sorted(
            path for path in lua.glob("*.c") if path.name not in {"lua.c", "luac.c", "ltests.c", "onelua.c"}
        )
        subprocess.run(["gcc", "-DLUA_USE_LINUX", "-O0", "-c", *map(str, sources)], cwd=build, check=True)
        cls.executable = build / "tick-runtime-contract"
        subprocess.run(
            [
                "g++",
                "-std=c++20",
                "-O0",
                "-Wall",
                "-Wextra",
                f"-I{lua}",
                f"-I{root / 'shared/lua-runtime'}",
                str(root / "shared/lua-runtime/TickRuntime.cpp"),
                str(root / "shared/lua-runtime/Runtime.cpp"),
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(root / "cli/test/tick_runtime_contract.cpp"),
                *map(str, sorted(build.glob("*.o"))),
                "-lm",
                "-ldl",
                "-o",
                str(cls.executable),
            ],
            check=True,
        )

    def run_contract(self, scenario: str) -> None:
        subprocess.run([str(self.executable), scenario], check=True, timeout=10)

    def test_file_leading_mode_and_budget_declarations_are_strict(self) -> None:
        self.run_contract("declarations")

    def test_entry_context_state_return_values_and_initial_identity(self) -> None:
        self.run_contract("entry")

    def test_domains_are_recursive_read_only_core_refreshed_and_lazy_cached(self) -> None:
        self.run_contract("domains")

    def test_only_the_final_draft_causes_native_input_and_intents_persist(self) -> None:
        self.run_contract("draft")

    def test_action_slot_idempotence_last_queue_and_pause_resume(self) -> None:
        self.run_contract("actions")

    def test_multiple_states_share_one_machine_and_cancel_only_owned_input(self) -> None:
        self.run_contract("sessions")

    def test_overrun_abort_commit_skip_and_initialization_budget(self) -> None:
        self.run_contract("budgets")

    def test_lifecycle_and_direction_release_require_native_confirmation(self) -> None:
        self.run_contract("lifecycle")

    def test_old_and_new_engines_never_share_api_or_input_lifecycle(self) -> None:
        self.run_contract("isolation")

    def test_native_callbacks_cannot_reenter_lua_or_invalidate_submission(self) -> None:
        self.run_contract("reentrancy")
