"""脱敏的商城观察与禁止输入测试。"""
import unittest
from unittest.mock import Mock, patch

from beidou_pilot import cashshop
from beidou_pilot.errors import ClientError


def sample():
    return {"grid_count": 1, "modal_count": 0, "modal": None,
            "grid": {"address": "fixture-grid", "nx_credit": 40000, "maple_point": 0, "nx_prepaid": 0,
                     "balance_checksums_valid": True, "category_candidate": 5, "subcategory_candidate": 2,
                     "page_zero_candidate": 2,
                     "items": [{"slot": 3, "control_id_candidate": 2009, "sn_candidate": 50200093,
                                "item_id_candidate": 9111000, "price_candidate": 6400,
                                "secure_value_checksum_valid": True, "address": "fixture-item"}]}}


class CashShopTest(unittest.TestCase):
    def test_dry_run_is_blocked_without_input(self):
        with patch.object(cashshop, "read_cashshop", return_value=sample()):
            result = cashshop.expand(Mock(), "equip", 1, True)
        self.assertFalse(result["input_dispatched"])
        self.assertEqual(result["candidate_matches"][0]["control_id_candidate"], 2009)
        self.assertIn("atomic_click_unavailable", result["blockers"])

    def test_nondry_run_never_dispatches(self):
        backend = Mock()
        with patch.object(cashshop, "read_cashshop", return_value=sample()):
            with self.assertRaises(ClientError) as caught:
                cashshop.expand(backend, "equip", 1, False)
        self.assertEqual(caught.exception.code, "cashshop_unverified")
        backend.desktop.assert_not_called()

    def test_wrong_product_and_existing_modal_are_blocked(self):
        state = sample()
        state["grid"]["items"][0]["sn_candidate"] = 50200092
        state["modal_count"] = 1
        state["modal"] = {"count": 1, "items": [{"sn_candidate": 50200092}]}
        with patch.object(cashshop, "read_cashshop", return_value=state):
            result = cashshop.expand(Mock(), "equip", 1, True)
        self.assertIn("candidate_not_unique", result["blockers"])
        self.assertIn("modal_present_or_unknown", result["blockers"])

    def test_missing_modal_is_unknown(self):
        state = sample()
        del state["modal"]
        with patch.object(cashshop, "read_cashshop", return_value=state):
            result = cashshop.expand(Mock(), "equip", 1, True)
        self.assertIn("modal_present_or_unknown", result["blockers"])

    def test_count_is_bounded_before_observation(self):
        with patch.object(cashshop, "read_cashshop") as read:
            with self.assertRaises(ClientError):
                cashshop.expand(Mock(), "equip", 2, False)
        read.assert_not_called()
