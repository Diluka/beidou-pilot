"""商店关闭必须确认结果，重试仅针对仍在顶层的同一窗口。"""

import unittest
from unittest.mock import Mock, patch

from beidou_pilot.errors import ClientError
from beidou_pilot.shop import close_shop


class ShopCloseTest(unittest.TestCase):
    def run_close(self, close_after, top=True):
        window = {"address": "0x1", "instance_ref": "one", "buttons": []}
        opened = {"open": True, "window": window, "quantity_dialog": None, "unavailable": []}
        closed = {"open": False, "window": None, "quantity_dialog": None, "unavailable": []}
        ui = {"windows": [window if top else {"instance_ref": "other"}], "unavailable": [], "dialog": {}}
        backend = Mock()
        clicks = []
        clock = [0.0]

        def read(domain):
            if domain == "ui":
                return ui
            return closed if len(clicks) >= close_after else opened

        def click(*args):
            clicks.append(args)

        def sleep(seconds):
            clock[0] += seconds

        backend.read.side_effect = read
        with (
            patch("beidou_pilot.shop.click_control", side_effect=click),
            patch("beidou_pilot.shop.time.monotonic", side_effect=lambda: clock[0]),
            patch("beidou_pilot.shop.time.sleep", side_effect=sleep),
        ):
            try:
                return close_shop(backend), clicks, None
            except ClientError as error:
                return None, clicks, error

    def test_closes_first_attempt(self):
        result, clicks, error = self.run_close(1)
        self.assertIsNone(error)
        self.assertTrue(result["closed"])
        self.assertEqual(len(clicks), 1)

    def test_retries_same_topmost_window(self):
        result, clicks, error = self.run_close(2)
        self.assertIsNone(error)
        self.assertTrue(result["closed"])
        self.assertEqual(len(clicks), 2)

    def test_exhaustion_reports_window_evidence(self):
        result, clicks, error = self.run_close(4)
        self.assertIsNone(result)
        self.assertEqual(len(clicks), 3)
        self.assertEqual(error.code, "shop_close_not_confirmed")
        self.assertEqual(error.details["attempts"], 3)
        self.assertTrue(error.details["shop"]["open"])
        self.assertEqual(error.details["ui"]["windows"][-1]["instance_ref"], "one")

    def test_not_topmost_refuses_retry(self):
        result, clicks, error = self.run_close(4, top=False)
        self.assertIsNone(result)
        self.assertEqual(len(clicks), 0)
        self.assertEqual(error.code, "shop_close_not_confirmed")
        self.assertEqual(error.details["attempts"], 0)


if __name__ == "__main__":
    unittest.main()
