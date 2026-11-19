"""Exercise AutoAp session arbitration through the shared tick runtime."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from beidou_pilot.auto_ap import auto_ap
from beidou_pilot.errors import ClientError
from beidou_pilot.strategies import compile_strategy


class AutoApRuntimeArbitration(unittest.TestCase):
    def test_shared_draft_arbitration(self) -> None:
        root = Path(__file__).resolve().parents[2]
        lua = root / "third_party/lua"
        sources = sorted(path for path in lua.glob("*.c")
                         if path.name not in {"lua.c", "luac.c", "ltests.c", "onelua.c"})
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            subprocess.run(["gcc", "-DLUA_USE_LINUX", "-O0", "-c", *map(str, sources)], cwd=build, check=True)
            executable = build / "auto-ap-runtime"
            subprocess.run([
                "g++", "-std=c++14", "-Wall", "-Wextra", "-Werror",
                f"-I{root / 'beidou-ijl15/ezorsia'}", f"-I{root / 'shared/lua-runtime'}", f"-I{lua}",
                str(root / "shared/lua-runtime/TickRuntime.cpp"),
                str(root / "shared/lua-runtime/Observation.cpp"),
                str(root / "beidou-ijl15/tests/native_auto_ap_runtime_contract.cpp"),
                *map(str, sorted(build.glob("*.o"))), "-lm", "-ldl", "-o", str(executable),
            ], check=True)
            subprocess.run([str(executable)], check=True, timeout=10)
            scene = {"instance_id": "test", "character_id": 7, "scene_generation": 1, "map_id": 0}
            snapshot = {**scene, "ready": True, "character": {"id": 7}, "scripts": []}
            backend = Mock()
            backend.name = "headless"
            backend.read.return_value = {"character": {"id": 7, "strength": 10, "dexterity": 4,
                "intelligence": 4, "luck": 4, "ability_points": 2}, "native_values_valid": True}
            with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
                 patch("beidou_pilot.auto_ap.scene_context", return_value=scene):
                bridge.return_value.snapshot.return_value = snapshot
                bridge.return_value.run_script.side_effect = ClientError("stop", "fixture", {})
                with self.assertRaises(ClientError):
                    auto_ap(backend)
                cliSource = bridge.return_value.run_script.call_args.kwargs["code"]
            # The actual CLI-generated chunk must retain the old anchor even
            # after native InstallScene replaces context.scene.
            compiled = build / "cli.lua"
            compiled.write_text(cliSource, encoding="utf-8")
            subprocess.run([str(executable), str(compiled)], check=True, timeout=10)
            # Independently exercise the numeric projection: native scene
            # numbers are Lua floats, while the retained payload stays old.
            floatSource = compile_strategy('''function main(c)
  assert(math.type(c.scene.character_id) == 'float')
  assert(math.type(c.scene.scene_generation) == 'float')
  local a = c.auto_ap_anchor
  c.game.player.auto_ap(a.instance_id, a.character_id + 0.0, a.scene_generation + 0.0)
end''', {}, scene, extra={"auto_ap_anchor": scene})
            compiled.write_text(floatSource, encoding="utf-8")
            subprocess.run([str(executable), str(compiled)], check=True, timeout=10)
            for character, generation in (("7.5", "1"), ("7", "1.5"), ("7", "0"),
                                          ("7", "9007199254740992.0"), ("7", "math.huge"), ("'7'", "1")):
                invalid = compile_strategy(
                    f"function main(c) c.game.player.auto_ap('test', {character}, {generation}) end", {}, scene)
                compiled.write_text(invalid, encoding="utf-8")
                subprocess.run([str(executable), str(compiled), "invalid"], check=True, timeout=10)
