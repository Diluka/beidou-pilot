"""V17动作忙闲纯读与真实GUI持有核心合同；不替代原版实机验收。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class NativeActionStateContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory(prefix="native-action-state-")
        cls.addClassCleanup(temporary.cleanup)
        cls.executable = Path(temporary.name) / "native-action-state-contract"
        subprocess.run(
            [
                "g++",
                "-std=c++14",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic",
                f"-I{root / 'beidou-ijl15/ezorsia'}",
                f"-I{root / 'shared/lua-runtime'}",
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(root / "cli/test/native_action_state_contract.cpp"),
                "-o",
                str(cls.executable),
            ],
            check=True,
        )

    def run_contract(self, scenario: str) -> None:
        subprocess.run([str(self.executable), scenario], check=True, timeout=10)

    def test_native_action_sign_frame_end_clear_and_invalid_local_user(self) -> None:
        self.run_contract("state")

    def test_repeat_uses_current_original_input_settings_and_no_fallback(self) -> None:
        self.run_contract("native-repeat")

    def test_current_intent_never_relabels_or_clears_started_animation(self) -> None:
        self.run_contract("intent")

    def test_same_value_no_lock_skill_and_unknown_never_create_replays(self) -> None:
        self.run_contract("no-lock")

    def test_native_repeat_and_potion_guard_are_independent_of_lua_frequency(self) -> None:
        self.run_contract("repeat")

    def test_held_action_change_and_clear_require_native_consumption(self) -> None:
        self.run_contract("fences")

    def test_actual_potion_calls_stay_spaced_across_replace_clear_other_actions_and_cancel(self) -> None:
        self.run_contract("potion-native")

    def test_unstarted_native_attack_and_rejected_skill_recover_without_lua_rewrite(self) -> None:
        self.run_contract("attack-retry")
