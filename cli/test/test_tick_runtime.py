"""以真实 Lua 和共享 tick 引擎验证公开 API；替身仅提供原生 I/O。"""

from pathlib import Path
import subprocess
import tempfile
import unittest

from beidou_pilot.strategies import compile_strategy, parse_options, read_strategy_file, split_script_header


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

    def test_gears_share_current_core_without_sampling_non_due_frames(self) -> None:
        self.run_contract("cadence")

    def test_absolute_phase_actual_callback_time_and_missed_periods_inside_main(self) -> None:
        self.run_contract("cadence-phase")

    def test_native_consumption_cancel_deadline_release_and_scene_advance_when_main_is_not_due(self) -> None:
        self.run_contract("cadence-lifecycle")

    def test_entry_context_state_return_values_and_initial_identity(self) -> None:
        self.run_contract("entry")

    def test_scene_tracks_two_maps_and_same_map_reentry_without_losing_caller_context(self) -> None:
        self.run_contract("scene-continuity")

    def test_scene_is_shared_across_gears_without_reading_during_transition_or_replaying_input(self) -> None:
        self.run_contract("scene-cadence")

    def test_new_scene_replanning_preserves_native_a_and_never_replays_withdrawn_input_b(self) -> None:
        self.run_contract("scene-held-intents")

    def test_scene_reports_missing_reference_error_and_wrong_map_without_old_geometry(self) -> None:
        self.run_contract("scene-unavailable")

    def test_strategy_file_and_direct_code_receive_native_scene_without_session_restart(self) -> None:
        body = """local function main(context)
  local c=context
  local s=c.scene
  assert(s.map_id==c.game.world.map_id and s.scene_generation==c.tick.scene_generation)
  assert(s.terrain.status=='available' and s.terrain.source=='local-IMG-contract')
  assert(c.game.terrain==nil)
  if c.options then assert(c.options.goal==50001 and c.route.goal==50001 and c.custom=='keep') end
  if c.tick.index==1 then
    assert(s.map_id==50000 and s.terrain.footholds[1].x1==10)
    c.state.route_index=2
    c.game.player.move('up')
  else
    assert(s.map_id==50001 and s.terrain.footholds[1].x1==20 and c.state.route_index==2)
    return 'done'
  end
end
"""
        header = "-- @mode tick\n-- @tick.gear 4\n-- @option[type=int,min=1] goal destination\n"
        policy = self.executable.parent / "scene-policy.lua"
        policy.write_text(header + body, encoding="utf-8")
        source, metadata = read_strategy_file(policy)
        self.assertIsNotNone(metadata)
        options = parse_options(metadata, ["--goal", "50001"])
        scene = {"instance_id": "tick-contract", "character_id": 1, "map_id": 50000, "scene_generation": 1}
        entries = {
            "file": compile_strategy(source, options, scene, {"route": {"goal": 50001}, "custom": "keep"}),
            "code": header + body.replace("local function main", "function main", 1),
        }
        for entry, compiled_source in entries.items():
            with self.subTest(entry=entry):
                script = self.executable.parent / ("scene-" + entry + ".lua")
                script.write_text(compiled_source, encoding="utf-8")
                subprocess.run([str(self.executable), "scene-script", str(script)], check=True, timeout=10)

    def test_domains_are_recursive_read_only_core_refreshed_and_lazy_cached(self) -> None:
        self.run_contract("domains")

    def test_only_the_final_draft_causes_native_input_and_intents_persist(self) -> None:
        self.run_contract("draft")

    def test_held_inputs_persist_and_same_value_never_represses_or_replays_native_updates(self) -> None:
        self.run_contract("held-intents")

    def test_busy_native_a_accepts_b_and_withdrawn_b_is_never_replayed_before_c(self) -> None:
        self.run_contract("actions")

    def test_busy_and_action_idle_preserve_native_true_false_and_unknown_independent_of_intent(self) -> None:
        self.run_contract("idle-facts")

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

    def test_profile_counts_idle_active_and_transition_frames_without_sampling_when_idle(self) -> None:
        self.run_contract("profiling")

    def test_directory_package_modules_load_with_sources_and_line_attribution(self) -> None:
        self.run_contract("packages")

    def test_motion_facts_and_reference_capabilities_are_fresh_read_only_and_unknown_when_missing(self) -> None:
        self.run_contract("motion")

    def test_held_skill_example_returns_done_and_runtime_confirms_release_without_waiting_for_animation(self) -> None:
        path = Path(__file__).resolve().parents[2] / "shared/scripts/examples/tick-held-skill.lua"
        source, metadata = read_strategy_file(path)
        self.assertIsNotNone(metadata)
        self.assertEqual("tick", metadata.mode)
        header, body = split_script_header(source)
        source = header + "-- @tick.gear 4\n" + body
        scene = {"instance_id": "tick-contract", "character_id": 1, "map_id": 50000, "scene_generation": 1}
        compiled = self.executable.parent / "tick-held-skill-compiled.lua"
        compiled.write_text(
            compile_strategy(source, {"skill_id": 1001004, "hold_seconds": 0.1}, scene), encoding="utf-8"
        )
        subprocess.run([str(self.executable), "held-skill-example", str(compiled)], check=True, timeout=10)

    def test_moving_jump_attack_example_holds_direction_until_landing(self) -> None:
        path = Path(__file__).resolve().parents[2] / "shared/scripts/examples/tick-jump-attack.lua"
        source, metadata = read_strategy_file(path)
        self.assertIsNotNone(metadata)
        self.assertEqual("tick", metadata.mode)
        self.assertEqual(3, metadata.execution.gear)
        # This behavior fixture advances native frames without wall-clock waits.
        header, body = split_script_header(source)
        source = header + "-- @tick.gear 4\n" + body
        scene = {"instance_id": "tick-contract", "character_id": 1, "map_id": 50000, "scene_generation": 1}
        for arguments, direction in (([], "right"), (["--direction", "left"], "left")):
            with self.subTest(arguments=arguments):
                options = parse_options(metadata, arguments)
                self.assertEqual({"direction": direction}, options)
                compiled = self.executable.parent / "tick-jump-attack-compiled.lua"
                compiled.write_text(compile_strategy(source, options, scene), encoding="utf-8")
                subprocess.run(
                    [str(self.executable), "jump-attack-example", str(compiled), direction],
                    check=True,
                    timeout=10,
                )
