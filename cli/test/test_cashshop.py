import unittest

from beidou_pilot import cashshop
from beidou_pilot.backend import ClientError
from beidou_pilot.cli import parser, dispatch


class FakeBackend:
    def __init__(self, windows, unavailable=None):
        self.windows = windows
        self.unavailable = unavailable or []
        self.actions = []

    def read(self, domain):
        assert domain == "ui"
        return {"windows": self.windows, "unavailable": self.unavailable}

    def desktop(self, actions):
        self.actions.extend(actions)


def window(vtable, width, height):
    return {"vtables": [vtable], "width": width, "height": height, "buttons": []}


class CashshopTests(unittest.TestCase):
    def setUp(self):
        self.windows = [window("0xaf1ca8", 545, 56), window("0xaf1c24", 412, 430), window("0xaf1ba0", 508, 78)]

    def test_open_candidate_keeps_balance_and_page_unknown(self):
        result = cashshop.read_cashshop(FakeBackend(self.windows))
        self.assertTrue(result["open"])
        self.assertEqual(result["status"], "candidate_open")
        self.assertIsNone(result["balance"]["nx"])
        self.assertIsNone(result["page"])

    def test_missing_ambiguous_and_unavailable_are_unknown(self):
        for backend in (
            FakeBackend([]),
            FakeBackend(self.windows + self.windows),
            FakeBackend(self.windows, ["camera"]),
        ):
            self.assertIsNone(cashshop.read_cashshop(backend)["open"])

    def test_no_actions_before_calibration(self):
        backend = FakeBackend(self.windows)
        for action in ("open", "close", "expand"):
            with self.assertRaises(ClientError) as error:
                cashshop.unavailable(backend, action)
            self.assertEqual(error.exception.code, "cashshop_unverified")
        self.assertEqual(backend.actions, [])

    def test_dry_run_is_unverified_and_never_confirms(self):
        backend = FakeBackend(self.windows)
        result = cashshop.plan_expand(backend, "equip", 1)
        self.assertEqual(result["requested"]["sn"], 50200093)
        self.assertEqual(result["candidate"]["button_id"], 2006)
        self.assertFalse(result["candidate_verified"])
        self.assertFalse(result["input_dispatched"])
        self.assertEqual(backend.actions, [])

    def test_parser_and_dispatch(self):
        args = parser().parse_args(["cashshop", "expand", "--type", "equip", "--dry-run"])
        result = dispatch(FakeBackend(self.windows), args)
        self.assertEqual(result["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
