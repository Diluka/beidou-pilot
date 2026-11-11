"""通过真实 Lua 策略验证目标筛选、连续狩猎及已知失败；不模拟真实游戏效果。"""

from pathlib import Path
import subprocess
import tempfile
import unittest


class HuntLuaContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        root = Path(__file__).resolve().parents[2]
        lua = root / "third_party/lua"
        cls.executable = Path(temporary.name) / "hunt-lua"
        sources = sorted(path for path in lua.glob("*.c") if path.name not in {"ltests.c", "onelua.c"})
        subprocess.run(
            ["gcc", "-DLUA_USE_LINUX", "-O0", *map(str, sources), "-lm", "-ldl", "-o", str(cls.executable)],
            check=True,
        )
        cls.contract = root / "cli/test/hunt_contract.lua"
        cls.strategy = root / "shared/scripts/combat/hunt.lua"

    def test_selected_monsters_and_all_monsters_continue_to_next_target(self) -> None:
        for scenario in ("specified", "all", "skill"):
            with self.subTest(scenario=scenario):
                subprocess.run(
                    [str(self.executable), str(self.contract), scenario, str(self.strategy)], check=True, timeout=5
                )

    def test_rope_top_landing_without_overshoot_sample_continues_hunting(self) -> None:
        subprocess.run([str(self.executable), str(self.contract), "rope", str(self.strategy)], check=True, timeout=5)

    def test_resuming_on_a_rope_confirms_departure_before_hunting(self) -> None:
        for scenario in ("resume", "resume-top", "resume-bottom"):
            with self.subTest(scenario=scenario):
                subprocess.run(
                    [str(self.executable), str(self.contract), scenario, str(self.strategy)], check=True, timeout=5
                )

    def test_rope_recovery_stops_when_unsafe_stalled_or_preempted(self) -> None:
        for scenario in ("resume-no-endpoint", "resume-stalled", "resume-preempted", "resume-context", "resume-budget"):
            with self.subTest(scenario=scenario):
                subprocess.run(
                    [str(self.executable), str(self.contract), scenario, str(self.strategy)], check=True, timeout=5
                )

    def test_long_progressing_rope_approach_continues_to_next_platform(self) -> None:
        subprocess.run(
            [str(self.executable), str(self.contract), "rope-long-approach", str(self.strategy)], check=True, timeout=5
        )

    def test_blocked_rope_uses_an_alternative_or_reports_unreachable(self) -> None:
        for scenario in ("rope-blocked", "rope-blocked-only"):
            with self.subTest(scenario=scenario):
                subprocess.run(
                    [str(self.executable), str(self.contract), scenario, str(self.strategy)], check=True, timeout=5
                )

    def test_rope_grab_settles_horizontal_inertia_before_jumping(self) -> None:
        subprocess.run(
            [str(self.executable), str(self.contract), "rope-inertia", str(self.strategy)], check=True, timeout=5
        )

    def test_new_target_on_a_wide_platform_is_cleared_before_climbing(self) -> None:
        subprocess.run(
            [str(self.executable), str(self.contract), "wide-local-spawn", str(self.strategy)], check=True, timeout=5
        )

    def test_stalled_approach_and_scene_change_stop_without_attacking(self) -> None:
        for scenario in ("stalled", "context"):
            with self.subTest(scenario=scenario):
                subprocess.run(
                    [str(self.executable), str(self.contract), scenario, str(self.strategy)], check=True, timeout=5
                )

    def test_patrol_stays_inside_a_narrow_hunting_area(self) -> None:
        subprocess.run([str(self.executable), str(self.contract), "narrow", str(self.strategy)], check=True, timeout=5)

    def test_falling_character_can_attack_before_landing(self) -> None:
        subprocess.run([str(self.executable), str(self.contract), "fall", str(self.strategy)], check=True, timeout=5)

    def test_continuous_slope_reaches_its_real_edge_before_hunting_below(self) -> None:
        subprocess.run([str(self.executable), str(self.contract), "slope", str(self.strategy)], check=True, timeout=5)

    def test_gui_attack_lock_turns_without_attack_and_uses_combat_progress(self) -> None:
        for scenario in ("gui-lock", "gui-turn-stalled"):
            with self.subTest(scenario=scenario):
                subprocess.run(
                    [str(self.executable), str(self.contract), scenario, str(self.strategy)], check=True, timeout=5
                )
