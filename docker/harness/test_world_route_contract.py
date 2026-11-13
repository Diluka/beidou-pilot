"""技能内路线数据与生成器安全合同。"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))
map_spec = importlib.util.spec_from_file_location("world_map_contract", ROOT / ".agents/skills/beidou-game-guide/tools/world_map.py")
map_generator = importlib.util.module_from_spec(map_spec)
map_spec.loader.exec_module(map_generator)


class WorldRouteContract(unittest.TestCase):
    def test_route_runs_without_runtime_resources(self):
        script = ROOT / ".agents/skills/beidou-game-guide/tools/world_route.py"
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
               "MAPLE_RESOURCES_CONFIG": "/nonexistent", "CLIENT_ROOT": "/nonexistent"}
        result = subprocess.run([sys.executable, str(script), "103000000", "102000000"],
                                env=env, cwd="/", capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report["paid_candidates"]["fewest_planning_legs"]["cost"], 1000)

    def test_generator_does_not_overwrite_when_display_data_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory)
            (skill / "references").mkdir()
            output = skill / "references/world-map.md"
            output.write_text("保留原有攻略")
            with patch.object(map_generator, "SKILL", skill), \
                 patch.object(map_generator, "world_data", return_value={1: object()}), \
                 patch.object(map_generator, "display_regions", return_value={}):
                with self.assertRaisesRegex(SystemExit, "未覆盖"):
                    map_generator.main()
            self.assertEqual(output.read_text(), "保留原有攻略")


if __name__ == "__main__":
    unittest.main()
