"""通过真实 Lua 策略验证目标筛选、连续狩猎及已知失败；不模拟真实游戏效果。"""

from pathlib import Path
import subprocess
import tempfile
import unittest

from beidou_pilot.strategies import compile_strategy, read_strategy_file


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
        cls.strategy_context_contract = root / "cli/test/strategy_context_contract.lua"
        terrain = (root / "shared/scripts/travel/_terrain.lua").read_text(encoding="utf-8")
        hunt = (root / "shared/scripts/combat/hunt.lua").read_text(encoding="utf-8")
        cls.strategy = Path(temporary.name) / "hunt-with-terrain.lua"
        cls.strategy.write_text(terrain + "\n" + hunt, encoding="utf-8")

    def test_stale_entry_context_stops_recovery_before_actions(self) -> None:
        root = Path(__file__).resolve().parents[2]
        scene = {
            "instance_id": "current-instance",
            "character_id": 4,
            "map_id": 100,
            "scene_generation": 2,
            "terrain": {"status": "unavailable", "error": "hunt_terrain_unavailable"},
        }
        source, metadata = read_strategy_file(root / "shared/scripts/recovery/recover.lua")
        self.assertIsNotNone(metadata)
        options = {
            "item_id": 2000000,
            "count": 1,
            "budget_seconds": 60,
            "heals_hp": False,
            "heals_mp": False,
            "healing_known": False,
            "consume_only": False,
        }
        with tempfile.TemporaryDirectory() as temporary:
            compiled_path = Path(temporary) / "compiled.lua"
            compiled_path.write_text(compile_strategy(source, options, scene), encoding="utf-8")
            subprocess.run(
                [str(self.executable), str(self.strategy_context_contract), str(compiled_path)],
                check=True,
                timeout=5,
            )

    def test_generated_preflight_rejects_each_identity_anchor_before_main(self) -> None:
        scene = {
            "instance_id": "current-instance",
            "character_id": 4,
            "map_id": 100,
            "scene_generation": 2,
            "terrain": {"status": "unavailable", "error": "hunt_terrain_unavailable"},
        }
        source = "-- @option[type=int] marker 测试入口参数\nlocal function main(context) game.move('right') end\n"
        compiled = compile_strategy(source, {"marker": 1}, scene)
        with tempfile.TemporaryDirectory() as temporary:
            compiled_path = Path(temporary) / "compiled.lua"
            compiled_path.write_text(compiled, encoding="utf-8")
            for scenario in (
                "preflight-instance",
                "preflight-character",
                "preflight-map",
                "preflight-generation",
            ):
                with self.subTest(anchor=scenario):
                    subprocess.run(
                        [
                            str(self.executable),
                            str(self.strategy_context_contract),
                            str(compiled_path),
                            scenario,
                        ],
                        check=True,
                        timeout=5,
                    )

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

    def test_rope_recovery_stops_when_unsafe_stalled_preempted_or_scene_changed(self) -> None:
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
        for scenario in ("stalled", "context", "stale-entry"):
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
