"""桥状态 character.physics 严格校验合同；临时文件只验证 IPC 字段，不代表游戏事实。"""

import importlib
import os
from pathlib import Path
import tempfile
import typing
import unittest
from unittest.mock import patch

from beidou_pilot.bridge import BridgeClient
from beidou_pilot.errors import ClientError
from .test_bridge import BridgeFiles


class BridgeTypeAnnotationOrder(unittest.TestCase):
    def test_bridge_typed_dict_annotations_resolve(self) -> None:
        # 镜像内 CLI 运行 Python 3.11，TypedDict 注解在类创建时立即求值；这里显式
        # 解析全部桥 TypedDict 注解，避免只在本机 Python 3.14 惰性求值下通过、
        # 到镜像里才因前向引用顺序抛 NameError。
        module = importlib.import_module("beidou_pilot.bridge")
        definitions = [
            value for value in vars(module).values() if isinstance(value, type) and typing.is_typeddict(value)
        ]
        self.assertTrue(definitions)
        for definition in definitions:
            typing.get_type_hints(definition)


class BridgePhysicsContract(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.files = BridgeFiles(Path(temporary.name))
        self.enterContext(patch.dict(os.environ, self.files.environment))
        self.client = BridgeClient(self.files.root)

    def publish_physics(self, physics: object) -> None:
        self.files.state["character"]["physics"] = physics
        self.files.publish()

    def test_known_pose_is_accepted_and_not_recomputed(self) -> None:
        pose = {
            "update_id": 12,
            "step_ms": 30,
            "x": 2147.125,
            "y": 1239.0,
            "velocity": {"x": 125.0, "y": 0.0},
            "on_ground": True,
        }
        self.publish_physics(pose)
        self.assertEqual(pose, self.client.snapshot()["character"]["physics"])

    def test_unknown_fields_stay_unknown_instead_of_zero(self) -> None:
        pose = {
            "update_id": 3,
            "step_ms": 8,
            "x": None,
            "y": None,
            "velocity": None,
            "on_ground": None,
        }
        self.publish_physics(pose)
        self.assertEqual(pose, self.client.snapshot()["character"]["physics"])
        self.publish_physics(None)
        self.assertIsNone(self.client.snapshot()["character"]["physics"])

    def test_invalid_pose_fields_are_rejected(self) -> None:
        cases = (
            "not-a-dict",
            {"update_id": -1, "step_ms": 30},
            {"update_id": True, "step_ms": 30},
            {"update_id": 1, "step_ms": 0},
            {"update_id": 1, "step_ms": 30, "x": "2147.125", "y": 1239.0},
            {"update_id": 1, "step_ms": 30, "x": 1.0},
            {"update_id": 1, "step_ms": 30, "x": 1.0, "y": None},
            {"update_id": 1, "step_ms": 30, "x": 1.0, "y": 2.0, "velocity": {"x": 1.0}},
            {"update_id": 1, "step_ms": 30, "x": 1.0, "y": 2.0, "velocity": {"x": 1.0, "y": float("nan")}},
            {"update_id": 1, "step_ms": 30, "x": 1.0, "y": 2.0, "on_ground": 1},
        )
        for physics in cases:
            with self.subTest(physics=physics):
                self.publish_physics(physics)
                with self.assertRaises(ClientError) as raised:
                    self.client.snapshot()
                self.assertEqual("invalid_bridge_state", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
