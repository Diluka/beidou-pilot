"""同层战斗补给合同：药品参数透传与战斗范围校验的可定位错误。"""

from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from beidou_pilot.backend import Backend
from beidou_pilot.control_scripts import fight
from beidou_pilot.errors import ClientError


def _backend() -> Mock:
    backend = Mock(spec=Backend)
    backend.root, backend.name, backend.instance = Path("/unused"), "beidou", "default"
    return backend


class FightSupplyContract(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = _backend()
        self.report = {"status": "completed", "last_state": {}}

    def _run(self, **overrides: object) -> dict:
        arguments = {
            "mob_id": 1110101,
            "seconds": 60,
            "stop_level": 30,
            "floor_y": 585,
            "bounds": (-300, 3000),
            "retreat_x": 2000,
            "loot": False,
        }
        arguments.update(overrides)
        with patch("beidou_pilot.control_scripts.run_strategy", return_value=self.report) as run:
            fight(self.backend, **arguments)
        self.run_mock = run
        return run.call_args.args[2]

    def test_explicit_potion_is_forwarded_and_omitted_when_unset(self) -> None:
        options = self._run(hp_item=2000001)
        self.assertEqual(2000001, options["hp_item"])
        options = self._run()
        self.assertNotIn("hp_item", options)

    def test_range_errors_name_the_offending_values(self) -> None:
        with self.assertRaises(ClientError) as failure:
            self._run(retreat_x=4000)
        details = failure.exception.details
        self.assertEqual([-300, 3000], details["bounds"])
        self.assertEqual(4000, details["retreat_x"])
        with self.assertRaises(ClientError) as failure:
            self._run(bounds=(200, 100))
        self.assertEqual([200, 100], failure.exception.details["bounds"])


if __name__ == "__main__":
    unittest.main()
