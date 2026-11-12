"""跨平台移动合同：预算校验、身份锚定、到达确认与只规划模式。"""

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from beidou_pilot.backend import Backend
from beidou_pilot.errors import ClientError
from beidou_pilot.travel import walk_to


def _backend() -> Mock:
    backend = Mock(spec=Backend)
    backend.root, backend.name, backend.instance = Path("/unused"), "beidou", "default"
    return backend


class WalkToContract(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _backend()
        self.initial = {"ready": True, "instance_id": "first", "scene_generation": 3, "map_id": 100,
                        "position": {"x": 10.5, "y": 20.0}, "character": {"id": 4, "hp": 100, "max_hp": 100}}

    def _run(self, final: dict, *, status: str = "completed", plan_only: bool = False) -> dict:
        report = {"status": status, "last_state": final}
        with patch("beidou_pilot.travel.BridgeClient") as bridge:
            bridge.return_value.snapshot.return_value = self.initial
            with patch("beidou_pilot.travel.run_strategy", return_value=report) as run:
                result = walk_to(self.backend, 200, -300, seconds=45, plan_only=plan_only)
        self.run_mock = run
        return result

    def test_arrival_requires_same_map_identity_and_target_coordinates(self) -> None:
        final = {**self.initial, "position": {"x": 200.4, "y": -300.0}}
        result = self._run(final)
        self.assertEqual("arrived", result["status"])
        self.assertEqual("travel/walk_to", self.run_mock.call_args.args[1])
        options = self.run_mock.call_args.args[2]
        self.assertEqual({45, 200, -300, False}, {options["budget_seconds"], options["target_x"],
                                                 options["target_y"], options["plan_only"]})
        self.assertEqual(self.initial, self.run_mock.call_args.kwargs["context_state"])

    def test_wrong_position_or_map_stops_with_explicit_error(self) -> None:
        cases = {
            "walk_to_not_confirmed": {**self.initial, "position": {"x": 10.0, "y": 20.0}},
            "walk_to_identity_changed": {**self.initial, "map_id": 200, "position": {"x": 200.0, "y": -300.0}},
        }
        for code, final in cases.items():
            with self.subTest(code=code), self.assertRaises(ClientError) as failure:
                self._run(final)
            self.assertEqual(code, failure.exception.code)

    def test_plan_only_returns_planned_without_requiring_movement(self) -> None:
        result = self._run(self.initial, plan_only=True)
        self.assertEqual("planned", result["status"])
        self.assertTrue(self.run_mock.call_args.args[2]["plan_only"])

    def test_budget_and_tolerance_are_validated_before_input(self) -> None:
        for kwargs in ({"seconds": 0.5}, {"seconds": 121}, {"tolerance": 0}, {"min_hp_ratio": -0.1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ClientError):
                walk_to(self.backend, 0, 0, **kwargs)


if __name__ == "__main__":
    unittest.main()
