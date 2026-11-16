"""编译真实GUI运动读取器和池采集；内存/ASCII转换夹具不代表实机验收。"""

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET


class GuiMotionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[2]
        cls.project = root / "beidou-ijl15/ezorsia"
        temporary = tempfile.TemporaryDirectory(prefix="gui-motion-contract-")
        cls.addClassCleanup(temporary.cleanup)
        build = Path(temporary.name)
        cls.executable = build / "gui-motion-contract"
        # Compile the entire production collector, omitting only the unrelated
        # Windows PCH. Unused GUI equipment/native-call paths are linker-pruned;
        # motion/NPC/user traversal and typed projections are not reimplemented.
        world = build / "ObserveWorld.cpp"
        world.write_text(
            (cls.project / "ObserveWorld.cpp")
            .read_text(encoding="utf-8")
            .replace('#include "stdafx.h"', "// Windows PCH omitted in this offline build."),
            encoding="utf-8",
        )
        subprocess.run(
            [
                "g++",
                "-std=c++14",
                "-O0",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pedantic",
                "-D__cdecl=",
                "-ffunction-sections",
                "-fdata-sections",
                "-Wl,--gc-sections",
                f"-I{root / 'shared/lua-runtime'}",
                f"-I{cls.project}",
                str(cls.project / "NativeMotion.cpp"),
                str(world),
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(root / "cli/test/gui_motion_contract.cpp"),
                "-o",
                str(cls.executable),
            ],
            cwd=build,
            check=True,
        )

    def test_external_native_layout_velocity_and_continuous_reference(self) -> None:
        subprocess.run([str(self.executable), "normal"], check=True, timeout=10)

    def test_missing_native_fields_keep_independent_unknowns(self) -> None:
        subprocess.run([str(self.executable), "missing"], check=True, timeout=10)

    def test_both_native_secure_layouts_authenticate_every_field(self) -> None:
        subprocess.run([str(self.executable), "checksums"], check=True, timeout=10)

    def test_nonfinite_invalid_coefficients_and_overflow_are_unknown(self) -> None:
        subprocess.run([str(self.executable), "numeric"], check=True, timeout=10)

    def test_only_read_errors_are_recovered_as_unknown(self) -> None:
        subprocess.run([str(self.executable), "boundary"], check=True, timeout=10)

    def test_physical_pose_is_the_unrounded_vector_point_not_the_display_cache(self) -> None:
        subprocess.run([str(self.executable), "physics"], check=True, timeout=10)

    def test_unreadable_pose_fields_stay_unknown_without_zero_or_display_fill(self) -> None:
        subprocess.run([str(self.executable), "physics-unknowns"], check=True, timeout=10)

    def test_repeated_host_frames_reuse_one_physics_sample_and_update_id(self) -> None:
        subprocess.run([str(self.executable), "physics-cache"], check=True, timeout=10)

    def test_each_entity_kind_owns_its_velocity_and_measured_zero(self) -> None:
        subprocess.run([str(self.executable), "entities"], check=True, timeout=10)

    def test_every_object_primary_vector_and_com_type_is_authenticated(self) -> None:
        subprocess.run([str(self.executable), "entity_types"], check=True, timeout=10)

    def test_each_kind_rejects_bad_payloads_without_fallback(self) -> None:
        subprocess.run([str(self.executable), "entity_payloads"], check=True, timeout=10)

    def test_typed_npc_uses_real_shared_collection_and_cached_position(self) -> None:
        subprocess.run([str(self.executable), "npcs"], check=True, timeout=10)

    def test_remote_player_collection_uses_its_own_primary_vector(self) -> None:
        subprocess.run([str(self.executable), "players"], check=True, timeout=10)

    def test_one_npc_collector_and_explicit_projectile_unknown(self) -> None:
        world = (self.project / "ObserveWorld.cpp").read_text(encoding="utf-8")
        bridge = (self.project / "AgentBridge.cpp").read_text(encoding="utf-8")
        self.assertEqual(world.count("Read<Address>(0x00BED780)"), 2)  # before/after one traversal
        self.assertEqual(world.count("for (const auto& record : NpcRecords())"), 1)
        self.assertEqual(world.count("for (auto& record : NpcRecords())"), 1)
        self.assertIn("NativeObservation::Npcs(state.npcs)", bridge)
        self.assertIn('{"projectiles", Value{}}', world)
        self.assertIn('{"projectiles", false}', world)
        self.assertIn(r"\"projectiles\":false", bridge)
        self.assertIn(r"\"projectiles\":null,\"projectiles_complete\":null", bridge)
        self.assertIn("NativeDropDestination", world)
        self.assertIn("NativeDropDestination", bridge)
        # Bridge wiring: failed real traversal must leave membership unknown.
        players = bridge.split("state.playersKnown = false;", 1)[1].split("NativeObservation::Npcs", 1)[0]
        self.assertLess(players.index("NativeObservation::Players"), players.index("state.playersKnown = true;"))
        self.assertNotIn("state.playersKnown = state.ready", bridge)

    def test_production_published_character_section_is_valid_entity_owned_json(self) -> None:
        # Execute the unchanged production serialization section, not a rewrite;
        # unrelated Windows publication/I/O is outside this portable contract.
        bridge = (self.project / "AgentBridge.cpp").read_text(encoding="utf-8")
        section = bridge.split(r'out << ",\"character\":";', 1)[1].split(r'out << ",\"position\":";', 1)[0]
        build = self.executable.parent
        source = build / "published-character.cpp"
        source.write_text(
            "\n".join(
                [
                    '#include "Contract.h"',
                    "#include <array>",
                    "#include <iostream>",
                    "#include <sstream>",
                    "int main(int argc, char**) {",
                    "MapleControl::State state; state.characterKnown = argc != 2;",
                    'state.character.id = 7; state.character.name = "observer";',
                    "state.character.SetPosition(10.5, -2.25);",
                    "state.character.velocity.source = MapleControl::MotionVector::Source::Native;",
                    "state.character.velocity.x = 123.5;",
                    "state.character.movement.known = true; state.character.movement.maxSpeed = 160;",
                    "state.character.physics.known = argc == 1;",
                    "state.character.physics.updateIdKnown = true;",
                    "state.character.physics.updateId = 12;",
                    "state.character.physics.stepMsKnown = true;",
                    "state.character.physics.stepMs = 30;",
                    "state.character.physics.positionKnown = argc == 1;",
                    "state.character.physics.x = 2147.125;",
                    "state.character.physics.y = 1239.0;",
                    "state.character.physics.velocityKnown = argc == 1;",
                    "state.character.physics.velocityX = 125.0;",
                    "state.character.physics.velocityY = 0.0;",
                    "state.character.physics.onGround = MapleControl::Fact::True;",
                    'std::ostringstream out; out << "{\\"character\\":";',
                    section,
                    "out << '}'; std::cout << out.str(); }",
                ]
            ),
            encoding="utf-8",
        )
        executable = build / "published-character"
        root = self.project.parents[1]
        subprocess.run(
            [
                "g++",
                "-std=c++14",
                f"-I{root / 'shared/lua-runtime'}",
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(source),
                "-o",
                str(executable),
            ],
            check=True,
        )
        character = json.loads(subprocess.check_output([str(executable)], text=True))["character"]
        self.assertEqual((7, 10.5, -2.25), (character["id"], character["x"], character["y"]))
        self.assertEqual(123.5, character["velocity"]["x"])
        self.assertEqual(160, character["movement"]["max_speed"])
        # The display cache and the whole physics record are distinct reference points.
        physics = character["physics"]
        self.assertNotEqual((character["x"], character["y"]), (physics["x"], physics["y"]))
        self.assertEqual((12, 30), (physics["update_id"], physics["step_ms"]))
        self.assertEqual((2147.125, 1239.0), (physics["x"], physics["y"]))
        self.assertEqual({"x": 125.0, "y": 0.0}, physics["velocity"])
        self.assertIs(True, physics["on_ground"])
        self.assertIsNone(json.loads(subprocess.check_output([str(executable), "unknown"], text=True))["character"])
        # A known character without a native update still publishes an unknown record.
        without_sample = json.loads(
            subprocess.check_output([str(executable), "known", "no-physics-sample"], text=True)
        )["character"]
        self.assertEqual(7, without_sample["id"])
        self.assertIsNone(without_sample["physics"])

    def test_gui_pose_cache_is_the_single_source_for_state_and_cli_character(self) -> None:
        bridge = (self.project / "AgentBridge.cpp").read_text(encoding="utf-8")
        character = (self.project / "ObserveCharacter.cpp").read_text(encoding="utf-8")
        motion = (self.project / "NativeMotion.cpp").read_text(encoding="utf-8")
        hook = bridge.split("void AgentBridge::CharacterUpdated", 1)[1].split("\n}", 1)[0]
        self.assertIn("++characterUpdates;", hook)
        self.assertIn("NativeMotion::RecordLocalPhysics(current, characterUpdates);", hook)
        capture = bridge.split("state.characterUpdatesKnown =", 1)[1].split("state.actionIdle", 1)[0]
        self.assertIn("NativeMotion::CachedLocalPhysics()", capture)
        self.assertIn("physics.user == native.user", capture)
        self.assertNotIn("CapturePhysics", capture)
        self.assertEqual(1, bridge.count("NativeMotion::RecordLocalPhysics("))
        self.assertIn('character["physics"] = state.character.physics.Document();', bridge)
        self.assertEqual(1, character.count("NativeMotion::CachedLocalPhysics()"))
        self.assertIn('result["physics"] = physics.pose.Document();', character)
        # One capture reads the whole sample from the same verified VecCtrl.
        self.assertEqual(1, motion.count("ZtlDouble(vector + 0x20)"))
        self.assertEqual(1, motion.count("ZtlDouble(vector + 0x38)"))
        self.assertIn("pose.stepMs = 30;", motion)

    def test_windows_project_registers_the_motion_source_once(self) -> None:
        namespace = {"ms": "http://schemas.microsoft.com/developer/msbuild/2003"}
        for filename in ("ezorsia.vcxproj", "ezorsia.vcxproj.filters"):
            project = ET.parse(self.project / filename)
            for tag, source in (("ClCompile", "NativeMotion.cpp"), ("ClInclude", "NativeMotion.h")):
                entries = project.findall(f".//ms:{tag}[@Include='{source}']", namespace)
                self.assertEqual(len(entries), 1, f"{filename} includes {source} once")
                if filename == "ezorsia.vcxproj" and source == "NativeMotion.cpp":
                    self.assertEqual(entries[0].find("ms:PrecompiledHeader", namespace).text, "NotUsing")
