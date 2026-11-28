"""Temporary probe only: verify the CLI uses the read-only IPC lane."""
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from beidou_pilot.cli import main
from beidou_pilot.observations import DOMAINS


class CashProbeResearchTest(unittest.TestCase):
    def test_probe_uses_private_read_lane_without_input_lock(self):
        reply = {"status": "ok", "data": {"grid_count": 0, "modal_count": 0}}
        output = io.StringIO()
        with patch("beidou_pilot.backend.load_runtime", return_value=None), \
             patch("beidou_pilot.observations.NativeObserver.__init__", return_value=None), \
             patch("beidou_pilot.observations.NativeObserver._read", return_value=(reply, 0)) as read, \
             patch("beidou_pilot.cli.control", side_effect=AssertionError("input lock")), \
             redirect_stdout(output):
            self.assertEqual(main(["--json", "--debug", "_cash-probe"]), 0)
        read.assert_called_once_with("cash-probe", 3)
        self.assertEqual(json.loads(output.getvalue())["data"], reply)
        self.assertNotIn("cash-probe", DOMAINS)
