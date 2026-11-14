"""GUI 原生输入联合投放与独立 tick 生命周期合同；不模拟动画或药效。"""

from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


class TickGuiInputContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        cls.executable = build / "tick-gui-input-contract"
        lua = root / "third_party/lua"
        sources = sorted(
            path for path in lua.glob("*.c") if path.name not in {"lua.c", "luac.c", "ltests.c", "onelua.c"}
        )
        subprocess.run(["gcc", "-DLUA_USE_LINUX", "-O0", "-c", *map(str, sources)], cwd=build, check=True)
        subprocess.run(
            [
                "g++",
                "-std=c++14",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{root / 'beidou-ijl15/ezorsia'}",
                f"-I{root / 'shared/lua-runtime'}",
                f"-I{lua}",
                str(root / "shared/lua-runtime/TickRuntime.cpp"),
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(root / "cli/test/tick_gui_input_contract.cpp"),
                *map(str, sorted(build.glob("*.o"))),
                "-lm",
                "-ldl",
                "-o",
                str(cls.executable),
            ],
            check=True,
        )

    def test_legacy_single_producer_key_sequence_is_unchanged(self) -> None:
        subprocess.run([str(self.executable), "single"], check=True, timeout=10)

    def test_each_engine_releases_only_its_own_logical_keys(self) -> None:
        subprocess.run([str(self.executable), "isolation"], check=True, timeout=10)

    def test_native_keydown_callback_does_not_resume_superseded_keys(self) -> None:
        subprocess.run([str(self.executable), "reentrant-down"], check=True, timeout=10)

    def test_failed_reentrant_keyup_does_not_roll_back_new_owner(self) -> None:
        subprocess.run([str(self.executable), "reentrant-up"], check=True, timeout=10)

    def test_direction_release_requires_native_character_consumption(self) -> None:
        subprocess.run([str(self.executable), "release-fence"], check=True, timeout=10)

    def test_tick_item_and_skill_requests_are_independent(self) -> None:
        subprocess.run([str(self.executable), "slots"], check=True, timeout=10)

    def test_cancelled_action_owner_does_not_pulse_another_sessions_movement(self) -> None:
        subprocess.run([str(self.executable), "action-owner-cancel"], check=True, timeout=10)

    def test_same_held_skill_is_idempotent_and_withdrawn_replacement_never_replays(self) -> None:
        subprocess.run([str(self.executable), "held-updates"], check=True, timeout=10)

    def test_rejected_native_attack_recovers_without_lua_rewrite_and_clear_prevents_retry(self) -> None:
        subprocess.run([str(self.executable), "attack-recovery"], check=True, timeout=10)

    def test_lua_potion_churn_cannot_reset_actual_native_guard_or_delay_cancel(self) -> None:
        subprocess.run([str(self.executable), "potion-churn"], check=True, timeout=10)

    def test_done_withdraws_held_intent_before_deferred_native_consumption(self) -> None:
        subprocess.run([str(self.executable), "deferred-done"], check=True, timeout=10)

    def test_tick_budget_abort_withdraws_committed_and_uncommitted_held_intents(self) -> None:
        subprocess.run([str(self.executable), "deferred-overrun"], check=True, timeout=10)

    def test_windows_project_compiles_shared_tick_engine(self) -> None:
        root = Path(__file__).resolve().parents[2]
        namespace = {"ms": "http://schemas.microsoft.com/developer/msbuild/2003"}
        project = ET.parse(root / "beidou-ijl15/ezorsia/ezorsia.vcxproj")
        sources = {node.attrib["Include"]: node for node in project.findall(".//ms:ClCompile[@Include]", namespace)}
        tick = sources[r"..\..\shared\lua-runtime\TickRuntime.cpp"]
        self.assertEqual(tick.find("ms:PrecompiledHeader", namespace).text, "NotUsing")
        for name in ("NativeKeyUnion.h", "NativeTickInput.h", r"..\..\shared\lua-runtime\TickRuntime.h"):
            self.assertIsNotNone(project.find(f".//ms:ClInclude[@Include='{name}']", namespace))
        filters = ET.parse(root / "beidou-ijl15/ezorsia/ezorsia.vcxproj.filters")
        self.assertIsNotNone(
            filters.find(r".//ms:ClCompile[@Include='..\..\shared\lua-runtime\TickRuntime.cpp']", namespace)
        )
