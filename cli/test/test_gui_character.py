import fcntl
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from beidou_pilot.errors import ClientError
from beidou_pilot.gui_character import (
    _appearance_step,
    _apply_appearance,
    _check_name,
    _enter_name,
    _final_confirmation_action,
    _navigate_category,
    _open_creation,
    _set_gender,
    _submit_creation,
    _wait_creation_result,
    create_once,
    creation_page_button,
    identify_creation_page,
    name_candidate_decision,
    mark_final_submit,
    persist_result,
    plan_observed_appearance_step,
    query_result,
    record_attempt,
    record_final_dispatch,
    require_supported_creation,
    validate_appearance_transition,
    verify_created_character,
)
from beidou_pilot.profile import CharacterCreation


class GuiCharacterTest(unittest.TestCase):
    def setUp(self):
        self.state = {
            "instance_id": "instance",
            "client": {"run_id": "run"},
            "unavailable": [],
            "stage": "CHARACTER_SELECT",
            "login": {
                "characters_available": True,
                "request_pending": False,
                "transition_pending": False,
                "characters": [{"id": 19, "name": "Example"}],
            },
        }

    def verify(self, previous_ids=None):
        return verify_created_character(
            self.state,
            instance_id="instance",
            run_id="run",
            name="Example",
            previous_ids=set() if previous_ids is None else previous_ids,
        )

    def test_real_new_id_required(self):
        self.assertEqual(self.verify()["character_id"], 19)
        self.assertEqual(self.verify({19})["status"], "unknown")
        self.state["login"]["characters"][0]["id"] = 0
        self.assertEqual(self.verify()["status"], "unknown")

    def test_unknown_state_or_ambiguous_list(self):
        self.state["login"]["request_pending"] = True
        self.assertEqual(self.verify()["status"], "unknown")
        self.state["login"]["request_pending"] = False
        self.state["login"]["characters"].append({"id": 20, "name": "Other"})
        self.assertEqual(self.verify()["status"], "unknown")
        self.state["client"]["run_id"] = "other"
        self.assertEqual(self.verify()["status"], "unknown")

    def test_page_identification_stops_on_unknown(self):
        self.state["login"]["raw_step"] = 4
        dialog = {
            "instance_id": "instance",
            "client": {"run_id": "run"},
            "unavailable": [],
            "focused_window": {"vtables": ["0xaf7564", "0xaf7518", "0xaf7514"], "width": 201, "height": 224},
        }
        self.assertEqual(identify_creation_page(self.state, dialog, instance_id="instance", run_id="run"), "name")
        dialog["focused_window"]["vtables"] = None
        self.assertEqual(identify_creation_page(self.state, dialog, instance_id="instance", run_id="run"), "unknown")

    def test_stable_category_and_name_button_projection(self):
        for page, step, vt, dim, origin, button in (
            ("category", 3, ["0xaf7360", "0xaf7314", "0xaf7310"], (700, 460), (240, 40), (1003, 530, 422, 73, 29)),
            ("name", 4, ["0xaf7564", "0xaf7518", "0xaf7514"], (201, 224), (721, 155), (1000, 27, 178, 81, 41)),
        ):
            with self.subTest(page=page):
                cid, x, y, w, h = button
                gx, gy = origin
                rw, rh = dim
                b = {"control_id": cid, "layout_x": x, "layout_y": y, "width": w, "height": h}
                focused = {
                    "address": "0x1234",
                    "vtables": vt,
                    "width": rw,
                    "height": rh,
                    "game_rect": {"left": gx, "top": gy, "right": gx + rw, "bottom": gy + rh},
                    "root_rect": {"left": 323 + gx, "top": 119 + gy, "right": 323 + gx + rw, "bottom": 119 + gy + rh},
                    "buttons": [
                        {
                            **b,
                            "root_rect": {
                                "left": 323 + gx + x,
                                "top": 119 + gy + y,
                                "right": 323 + gx + x + w,
                                "bottom": 119 + gy + y + h,
                            },
                        }
                    ],
                }
                dialog = {
                    "instance_id": "instance",
                    "client": {"run_id": "run"},
                    "unavailable": [],
                    "focused_window": focused,
                    "game_geometry": {"x": 323, "y": 119, "width": 1280, "height": 720},
                    "script_dialog_open": False,
                    "focused_talk_dialog_open": False,
                    "registered_talk_dialog_open": False,
                }
                stage = {
                    "instance_id": "instance",
                    "client": {"run_id": "run"},
                    "unavailable": [],
                    "login": {"raw_step": step, "request_pending": False, "transition_pending": False},
                    "windows": [{"address": "0x1234", "vtables": vt, "buttons": [{**b, "enabled": True}]}],
                }
                args = {"instance_id": "instance", "run_id": "run", "page": page}
                self.assertIsNotNone(creation_page_button(stage, dialog, **args))
                for invalid in (None, "", "0x0"):
                    focused["address"] = invalid
                    stage["windows"][0]["address"] = invalid
                    self.assertIsNone(creation_page_button(stage, dialog, **args))
                del focused["address"]
                del stage["windows"][0]["address"]
                self.assertIsNone(creation_page_button(stage, dialog, **args))
                focused["address"] = stage["windows"][0]["address"] = "0x1234"
                focused["game_rect"]["top"] += 67
                self.assertIsNone(creation_page_button(stage, dialog, **args))
                focused["game_rect"]["top"] -= 67
                stage["windows"][0]["buttons"][0]["enabled"] = False
                self.assertIsNone(creation_page_button(stage, dialog, **args))

    def test_final_action_requires_every_raw_field(self):
        raw = [21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005]
        params = CharacterCreation("Example", 1, *raw, True)
        vt = ["0xaf777c", "0xaf7730", "0xaf772c"]
        button = {"control_id": 1000, "layout_x": 37, "layout_y": 330, "width": 81, "height": 41}
        window = {
            "address": "0x1234",
            "vtables": vt,
            "raw_appearance_candidates": raw.copy(),
            "raw_job_candidate": 1,
            "raw_appearance_selector": 1,
            "buttons": [{**button, "enabled": True}],
        }
        stage = {
            "instance_id": "instance",
            "client": {"run_id": "run"},
            "unavailable": [],
            "login": {"raw_step": 4, "request_pending": False, "transition_pending": False},
            "windows": [window],
        }
        focused = {
            "address": "0x1234",
            "vtables": vt,
            "width": 225,
            "height": 377,
            "game_rect": {"left": 721, "top": 155, "right": 946, "bottom": 532},
            "root_rect": {"left": 1044, "top": 274, "right": 1269, "bottom": 651},
            "buttons": [{**button, "root_rect": {"left": 1081, "top": 604, "right": 1162, "bottom": 645}}],
        }
        dialog = {
            "instance_id": "instance",
            "client": {"run_id": "run"},
            "unavailable": [],
            "focused_window": focused,
            "game_geometry": {"x": 323, "y": 119, "width": 1280, "height": 720},
            "script_dialog_open": False,
            "focused_talk_dialog_open": False,
            "registered_talk_dialog_open": False,
        }
        args = {"instance_id": "instance", "run_id": "run"}
        self.assertEqual(
            _final_confirmation_action(stage, dialog, params, **args), {"action": "click", "x": 1121, "y": 624}
        )
        for index in range(8):
            window["raw_appearance_candidates"][index] += 1
            self.assertIsNone(_final_confirmation_action(stage, dialog, params, **args))
            window["raw_appearance_candidates"][index] -= 1
        for key in ("raw_job_candidate", "raw_appearance_selector"):
            old = window[key]
            window[key] = None
            self.assertIsNone(_final_confirmation_action(stage, dialog, params, **args))
            window[key] = old

    def test_name_candidate_remains_unknown_without_exact_focus(self):
        stage = {
            "windows": [{"address": "0x1234", "creation_name_focused": True, "creation_name_candidate": "OldName"}]
        }
        dialog = {"focused_window": {"address": "0x1234"}}
        args = {"instance_id": "instance", "run_id": "run", "name": "NewName"}
        with patch("beidou_pilot.gui_character.creation_page_button", return_value={"action": "click"}):
            self.assertEqual(name_candidate_decision(stage, dialog, **args)["status"], "different")
            stage["windows"][0]["creation_name_candidate"] = "NewName"
            self.assertEqual(name_candidate_decision(stage, dialog, **args)["status"], "matched")
            stage["windows"][0]["creation_name_candidate"] = ""
            self.assertEqual(name_candidate_decision(stage, dialog, **args)["status"], "empty")
            for value in (None, "中文"):
                stage["windows"][0]["creation_name_candidate"] = value
                self.assertEqual(name_candidate_decision(stage, dialog, **args)["status"], "unknown")
            stage["windows"][0]["creation_name_candidate"] = "NewName"
            stage["windows"][0]["creation_name_focused"] = False
            self.assertEqual(name_candidate_decision(stage, dialog, **args)["status"], "unknown")
            self.assertEqual(name_candidate_decision(stage, dialog, **{**args, "name": "中文"})["status"], "unknown")

    def test_name_controller_mock_requires_exact_post_input_match(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        for final in ("matched", "unknown"):
            with self.subTest(final=final), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
                backend = MagicMock()
                backend.name = "beidou"
                backend.read.side_effect = (
                    lambda kind: {} if kind == "stage" else {"focused_window": {"address": "0x1234"}}
                )
                args = {
                    "directory": root,
                    "request_id": record["request_id"],
                    "instance_id": "instance",
                    "run_id": "run",
                    "deadline": float("inf"),
                }
                with (
                    patch(
                        "beidou_pilot.gui_character.load_runtime",
                        return_value=SimpleNamespace(running=True, run_id="run"),
                    ),
                    patch("beidou_pilot.gui_character.require_input_idle"),
                    patch("beidou_pilot.gui_character.BridgeClient"),
                    patch(
                        "beidou_pilot.gui_character.name_candidate_decision",
                        side_effect=[{"status": "empty"}, {"status": "empty"}, {"status": final}],
                    ),
                ):
                    self.assertEqual(_enter_name(backend, params, **args)["status"], final)
                self.assertEqual(backend.text.call_count, 1)
                backend.desktop.assert_not_called()

    def test_name_controller_timeout_identity_and_input_failure(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        for scenario in ("identity", "deadline", "input_failure"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
                backend = MagicMock()
                backend.name = "beidou"
                backend.read.side_effect = (
                    lambda kind: {} if kind == "stage" else {"focused_window": {"address": "0x1234"}}
                )
                if scenario == "input_failure":
                    backend.text.side_effect = OSError("uncertain input")
                args = {
                    "directory": root,
                    "request_id": record["request_id"],
                    "instance_id": "instance",
                    "run_id": "other" if scenario == "identity" else "run",
                    "deadline": 0 if scenario == "deadline" else float("inf"),
                }
                with (
                    patch(
                        "beidou_pilot.gui_character.load_runtime",
                        return_value=SimpleNamespace(running=True, run_id="run"),
                    ),
                    patch("beidou_pilot.gui_character.require_input_idle"),
                    patch("beidou_pilot.gui_character.BridgeClient"),
                    patch("beidou_pilot.gui_character.name_candidate_decision", return_value={"status": "empty"}),
                ):
                    if scenario == "deadline":
                        self.assertEqual(_enter_name(backend, params, **args)["reason"], "timeout")
                    else:
                        with self.assertRaises((ClientError, OSError)):
                            _enter_name(backend, params, **args)
                    if scenario == "input_failure":
                        with self.assertRaises(ClientError) as error:
                            _enter_name(backend, params, **args)
                        self.assertEqual(error.exception.code, "gui_character_already_attempted")
                self.assertEqual(backend.text.call_count, 1 if scenario == "input_failure" else 0)

    def test_name_check_unknown_never_replayed(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            backend = MagicMock()
            backend.name = "beidou"
            backend.read.side_effect = lambda kind: {} if kind == "stage" else {"focused_window": {"address": "0x1234"}}
            backend.desktop.return_value = {
                "input_dispatched": True,
                "cancelled": False,
                "timings": [{"action": "click"}],
            }
            args = {
                "directory": root,
                "request_id": record["request_id"],
                "instance_id": "instance",
                "run_id": "run",
                "deadline": time.monotonic() + 0.05,
            }
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient"),
                patch(
                    "beidou_pilot.gui_character.creation_page_button",
                    return_value={"action": "click", "x": 10, "y": 20},
                ),
                patch("beidou_pilot.gui_character.name_candidate_decision", return_value={"status": "matched"}),
                patch("beidou_pilot.gui_character.identify_creation_page", return_value="unknown"),
            ):
                self.assertEqual(_check_name(backend, params, **args)["status"], "unknown")
                args["deadline"] = time.monotonic() + 1
                with self.assertRaises(ClientError):
                    _check_name(backend, params, **args)
            backend.desktop.assert_called_once()

    def test_name_check_dispatch_exception_cannot_replay(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            backend = MagicMock()
            backend.name = "beidou"
            backend.read.side_effect = lambda kind: {} if kind == "stage" else {"focused_window": {"address": "0x1234"}}
            backend.desktop.side_effect = OSError("uncertain dispatch")
            args = {
                "directory": root,
                "request_id": record["request_id"],
                "instance_id": "instance",
                "run_id": "run",
                "deadline": time.monotonic() + 0.05,
            }
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient"),
                patch(
                    "beidou_pilot.gui_character.creation_page_button",
                    return_value={"action": "click", "x": 10, "y": 20},
                ),
                patch("beidou_pilot.gui_character.name_candidate_decision", return_value={"status": "matched"}),
            ):
                with self.assertRaises(OSError):
                    _check_name(backend, params, **args)
                with self.assertRaises(ClientError) as error:
                    _check_name(backend, params, **args)
                self.assertEqual(error.exception.code, "gui_character_already_attempted")
            backend.desktop.assert_called_once()

    def test_mock_single_command_flow(self):
        params = CharacterCreation("Example", 1, 21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = MagicMock()
            backend.name = "beidou"
            stage = {**self.state, "login": {**self.state["login"], "characters": []}}
            backend.read.return_value = stage

            def submit(_backend, _params, **kwargs):
                (root / "gui-character-final-dispatched").write_text(kwargs["request_id"])
                return {"status": "unknown"}

            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime",
                    return_value=SimpleNamespace(running=True, run_id="run", run_dir=root),
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient"),
                patch("beidou_pilot.gui_character._open_creation", return_value={"status": "category_page"}),
                patch("beidou_pilot.gui_character._navigate_category", return_value={"status": "name_page"}),
                patch("beidou_pilot.gui_character._enter_name", return_value={"status": "matched"}),
                patch("beidou_pilot.gui_character._check_name", return_value={"status": "appearance_page"}),
                patch("beidou_pilot.gui_character._set_gender", return_value={"status": "matched"}),
                patch("beidou_pilot.gui_character._apply_appearance", return_value={"status": "matched"}),
                patch("beidou_pilot.gui_character._submit_creation", side_effect=submit) as final,
                patch(
                    "beidou_pilot.gui_character._wait_creation_result",
                    return_value={"status": "completed", "character_id": 19},
                ),
            ):
                result = create_once(backend, params, directory=root, instance_id="instance", run_id="run", timeout=5)
            self.assertEqual(result["character_id"], 19)
            final.assert_called_once()

    def test_recorded_failure_preserves_query_identity(self):
        params = CharacterCreation("Example", 1, 21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = MagicMock()
            backend.name = "beidou"
            backend.read.return_value = {**self.state, "login": {**self.state["login"], "characters": []}}
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime",
                    return_value=SimpleNamespace(running=True, run_id="run", run_dir=root),
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient"),
                patch("beidou_pilot.gui_character._open_creation", side_effect=OSError("uncertain")),
            ):
                result = create_once(backend, params, directory=root, instance_id="instance", run_id="run", timeout=1)
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(result["reason"], "operation_unconfirmed")
                self.assertEqual(
                    result["request_id"], json.loads((root / "gui-character-attempt.json").read_text())["request_id"]
                )
                for next_state in ({"stage": "UNKNOWN"}, self.state):
                    backend.read.return_value = next_state
                    with self.assertRaises(ClientError) as error:
                        create_once(backend, params, directory=root, instance_id="instance", run_id="run", timeout=1)
                    self.assertEqual(error.exception.details["request_id"], result["request_id"])
                    self.assertEqual(error.exception.details["run_id"], "run")
                with patch(
                    "beidou_pilot.gui_character.load_runtime",
                    return_value=SimpleNamespace(running=False, run_id="run", run_dir=root),
                ):
                    with self.assertRaises(ClientError) as error:
                        create_once(backend, params, directory=root, instance_id="instance", run_id="run", timeout=1)
                    self.assertEqual(error.exception.details["request_id"], result["request_id"])

    def test_open_creation_uses_fresh_dynamic_projection_once(self):
        params = CharacterCreation("Example", 1, 21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            focus = {"address": "0x111", "vtables": ["0xaf6f04", "0xaf6eb8", "0xaf6eb4"], "width": 720, "height": 80}
            window = {
                "address": "0x222",
                "vtables": ["0xaf6d90", "0xaf6d44", "0xaf6d40"],
                "width": 101,
                "height": 131,
                "game_rect": {"left": 812, "top": 209, "right": 913, "bottom": 340},
                "root_rect": {"left": 1135, "top": 328, "right": 1236, "bottom": 459},
                "buttons": [
                    {"control_id": 1001, "enabled": True, "layout_x": 4, "layout_y": 36, "width": 101, "height": 35}
                ],
            }
            stage = {
                "instance_id": "instance",
                "client": {"run_id": "run"},
                "unavailable": [],
                "stage": "CHARACTER_SELECT",
                "login": {
                    "raw_step": 2,
                    "characters_available": True,
                    "characters": [],
                    "request_pending": False,
                    "transition_pending": False,
                },
                "windows": [focus, window],
            }
            dialog = {
                "instance_id": "instance",
                "client": {"run_id": "run"},
                "unavailable": [],
                "focused_window": focus,
                "script_dialog_open": False,
                "focused_talk_dialog_open": False,
                "registered_talk_dialog_open": False,
                "game_geometry": {"x": 323, "y": 119, "width": 1280, "height": 720},
            }
            backend = MagicMock()
            backend.name = "beidou"
            backend.read.side_effect = lambda kind: stage if kind == "stage" else dialog
            backend.desktop.return_value = {
                "input_dispatched": True,
                "cancelled": False,
                "timings": [{"action": "click"}],
            }
            args = {
                "directory": root,
                "request_id": record["request_id"],
                "instance_id": "instance",
                "run_id": "run",
                "deadline": float("inf"),
            }
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient") as bridge,
                patch("beidou_pilot.gui_character.time.sleep"),
                patch("beidou_pilot.gui_character.creation_page_button", side_effect=[None, {"action": "click"}]),
            ):
                bridge.return_value.snapshot.return_value = {"instance_id": "instance", "run_id": "run"}
                self.assertEqual(_open_creation(backend, params, **args)["status"], "category_page")
                with self.assertRaises(ClientError):
                    _open_creation(backend, params, **args)
            backend.desktop.assert_called_once_with([{"action": "click", "x": 1189, "y": 381}])

    def test_create_rejects_nonempty_before_attempt(self):
        params = CharacterCreation("Other", 1, 21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = MagicMock()
            backend.name = "beidou"
            backend.read.return_value = self.state
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime",
                    return_value=SimpleNamespace(running=True, run_id="run", run_dir=root),
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient"),
            ):
                with self.assertRaises(ClientError) as error:
                    create_once(backend, params, directory=root, instance_id="instance", run_id="run", timeout=1)
                self.assertEqual(error.exception.code, "unsupported_capability")
            self.assertFalse((root / "gui-character-attempt.json").exists())
            backend.desktop.assert_not_called()

    def test_gender_selector_once_both_directions(self):
        for before, target, scenario in (
            (0, 1, "ok"),
            (1, 0, "ok"),
            (1, 1, "ok"),
            (0, 1, "unchanged"),
            (0, 1, "job"),
            (0, 1, "identity"),
            (0, 1, "timeout"),
        ):
            with (
                self.subTest(before=before, target=target, scenario=scenario),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                params = CharacterCreation(
                    "Example", 1, 21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, bool(target)
                )
                record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
                (root / "gui-character-name-checked").write_text(record["request_id"])
                vt = ["0xaf777c", "0xaf7730", "0xaf772c"]
                button = {"control_id": 1019, "layout_x": 196, "layout_y": 250, "width": 15, "height": 16}
                focused = {
                    "address": "0x1234",
                    "vtables": vt,
                    "width": 225,
                    "height": 377,
                    "root_rect": {"left": 1044, "top": 274, "right": 1269, "bottom": 651},
                    "buttons": [{**button, "root_rect": {"left": 1240, "top": 524, "right": 1255, "bottom": 540}}],
                }
                window = {
                    "address": "0x1234",
                    "vtables": vt,
                    "raw_job_candidate": 1,
                    "raw_appearance_selector": before,
                    "raw_appearance_candidates": [21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005],
                    "buttons": [{**button, "enabled": True}],
                }
                stage = {
                    "instance_id": "instance",
                    "client": {"run_id": "run"},
                    "unavailable": [],
                    "login": {"raw_step": 4, "request_pending": False, "transition_pending": False},
                    "windows": [window],
                }
                dialog = {
                    "instance_id": "instance",
                    "client": {"run_id": "run"},
                    "unavailable": [],
                    "focused_window": focused,
                    "script_dialog_open": False,
                    "focused_talk_dialog_open": False,
                    "registered_talk_dialog_open": False,
                }
                backend = MagicMock()
                backend.name = "beidou"
                backend.read.side_effect = lambda kind: stage if kind == "stage" else dialog

                def click(_):
                    if scenario != "unchanged":
                        window["raw_appearance_selector"] = target
                    return {"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]}

                backend.desktop.side_effect = click
                if scenario == "job":
                    window["raw_job_candidate"] = 99
                if scenario == "identity":
                    stage["instance_id"] = "other"
                args = {
                    "directory": root,
                    "request_id": record["request_id"],
                    "instance_id": "instance",
                    "run_id": "run",
                    "deadline": 0 if scenario == "timeout" else float("inf"),
                }
                with (
                    patch(
                        "beidou_pilot.gui_character.load_runtime",
                        return_value=SimpleNamespace(running=True, run_id="run"),
                    ),
                    patch("beidou_pilot.gui_character.require_input_idle"),
                    patch("beidou_pilot.gui_character.BridgeClient"),
                ):
                    if scenario in ("job", "identity"):
                        with self.assertRaises(ClientError):
                            _set_gender(backend, params, **args)
                    else:
                        result = _set_gender(backend, params, **args)
                        self.assertEqual(
                            result["status"], "unknown" if scenario in ("unchanged", "timeout") else "matched"
                        )
                self.assertEqual(backend.desktop.call_count, int(before != target and scenario in ("ok", "unchanged")))

    def test_per_run_lock_contention_and_shared_bridge_isolation(self):
        params = CharacterCreation("Example", 1, 21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, bridge = root / "run1", root / "run2", root / "bridge"
            for path in (first, second, bridge):
                path.mkdir()
            one = record_attempt(first, instance_id="instance", run_id="run1", params=params, previous_ids=set())
            two = record_attempt(second, instance_id="instance", run_id="run2", params=params, previous_ids=set())
            self.assertNotEqual(one["request_id"], two["request_id"])
            for path, record, run in ((first, one, "run1"), (second, two, "run2")):
                args = {"instance_id": "instance", "run_id": run, "request_id": record["request_id"]}
                mark_final_submit(path, **args)
                record_final_dispatch(
                    path,
                    receipt={"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]},
                    **args,
                )
                state = {**self.state, "client": {"run_id": run}}
                self.assertEqual(persist_result(path, bridge_directory=bridge, state=state, **args)["character_id"], 19)
                self.assertEqual(query_result(bridge, **args)["status"], "completed")
            with self.assertRaises(ClientError):
                query_result(bridge, instance_id="instance", run_id="run2", request_id=one["request_id"])
            with (first / "gui-character.lock").open("a+") as held:
                fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
                backend = MagicMock()
                with patch(
                    "beidou_pilot.gui_character.load_runtime",
                    return_value=SimpleNamespace(running=True, run_id="run1", run_dir=first),
                ):
                    with self.assertRaises(ClientError) as error:
                        create_once(backend, params, directory=first, instance_id="instance", run_id="run1", timeout=1)
                self.assertEqual(error.exception.code, "input_busy")

    def test_result_wait_observes_twice_and_never_inputs(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            args = {"directory": root, "request_id": record["request_id"], "instance_id": "instance", "run_id": "run"}
            mark_final_submit(**args)
            record_final_dispatch(
                receipt={"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]}, **args
            )
            backend = MagicMock()
            backend.read.return_value = self.state
            native = {"instance_id": "instance", "run_id": "run"}
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.BridgeClient") as bridge,
                patch("beidou_pilot.gui_character.time.sleep"),
            ):
                bridge.return_value.snapshot.return_value = native
                self.assertEqual(
                    _wait_creation_result(backend, bridge_directory=root, deadline=float("inf"), **args)[
                        "character_id"
                    ],
                    19,
                )
            self.assertEqual(backend.read.call_count, 2)
            backend.desktop.assert_not_called()

    def test_wait_rejects_changed_or_wrong_identity_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = MagicMock()
            first = {**self.state, "stage": "UNKNOWN"}
            second = self.state
            backend.read.side_effect = [first, second, second]
            args = {
                "directory": root,
                "request_id": "a" * 32,
                "instance_id": "instance",
                "run_id": "run",
                "deadline": float("inf"),
            }
            completed = {"status": "completed", "character_id": 19}
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.BridgeClient") as bridge,
                patch("beidou_pilot.gui_character.time.sleep"),
                patch("beidou_pilot.gui_character.query_result", return_value={"status": "unknown"}),
                patch("beidou_pilot.gui_character.persist_result", return_value=completed) as persist,
            ):
                bridge.return_value.snapshot.return_value = {"instance_id": "instance", "run_id": "run"}
                self.assertEqual(_wait_creation_result(backend, bridge_directory=root, **args), completed)
                self.assertEqual(backend.read.call_count, 3)
                persist.assert_called_once()
                bridge.return_value.snapshot.return_value = {"instance_id": "other", "run_id": "run"}
                self.assertEqual(_wait_creation_result(backend, bridge_directory=root, **args)["status"], "unknown")
                persist.assert_called_once()

    def test_final_submit_once_even_when_result_unknown(self):
        params = CharacterCreation("Example", 1, 21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            (root / "gui-character-name-checked").write_text(record["request_id"])
            backend = MagicMock()
            backend.name = "beidou"
            backend.read.side_effect = lambda kind: {} if kind == "stage" else {"focused_window": {"address": "0x1234"}}
            backend.desktop.return_value = {
                "input_dispatched": True,
                "cancelled": False,
                "timings": [{"action": "click"}],
            }
            args = {
                "directory": root,
                "request_id": record["request_id"],
                "instance_id": "instance",
                "run_id": "run",
                "deadline": float("inf"),
            }
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient"),
                patch(
                    "beidou_pilot.gui_character._final_confirmation_action",
                    return_value={"action": "click", "x": 1121, "y": 624},
                ),
            ):
                self.assertEqual(_submit_creation(backend, params, **args)["status"], "unknown")
                with self.assertRaises(ClientError):
                    _submit_creation(backend, params, **args)
            backend.desktop.assert_called_once()
            self.assertEqual((root / "gui-character-final-dispatched").read_text(), record["request_id"])

    def test_final_submit_dispatch_exception_never_replays(self):
        params = CharacterCreation("Example", 1, 21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            (root / "gui-character-name-checked").write_text(record["request_id"])
            backend = MagicMock()
            backend.name = "beidou"
            backend.read.side_effect = lambda kind: {} if kind == "stage" else {"focused_window": {"address": "0x1234"}}
            backend.desktop.side_effect = OSError("dispatch uncertain")
            args = {
                "directory": root,
                "request_id": record["request_id"],
                "instance_id": "instance",
                "run_id": "run",
                "deadline": float("inf"),
            }
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient"),
                patch(
                    "beidou_pilot.gui_character._final_confirmation_action",
                    return_value={"action": "click", "x": 1121, "y": 624},
                ),
            ):
                with self.assertRaises(OSError):
                    _submit_creation(backend, params, **args)
                with self.assertRaises(ClientError):
                    _submit_creation(backend, params, **args)
            backend.desktop.assert_called_once()
            self.assertFalse((root / "gui-character-final-dispatched").exists())

    def test_category_one_click_unknown_cannot_replay(self):
        params = CharacterCreation("Example", 1, 21002, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            backend = MagicMock()
            backend.name = "beidou"
            backend.read.side_effect = lambda kind: {} if kind == "stage" else {"focused_window": {"address": "0x1234"}}
            backend.desktop.return_value = {
                "input_dispatched": True,
                "cancelled": False,
                "timings": [{"action": "click"}],
            }
            args = {"directory": root, "request_id": record["request_id"], "instance_id": "instance", "run_id": "run"}
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient"),
                patch(
                    "beidou_pilot.gui_character.creation_page_button",
                    side_effect=lambda *a, **kw: {"action": "click", "x": 10, "y": 20}
                    if kw["page"] == "category"
                    else None,
                ),
                patch("beidou_pilot.gui_character.identify_creation_page", return_value="unknown"),
            ):
                result = _navigate_category(backend, params, deadline=time.monotonic() + 0.05, **args)
                self.assertEqual(result["status"], "unknown")
                with self.assertRaises(ClientError):
                    _navigate_category(backend, params, deadline=time.monotonic() + 0.05, **args)
            backend.desktop.assert_called_once()

    def test_category_waits_for_async_next_page_without_repeat_click(self):
        params = CharacterCreation("Example", 1, 21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            backend = MagicMock()
            backend.name = "beidou"
            backend.read.side_effect = lambda kind: {} if kind == "stage" else {"focused_window": {"address": "0x1234"}}
            backend.desktop.return_value = {
                "input_dispatched": True,
                "cancelled": False,
                "timings": [{"action": "click"}],
            }
            action = {"action": "click", "x": 10, "y": 20}
            args = {
                "directory": root,
                "request_id": record["request_id"],
                "instance_id": "instance",
                "run_id": "run",
                "deadline": float("inf"),
            }
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.require_input_idle"),
                patch("beidou_pilot.gui_character.BridgeClient"),
                patch("beidou_pilot.gui_character.time.sleep"),
                patch("beidou_pilot.gui_character.creation_page_button", side_effect=[action, action, None, action]),
            ):
                self.assertEqual(_navigate_category(backend, params, **args)["status"], "name_page")
            backend.desktop.assert_called_once()

    def test_category_failures_and_next_page(self):
        params = CharacterCreation("Example", 1, 21002, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        for scenario in ("identity", "deadline", "write", "dispatch", "success"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
                backend = MagicMock()
                backend.name = "beidou"
                backend.read.side_effect = (
                    lambda kind: {} if kind == "stage" else {"focused_window": {"address": "0x1234"}}
                )
                backend.desktop.return_value = {
                    "input_dispatched": scenario != "dispatch",
                    "cancelled": False,
                    "timings": [{"action": "click"}],
                }
                args = {
                    "directory": root,
                    "request_id": record["request_id"],
                    "instance_id": "instance",
                    "run_id": "different" if scenario == "identity" else "run",
                    "deadline": 0 if scenario == "deadline" else float("inf"),
                }
                with (
                    patch(
                        "beidou_pilot.gui_character.load_runtime",
                        return_value=SimpleNamespace(running=True, run_id="run"),
                    ),
                    patch("beidou_pilot.gui_character.require_input_idle"),
                    patch("beidou_pilot.gui_character.BridgeClient"),
                    patch(
                        "beidou_pilot.gui_character.creation_page_button",
                        return_value={"action": "click", "x": 10, "y": 20},
                    ),
                ):
                    if scenario == "write":
                        with patch("beidou_pilot.gui_character.os.open", side_effect=OSError("write error")):
                            with self.assertRaises(ClientError):
                                _navigate_category(backend, params, **args)
                    elif scenario in ("identity", "dispatch"):
                        with self.assertRaises(ClientError):
                            _navigate_category(backend, params, **args)
                    else:
                        result = _navigate_category(backend, params, **args)
                        self.assertEqual(result["status"], "unknown" if scenario == "deadline" else "name_page")
                if scenario in ("identity", "deadline", "write"):
                    backend.desktop.assert_not_called()
                else:
                    backend.desktop.assert_called_once()

    def test_attempt_is_persisted_once(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids={7})
            self.assertEqual(json.loads((root / "gui-character-attempt.json").read_text()), record)
            self.assertEqual(record["previous_ids"], [7])
            with self.assertRaises(ClientError) as raised:
                record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids={7})
            self.assertEqual(raised.exception.code, "gui_character_already_attempted")
            self.assertEqual(raised.exception.details["request_id"], record["request_id"])
            self.assertEqual(raised.exception.details["run_id"], "run")

    def test_result_persisted_using_login_bridge_contract(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            args = {"instance_id": "instance", "run_id": "run", "request_id": record["request_id"]}
            self.assertEqual(query_result(root, **args)["status"], "unknown")
            self.state["login"]["request_pending"] = True
            self.assertEqual(persist_result(root, bridge_directory=root, state=self.state, **args)["status"], "unknown")
            self.state["login"]["request_pending"] = False
            self.assertEqual(persist_result(root, bridge_directory=root, state=self.state, **args)["status"], "unknown")
            mark_final_submit(root, **args)
            with self.assertRaises(ClientError):
                mark_final_submit(root, **args)
            self.assertEqual(persist_result(root, bridge_directory=root, state=self.state, **args)["status"], "unknown")
            with self.assertRaises(ClientError):
                record_final_dispatch(root, receipt={"input_dispatched": False}, **args)
            record_final_dispatch(
                root, receipt={"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]}, **args
            )
            self.assertEqual(persist_result(root, bridge_directory=root, state=self.state, **args)["character_id"], 19)
            self.assertEqual(query_result(root, **args)["character_id"], 19)
            with self.assertRaises(ClientError):
                query_result(root, **{**args, "run_id": "other"})

    def test_recover_stale_temporary_and_upgrade_nonterminal_results(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        for status in ("accepted", "unknown"):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
                args = {"instance_id": "instance", "run_id": "run", "request_id": record["request_id"]}
                mark_final_submit(root, **args)
                record_final_dispatch(
                    root,
                    receipt={"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]},
                    **args,
                )
                results = root / "login-results"
                results.mkdir()
                result = {"protocol": 1, "operation": "create_character", **args, "status": status}
                path = results / (record["request_id"] + ".json")
                path.write_text(json.dumps(result))
                (results / (record["request_id"] + ".tmp")).write_text("interrupted")
                with patch.object(Path, "replace", side_effect=OSError("interrupted")):
                    with self.assertRaises(ClientError):
                        persist_result(root, bridge_directory=root, state=self.state, **args)
                self.assertEqual(query_result(root, **args)["status"], status)
                self.assertEqual(
                    persist_result(root, bridge_directory=root, state=self.state, **args)["status"], "completed"
                )
                self.assertEqual(query_result(root, **args)["character_id"], 19)
                # A later contradictory snapshot cannot replace a terminal result.
                self.state["login"]["characters"][0]["id"] = 20
                self.assertEqual(
                    persist_result(root, bridge_directory=root, state=self.state, **args)["character_id"], 19
                )
                self.state["login"]["characters"][0]["id"] = 19

    def test_unreadable_terminal_result_is_never_overwritten(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            args = {"instance_id": "instance", "run_id": "run", "request_id": record["request_id"]}
            mark_final_submit(root, **args)
            record_final_dispatch(
                root, receipt={"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]}, **args
            )
            results = root / "login-results"
            results.mkdir()
            path = results / (record["request_id"] + ".json")
            terminal = {"protocol": 1, "operation": "create_character", **args, "status": "rejected"}
            path.write_text(json.dumps(terminal))
            original_open = Path.open

            def guarded_open(target, *positional, **keywords):
                if target == path:
                    raise PermissionError("simulated unreadable result")
                return original_open(target, *positional, **keywords)

            with patch.object(Path, "open", guarded_open):
                with self.assertRaises(ClientError) as error:
                    persist_result(root, bridge_directory=root, state=self.state, **args)
                self.assertEqual(error.exception.code, "login_bridge_unavailable")
            self.assertEqual(json.loads(path.read_text()), terminal)

    def test_rejected_result_is_authoritative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = {"instance_id": "instance", "run_id": "run", "request_id": "a" * 32}
            results = root / "login-results"
            results.mkdir()
            original = {"protocol": 1, "operation": "create_character", **args, "status": "rejected"}
            (results / (args["request_id"] + ".json")).write_text(json.dumps(original))
            self.assertEqual(persist_result(root, bridge_directory=root, state=self.state, **args), original)
            self.assertEqual(query_result(root, **args), original)

    def test_appearance_step_and_cycle(self):
        base = [21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005]
        params = CharacterCreation("Example", 1, 21002, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        seen = [set() for _ in range(8)]
        self.assertEqual(
            plan_observed_appearance_step(params, base, seen), {"status": "step", "field": 0, "control_id": 1011}
        )
        after = base.copy()
        after[0] = 21002
        self.assertTrue(validate_appearance_transition(base, after, 0))
        self.assertEqual(plan_observed_appearance_step(params, after, seen)["status"], "matched")
        seen[0].add(base[0])
        self.assertEqual(plan_observed_appearance_step(params, base, seen)["status"], "unavailable")
        after[1] = 1
        self.assertFalse(validate_appearance_transition(base, after, 0))
        self.assertFalse(validate_appearance_transition(base, base, 0))

    def test_all_wire_fields_map_to_observed_arrows(self):
        from dataclasses import replace

        base = [21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005]
        params = CharacterCreation("Example", 1, *base, True)
        changes = (
            ("face", 21002),
            ("hair", 31040),
            ("hair_color", 0),
            ("skin", 1),
            ("top", 1041002),
            ("bottom", 1061008),
            ("shoes", 1072005),
            ("weapon", 1312004),
        )
        for index, (name, value) in enumerate(changes):
            with self.subTest(field=name):
                self.assertEqual(
                    plan_observed_appearance_step(replace(params, **{name: value}), base, [set() for _ in range(8)]),
                    {"status": "step", "field": index, "control_id": 1011 + index},
                )

    def test_one_appearance_input_requires_verified_change(self):
        base = [21001, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005]
        params = CharacterCreation("Example", 1, 21002, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = record_attempt(root, instance_id="instance", run_id="run", params=params, previous_ids=set())
            focused = {
                "address": "0x1234",
                "vtables": ["0xaf777c", "0xaf7730", "0xaf772c"],
                "width": 225,
                "height": 377,
                "root_rect": {"left": 100, "top": 100, "right": 325, "bottom": 477},
                "buttons": [
                    {
                        "control_id": 1011,
                        "layout_x": 196,
                        "layout_y": 106,
                        "root_rect": {"left": 296, "top": 206, "right": 311, "bottom": 222},
                    }
                ],
            }
            dialog = {
                "instance_id": "instance",
                "client": {"run_id": "run"},
                "unavailable": [],
                "focused_window": focused,
                "script_dialog_open": False,
                "focused_talk_dialog_open": False,
                "registered_talk_dialog_open": False,
            }
            stage = {
                "instance_id": "instance",
                "client": {"run_id": "run"},
                "unavailable": [],
                "login": {"raw_step": 4, "request_pending": False, "transition_pending": False},
                "windows": [
                    {
                        "address": "0x1234",
                        "vtables": focused["vtables"],
                        "raw_appearance_candidates": base,
                        "raw_job_candidate": 1,
                        "raw_appearance_selector": 1,
                        "buttons": [
                            {
                                "control_id": 1011,
                                "enabled": True,
                                "width": 15,
                                "height": 16,
                                "layout_x": 196,
                                "layout_y": 106,
                            }
                        ],
                    }
                ],
            }
            backend = MagicMock(name="backend")
            backend.name = "beidou"
            backend.read.side_effect = lambda kind: stage if kind == "stage" else dialog

            def click(_):
                stage["windows"][0]["raw_appearance_candidates"] = [21002, *base[1:]]
                return {"input_dispatched": True, "cancelled": False, "timings": [{"action": "click"}]}

            backend.desktop.side_effect = click
            native = {
                "instance_id": "instance",
                "run_id": "run",
                "held_keys": [],
                "command": {"status": "idle"},
                "scripts": [],
            }
            with (
                patch(
                    "beidou_pilot.gui_character.load_runtime", return_value=SimpleNamespace(running=True, run_id="run")
                ),
                patch("beidou_pilot.gui_character.BridgeClient") as bridge,
            ):
                bridge.return_value.snapshot.return_value = native
                args = {
                    "directory": root,
                    "request_id": record["request_id"],
                    "instance_id": "instance",
                    "run_id": "run",
                }
                for scripts in (
                    None,
                    [{"status": "running", "control_released": True}],
                    [{"status": "completed", "control_released": False}],
                    [{"status": "completed"}],
                ):
                    native["scripts"] = scripts
                    with self.assertRaises(ClientError):
                        _appearance_step(backend, params, [set() for _ in range(8)], deadline=float("inf"), **args)
                    backend.desktop.assert_not_called()
                native["scripts"] = [{"status": "completed", "control_released": True}]
                focused["address"] = None
                stage["windows"][0]["address"] = None
                with self.assertRaises(ClientError):
                    _appearance_step(backend, params, [set() for _ in range(8)], deadline=float("inf"), **args)
                focused["address"] = stage["windows"][0]["address"] = "0x1234"
                # Even matching projections are unsafe if the control is on another row.
                stage["windows"][0]["buttons"][0]["layout_y"] = 124
                focused["buttons"][0]["layout_y"] = 124
                focused["buttons"][0]["root_rect"] = {"left": 296, "top": 224, "right": 311, "bottom": 240}
                with self.assertRaises(ClientError):
                    _appearance_step(backend, params, [set() for _ in range(8)], deadline=float("inf"), **args)
                stage["windows"][0]["buttons"][0]["layout_y"] = 106
                focused["buttons"][0]["layout_y"] = 106
                focused["buttons"][0]["root_rect"] = {"left": 296, "top": 206, "right": 311, "bottom": 222}
                focused["root_rect"]["right"] = 300
                with self.assertRaises(ClientError):
                    _appearance_step(backend, params, [set() for _ in range(8)], deadline=float("inf"), **args)
                focused["root_rect"]["right"] = 325
                self.assertEqual(
                    _appearance_step(backend, params, [set() for _ in range(8)], deadline=0, **args)["reason"],
                    "timeout",
                )
                backend.desktop.assert_not_called()
                result = _appearance_step(backend, params, [set() for _ in range(8)], deadline=float("inf"), **args)
            self.assertEqual(result["status"], "changed")
            backend.desktop.assert_called_once()

    def test_appearance_timeout_cannot_be_replayed(self):
        params = CharacterCreation("Example", 1, 21002, 31000, 2, 0, 1041011, 1061002, 1072001, 1322005, True)
        with tempfile.TemporaryDirectory() as directory:
            args = {
                "directory": Path(directory),
                "request_id": "a" * 32,
                "instance_id": "instance",
                "run_id": "run",
                "timeout": 1.0,
            }
            with (
                patch("beidou_pilot.gui_character.time.monotonic", side_effect=[0, 2]),
                patch("beidou_pilot.gui_character._appearance_step") as step,
            ):
                self.assertEqual(
                    _apply_appearance(MagicMock(), params, **args), {"status": "unknown", "reason": "timeout"}
                )
                step.assert_not_called()
            with (
                self.assertRaises(ClientError) as error,
            ):
                _apply_appearance(MagicMock(), params, **args)
            self.assertEqual(error.exception.code, "gui_character_already_attempted")

    def test_unverified_parameters_never_dispatched(self):
        params = CharacterCreation("Example", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        require_supported_creation(params)
        invalid = CharacterCreation("中文", 1, 0, 0, 0, 0, 0, 0, 0, 0, False)
        with self.assertRaises(ClientError) as raised:
            require_supported_creation(invalid)
        self.assertEqual(raised.exception.code, "unsupported_capability")
        with tempfile.TemporaryDirectory() as directory:
            backend = MagicMock()
            with self.assertRaises(ClientError) as blocked:
                _apply_appearance(
                    backend,
                    invalid,
                    directory=Path(directory),
                    request_id="a" * 32,
                    instance_id="instance",
                    run_id="run",
                    timeout=1,
                )
            self.assertEqual(blocked.exception.code, "unsupported_capability")
            backend.desktop.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
