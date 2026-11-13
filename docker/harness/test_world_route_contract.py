"""线路工具的容器资源和导入合同，无需游戏资源。"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "cli"))
spec = importlib.util.spec_from_file_location("world_route_contract", ROOT / ".agents/skills/beidou-game-guide/tools/world_route.py")
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


class WorldRouteContract(unittest.TestCase):
    def test_explicit_resources_config_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "resources.json"
            config.write_text(json.dumps({"gui_client": "mounted-client"}))
            with patch.dict(os.environ, {"MAPLE_RESOURCES_CONFIG": str(config), "CLIENT_ROOT": directory}), \
                 patch.object(sys, "argv", ["world_route.py", "1", "1"]), \
                 patch.object(route, "world_data", side_effect=RuntimeError("observed")) as world_data:
                with self.assertRaisesRegex(RuntimeError, "observed"):
                    route.main()
            world_data.assert_called_once_with(Path(directory) / "mounted-client")

    def test_client_root_default_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config/resources.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"gui_client": "mounted-client"}))
            with patch.dict(os.environ, {"CLIENT_ROOT": directory}, clear=True), \
                 patch.object(sys, "argv", ["world_route.py", "1", "1"]), \
                 patch.object(route, "world_data", side_effect=RuntimeError("observed")) as world_data:
                with self.assertRaisesRegex(RuntimeError, "observed"):
                    route.main()
            world_data.assert_called_once_with(config.parent / "mounted-client")


if __name__ == "__main__":
    unittest.main()
