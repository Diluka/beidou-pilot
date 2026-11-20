"""外部资源配置和不携带运行资产的源码导出合同。"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from beidou_pilot.catalog import Catalog
from beidou_pilot.errors import ClientError
from beidou_pilot.resources import load_resources
from test.img_fixture import write_img


class ResourceConfigurationContract(unittest.TestCase):
    def test_relocated_config_supplies_original_img_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "settings").mkdir()
            write_img(root / "Data/String/Map.img", {"100": {"mapName": "训练场"}})
            config = root / "settings/resources.json"
            config.write_text(json.dumps({"game_data": "../Data"}))
            with patch.dict(os.environ, {"MAPLE_RESOURCES_CONFIG": str(config)}):
                paths = load_resources(root / "separate-client")
                self.assertEqual("训练场", Catalog(root / "separate-client").map_name(100))
            self.assertEqual(root / "Data", paths.game_data)
            self.assertEqual(config, paths.config_file)

    def test_misspelled_external_resource_setting_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "resources.json"
            config.write_text(json.dumps({"headless_resource": "/unselected"}))
            with patch.dict(os.environ, {"MAPLE_RESOURCES_CONFIG": str(config)}):
                with self.assertRaises(ClientError) as failure:
                    load_resources(Path(directory))
            self.assertEqual("resources_config_invalid", failure.exception.code)


class GuiRuntimePreparationContract(unittest.TestCase):
    def test_runtime_replaces_dll_and_shares_data_without_changing_source(self) -> None:
        prepare = Path(__file__).resolve().parents[2] / "docker/gui/prepare-client.sh"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "client"
            (source / "Data").mkdir(parents=True)
            contents = {"BeiDou.exe": b"client", "ijl15.dll": b"original-dll",
                        "2ijl15.dll": b"image-library", "config.ini": b"original-config",
                        "Data/Map.img": b"resource"}
            for name, data in contents.items():
                (source / name).write_bytes(data)
            bridge = Path(directory) / "bridge.dll"
            bridge.write_bytes(b"selected-bridge")
            runtime = Path(directory) / "runtime"
            subprocess.run(["bash", str(prepare), str(source), str(runtime), str(bridge)],
                           check=True, capture_output=True)
            self.assertEqual(b"selected-bridge", (runtime / "ijl15.dll").read_bytes())
            self.assertTrue((runtime / "Data").is_symlink())
            self.assertEqual(source / "Data", (runtime / "Data").resolve())
            (runtime / "config.ini").write_bytes(b"runtime-config")
            self.assertEqual(contents, {name: (source / name).read_bytes() for name in contents})


if __name__ == "__main__":
    unittest.main()
