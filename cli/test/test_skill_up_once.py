import io
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from beidou_pilot.errors import ClientError
from beidou_pilot.skill_up import preflight_skill_up, skill_up_once


def observation(sp=3):
    return {"native_values_valid": True, "instance_id": "i", "client": {"run_id": "r"},
            "character": {"id": 3, "job": 210, "skill_points": sp}}


def character(level=15):
    return {"character_id": 3, "skills_complete": True,
            "skills": {"2101002": {"level": level, "master_level": None}}}


def window(enabled=True):
    return {"address": "a", "instance_ref": "a:1", "vtables": ["0xb3b5cc"],
            "root_rect": {"left": 10, "top": 10, "right": 185, "bottom": 299},
            "buttons": [{"control_id": 2012, "enabled": enabled, "layout_x": 131,
                         "layout_y": 199, "width": 12, "height": 12}],
            "skills": {"ids": [2100000, 2101001, 2101002], "first_index": 0,
                       "selected_tab": 2, "tab_count": 3}}


class Backend:
    name = "beidou"

    def __init__(self):
        self.observations = [observation(), observation(), observation(2)]
        self.characters = [character(), character(), character(16)]

    def read(self, name, *args):
        values = self.observations if name == "observe" else self.characters
        return values.pop(0)


class SkillUpOnceTest(unittest.TestCase):
    def setUp(self):
        verifier = patch("beidou_pilot.skill_up._verified_client", return_value=True)
        verifier.start()
        self.addCleanup(verifier.stop)

    def test_total_preflight_rejects_insufficient_sp(self):
        with self.assertRaises(ClientError) as caught:
            preflight_skill_up(Backend(), 2101002, 4)
        self.assertEqual(caught.exception.code, "insufficient_skill_points")

    def test_total_preflight_refuses_unknown_batch_limit(self):
        with self.assertRaises(ClientError) as caught:
            preflight_skill_up(Backend(), 2201002, 2)
        self.assertEqual(caught.exception.code, "skill_limit_unavailable")

    @patch("beidou_pilot.skill_up.ImgDirectory")
    @patch("beidou_pilot.skill_up.hashlib.file_digest")
    @patch("pathlib.Path.open")
    def test_batch_checks_full_resource_limit(self, opened, digest, directory):
        backend = Backend()
        backend.root = Path("/client")
        opened.side_effect = lambda *args, **kwargs: io.BytesIO(b"sample")
        digest.return_value.hexdigest.side_effect = ["1198fa57ca5a7c489bae43ec13c69681d9cabe0f96762f3dc0357facf2e7d4df", "cc4db190d9fef0523fdfe440ae23a3d2fd61359cef6e327e246a86c6c955111e"] * 3
        level = ET.Element("imgdir")
        for i in range(1, 21):
            ET.SubElement(level, "imgdir", name=str(i))
        directory.return_value.read_tree.return_value = (level, (Path("/client/client/Data/Skill/210.img"),))
        self.assertEqual(preflight_skill_up(backend, 2101002, 2), ("i", "r", 3, 3, 15))
        backend = Backend()
        backend.root = Path("/client")
        backend.characters[0] = character(19)
        with self.assertRaises(ClientError) as caught:
            preflight_skill_up(backend, 2101002, 2)
        self.assertEqual(caught.exception.code, "skill_limit_exceeded")
        backend = Backend()
        backend.root = Path("/client")
        directory.return_value.read_tree.return_value = (level, (Path("/other/210.img"),))
        with self.assertRaises(ClientError) as caught:
            preflight_skill_up(backend, 2101002, 2)
        self.assertEqual(caught.exception.code, "skill_limit_unavailable")

    def test_total_preflight_accepts_one_with_sp(self):
        self.assertIsNone(preflight_skill_up(Backend(), 2101002, 1))

    @patch("beidou_pilot.skill_up.click_control")
    @patch("beidou_pilot.skill_up.read_ui")
    @patch("beidou_pilot.skill_up.open_window")
    def test_occluded_button_is_not_clicked(self, opened, read_ui, clicked):
        w = window()
        opened.return_value = w
        cover = {"vtables": ["other"], "root_rect": {"left": 140, "top": 210, "right": 160, "bottom": 230}}
        read_ui.return_value = {"windows": [w, cover], "dialog": {"focused_window": {"address": "a"}}}
        with self.assertRaises(ClientError) as caught:
            skill_up_once(Backend(), 2101002)
        self.assertEqual(caught.exception.code, "ui_target_occluded")
        clicked.assert_not_called()

    @patch("beidou_pilot.skill_up.click_window")
    @patch("beidou_pilot.skill_up.read_ui")
    @patch("beidou_pilot.skill_up.open_window")
    def test_window_disappears_during_tab_switch(self, opened, read_ui, click):
        w = window()
        w["skills"]["ids"] = []
        w["skills"]["selected_tab"] = 0
        opened.return_value = w
        read_ui.return_value = {"windows": []}
        with self.assertRaises(ClientError) as caught:
            skill_up_once(Backend(), 2101002)
        self.assertEqual(caught.exception.code, "skills_ui_unavailable")

    @patch("beidou_pilot.skill_up.click_control")
    @patch("beidou_pilot.skill_up.open_window")
    def test_unverified_sp_pool_is_refused(self, opened, clicked):
        w = window()
        w["skills"]["selected_tab"] = 0
        opened.return_value = w
        with self.assertRaises(ClientError) as caught:
            skill_up_once(Backend(), 2101002)
        self.assertEqual(caught.exception.code, "skill_points_pool_unavailable")
        clicked.assert_not_called()

    @patch("beidou_pilot.skill_up.click_control")
    @patch("beidou_pilot.skill_up.read_ui")
    @patch("beidou_pilot.skill_up.open_window")
    def test_ordinary_nonzero_tab_and_special_jobs(self, opened, read_ui, clicked):
        w = window()
        w["skills"]["selected_tab"] = 1
        w["skills"]["ids"] = [1000000, 1000001, 1001003]
        opened.return_value = w
        read_ui.return_value = {"windows": [w], "dialog": {"focused_window": {"address": "a"}}}
        backend = Backend()
        for item in backend.observations:
            item["character"]["job"] = 100
        for item in backend.characters:
            item["skills"]["1001003"] = item["skills"].pop("2101002")
        self.assertEqual(skill_up_once(backend, 1001003)["level_after"], 16)
        clicked.reset_mock()
        for job in (2200, 2299, 2001):
            backend = Backend()
            backend.observations[0]["character"]["job"] = job
            backend.characters[0]["skills"]["1001003"] = backend.characters[0]["skills"].pop("2101002")
            with self.assertRaises(ClientError) as caught:
                skill_up_once(backend, 1001003)
            self.assertEqual(caught.exception.code, "skill_points_pool_unavailable")
        clicked.assert_not_called()

    @patch("beidou_pilot.skill_up.click_control")
    @patch("beidou_pilot.skill_up.read_ui")
    @patch("beidou_pilot.skill_up.open_window")
    def test_confirms_one_point(self, opened, read_ui, clicked):
        w = window()
        opened.return_value = w
        read_ui.return_value = {"windows": [w], "dialog": {"focused_window": {"address": "a"}}}
        result = skill_up_once(Backend(), 2101002)
        self.assertEqual(result, {"skill_id": 2101002, "level_before": 15, "level_after": 16,
                                  "sp_before": 3, "sp_after": 2})
        clicked.assert_called_once_with(unittest.mock.ANY, w, 2012)

    @patch("beidou_pilot.skill_up.click_control")
    @patch("beidou_pilot.skill_up.open_window")
    def test_disabled_button_is_not_a_claimed_cause(self, opened, clicked):
        opened.return_value = window(False)
        with self.assertRaises(ClientError) as caught:
            skill_up_once(Backend(), 2101002)
        self.assertEqual(caught.exception.code, "skill_not_available")
        clicked.assert_not_called()

    @patch("beidou_pilot.skill_up.open_window")
    def test_missing_initial_level_is_refused(self, opened):
        backend = Backend()
        backend.characters[0]["skills"] = {}
        with self.assertRaises(ClientError) as caught:
            skill_up_once(backend, 2001002)
        self.assertEqual(caught.exception.code, "skill_level_unavailable")
        opened.assert_not_called()

    @patch("beidou_pilot.skill_up.click_control")
    @patch("beidou_pilot.skill_up.read_ui")
    @patch("beidou_pilot.skill_up.open_window")
    def test_missing_ordinary_level_can_start_at_zero(self, opened, read_ui, clicked):
        backend = Backend()
        backend.characters = [character(), character(), character(1)]
        backend.characters[0]["skills"] = {}
        backend.characters[1]["skills"] = {}
        w = window()
        opened.return_value = w
        read_ui.return_value = {"windows": [w], "dialog": {"focused_window": {"address": "a"}}}
        result = skill_up_once(backend, 2101002)
        self.assertEqual((result["level_before"], result["level_after"]), (0, 1))
        clicked.assert_called_once()

    @patch("beidou_pilot.skill_up.open_window")
    def test_unverified_executable_is_refused(self, opened):
        with patch("beidou_pilot.skill_up._verified_client", return_value=False):
            with self.assertRaises(ClientError) as caught:
                skill_up_once(Backend(), 2101002)
        self.assertEqual(caught.exception.code, "skill_points_pool_unavailable")
        opened.assert_not_called()

    @patch("beidou_pilot.skill_up.open_window")
    def test_changed_identity_after_preflight_is_refused(self, opened):
        with self.assertRaises(ClientError) as caught:
            skill_up_once(Backend(), 2101002, ("i", "old-run", 3, 3, 15))
        self.assertEqual(caught.exception.code, "skill_state_changed")
        opened.assert_not_called()

    @patch("beidou_pilot.skill_up.open_window")
    def test_insufficient_points_refused_before_ui(self, opened):
        backend = Backend()
        backend.observations[0] = observation(0)
        with self.assertRaises(ClientError) as caught:
            skill_up_once(backend, 2101002)
        self.assertEqual(caught.exception.code, "insufficient_skill_points")
        opened.assert_not_called()

    @patch("beidou_pilot.skill_up.click_control", side_effect=ClientError("backend_failed", "failed"))
    @patch("beidou_pilot.skill_up.read_ui")
    @patch("beidou_pilot.skill_up.open_window")
    def test_click_failure_has_unknown_outcome(self, opened, read_ui, clicked):
        w = window()
        opened.return_value = w
        read_ui.return_value = {"windows": [w], "dialog": {"focused_window": {"address": "a"}}}
        with self.assertRaises(ClientError) as caught:
            skill_up_once(Backend(), 2101002)
        self.assertEqual(caught.exception.code, "skill_up_unknown")
        clicked.assert_called_once()
