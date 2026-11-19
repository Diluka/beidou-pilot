import unittest
from pathlib import Path
from unittest.mock import patch

from beidou_pilot.auto_ap import auto_ap
from beidou_pilot.errors import ClientError


def observation(ap, strength=10, identity=1):
    return {"native_values_valid": True, "character": {"id": identity, "strength": strength,
            "dexterity": 4, "intelligence": 4, "luck": 4, "ability_points": ap}}


class AutoApTest(unittest.TestCase):
    def test_zero_ap_never_submits(self):
        from unittest.mock import Mock
        backend = Mock()
        backend.read.return_value = observation(0)
        with patch("beidou_pilot.auto_ap.BridgeClient") as bridge:
            self.assertEqual(auto_ap(backend)["status"], "unchanged")
            bridge.assert_not_called()

    def test_gui_opens_stats_before_single_submission(self):
        from unittest.mock import Mock, call
        backend = Mock()
        backend.name = "beidou"
        backend.root = Path("/work/runtime/default/run")
        backend.read.side_effect = [observation(2), observation(0, 12)]
        order = Mock()
        initial_scene = {"character_id": 1, "instance_id": "a", "scene_generation": 3, "map_id": 4}
        with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
             patch("beidou_pilot.auto_ap.scene_context", return_value=initial_scene), \
             patch("beidou_pilot.auto_ap.compile_strategy", return_value="compiled") as compile_script, \
             patch.object(Path, "is_file", return_value=True), \
             patch("beidou_pilot.ui.open_window") as open_window:
            bridge.return_value.snapshot.return_value = {"scripts": []}
            order.attach_mock(open_window, "open_window")
            order.attach_mock(bridge.return_value.run_script, "run_script")
            self.assertEqual(auto_ap(backend)["status"], "allocated")
            self.assertEqual(order.mock_calls, [call.open_window(backend, "stats"),
                             call.run_script(code="compiled", seconds=6, timeout=9)])
            source, options, scene = compile_script.call_args.args
            self.assertIs(scene, initial_scene)
            self.assertIn("auto_ap(context.scene.instance_id, context.scene.character_id, context.scene.scene_generation)", source)

    def test_gui_window_failure_does_not_submit(self):
        from unittest.mock import Mock
        backend = Mock()
        backend.name = "beidou"
        backend.root = Path("/work/runtime/default/run")
        backend.read.return_value = observation(2)
        with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
             patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": 1}), \
             patch.object(Path, "is_file", return_value=True), \
             patch("beidou_pilot.ui.open_window", side_effect=ClientError("ui_window_missing", "error")):
            bridge.return_value.snapshot.return_value = {"scripts": []}
            with self.assertRaises(ClientError) as caught:
                auto_ap(backend)
            self.assertEqual(caught.exception.code, "ui_window_missing")
            bridge.return_value.run_script.assert_not_called()

    def test_gui_character_change_during_window_never_submits(self):
        from unittest.mock import Mock
        backend = Mock()
        backend.name = "beidou"
        backend.root = Path("/work/runtime/default/run")
        backend.read.return_value = observation(2)
        original = {"character_id": 1, "instance_id": "a", "scene_generation": 1, "map_id": 1}
        for field, changed in (("character_id", 2), ("instance_id", "b"), ("scene_generation", 2)):
            with self.subTest(field=field), \
                 patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
                 patch("beidou_pilot.auto_ap.scene_context", side_effect=[original, {**original, field: changed}]), \
                 patch.object(Path, "is_file", return_value=True), \
                 patch("beidou_pilot.ui.open_window"):
                bridge.return_value.snapshot.return_value = {"scripts": []}
                with self.assertRaises(ClientError) as caught:
                    auto_ap(backend)
                self.assertEqual(caught.exception.code, "character_changed")
                bridge.return_value.run_script.assert_not_called()

    def test_gui_without_marker_has_no_input(self):
        from unittest.mock import Mock
        backend = Mock()
        backend.name = "beidou"
        backend.root = Path("/work/runtime/default/run")
        backend.read.return_value = observation(2)
        with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
             patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": 1}), \
             patch.object(Path, "is_file", autospec=True, return_value=False) as marker, \
             patch("beidou_pilot.ui.open_window") as open_window:
            bridge.return_value.snapshot.return_value = {"scripts": []}
            with self.assertRaises(ClientError) as caught:
                auto_ap(backend)
            self.assertEqual(caught.exception.code, "unsupported_capability")
            marker.assert_called_once_with(Path("/work/auto-ap-diagnostic.enable"))
            open_window.assert_not_called()
            bridge.return_value.run_script.assert_not_called()

    def test_gui_guards_do_not_open_stats(self):
        from unittest.mock import Mock
        for ap, scripts, scene_id, expected in (
            (0, [], 1, None), (2, [{"status": "running", "id": "x"}], 1, "input_busy"),
            (2, [], 2, "character_changed"),
        ):
            with self.subTest(expected=expected):
                backend = Mock()
                backend.name = "beidou"
                backend.read.return_value = observation(ap)
                with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
                     patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": scene_id}), \
                     patch("beidou_pilot.ui.open_window") as open_window:
                    bridge.return_value.snapshot.return_value = {"scripts": scripts}
                    if expected is None:
                        self.assertEqual(auto_ap(backend)["status"], "unchanged")
                    else:
                        with self.assertRaises(ClientError) as caught:
                            auto_ap(backend)
                        self.assertEqual(caught.exception.code, expected)
                    open_window.assert_not_called()
                    bridge.return_value.run_script.assert_not_called()

    def test_actual_result_and_single_submission(self):
        from unittest.mock import Mock
        backend = Mock(name="backend")
        backend.name = "headless"
        backend.read.side_effect = [observation(2), observation(2), observation(0, 12)]
        with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
             patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": 1}), \
             patch("beidou_pilot.auto_ap.compile_strategy", return_value="compiled"), \
             patch("beidou_pilot.auto_ap.time.sleep"):
            bridge.return_value.snapshot.return_value = {"scripts": []}
            result = auto_ap(backend)
            self.assertEqual(result["allocated"], 2)
            self.assertEqual(result["after"]["strength"], 12)
            bridge.return_value.run_script.assert_called_once()

    def test_script_error_mapping_and_no_retry(self):
        from unittest.mock import Mock
        for message, expected in (("input_busy", "input_busy"),
                                  ("auto_ap_input_busy", "input_busy"),
                                  ("auto_ap_unsupported", "unsupported_capability"),
                                  ("unsupported: auto_ap_job", "unsupported_capability"),
                                  ("auto_ap_confirmation_pending", "unknown")):
            with self.subTest(message=message):
                backend = Mock()
                backend.read.return_value = observation(2)
                with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
                     patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": 1}), \
                     patch("beidou_pilot.auto_ap.compile_strategy", side_effect=lambda code, *args: code):
                    bridge.return_value.snapshot.return_value = {"scripts": []}
                    bridge.return_value.run_script.side_effect = ClientError(
                        "bridge_script_error", "error", {"script": {"error": message}})
                    with self.assertRaises(ClientError) as caught:
                        auto_ap(backend)
                    self.assertEqual(caught.exception.code, expected)
                    bridge.return_value.run_script.assert_called_once()
                    code = bridge.return_value.run_script.call_args.kwargs["code"]
                    self.assertIn('reason == "unsupported"', code)
                    self.assertIn('status.input_action ~= "auto_ap"', code)
                    self.assertNotIn('if status.reason then', code)

    def test_unconfirmed_result_is_unknown(self):
        from unittest.mock import Mock
        backend = Mock()
        backend.read.return_value = observation(2)
        with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
             patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": 1}), \
             patch("beidou_pilot.auto_ap.compile_strategy", return_value="compiled"), \
             patch("beidou_pilot.auto_ap.time.monotonic", side_effect=[0, 0, 7]), \
             patch("beidou_pilot.auto_ap.time.sleep"):
            bridge.return_value.snapshot.return_value = {"scripts": []}
            with self.assertRaises(ClientError) as caught:
                auto_ap(backend)
            self.assertEqual(caught.exception.code, "unknown")
            bridge.return_value.run_script.assert_called_once()

    def test_mismatched_attribute_delta_is_unknown(self):
        from unittest.mock import Mock
        for strength in (11, 13, 9):
            with self.subTest(strength=strength):
                backend = Mock()
                backend.read.side_effect = [observation(2), observation(0, strength)]
                with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
                     patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": 1}), \
                     patch("beidou_pilot.auto_ap.compile_strategy", return_value="compiled"), \
                     patch("beidou_pilot.auto_ap.time.monotonic", side_effect=[0, 0, 7]), \
                     patch("beidou_pilot.auto_ap.time.sleep"):
                    bridge.return_value.snapshot.return_value = {"scripts": []}
                    with self.assertRaises(ClientError) as caught:
                        auto_ap(backend)
                    self.assertEqual(caught.exception.code, "unknown")
                    bridge.return_value.run_script.assert_called_once()

    def test_observation_error_after_submission_is_unknown(self):
        from unittest.mock import Mock
        backend = Mock()
        backend.read.side_effect = [observation(2), ClientError("read_failed", "读取失败")]
        with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
             patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": 1}), \
             patch("beidou_pilot.auto_ap.compile_strategy", return_value="compiled"):
            bridge.return_value.snapshot.return_value = {"scripts": []}
            with self.assertRaises(ClientError) as caught:
                auto_ap(backend)
            self.assertEqual(caught.exception.code, "unknown")
            self.assertEqual(caught.exception.details["observation_error"]["code"], "read_failed")
            bridge.return_value.run_script.assert_called_once()

    def test_changed_character_stops(self):
        from unittest.mock import Mock
        backend = Mock()
        backend.read.side_effect = [observation(2), observation(0, 12, 2)]
        with patch("beidou_pilot.auto_ap.BridgeClient") as bridge, \
             patch("beidou_pilot.auto_ap.scene_context", return_value={"character_id": 1}), \
             patch("beidou_pilot.auto_ap.compile_strategy", return_value="compiled"):
            bridge.return_value.snapshot.return_value = {"scripts": []}
            with self.assertRaises(ClientError) as caught:
                auto_ap(backend)
            self.assertEqual(caught.exception.code, "character_changed")
