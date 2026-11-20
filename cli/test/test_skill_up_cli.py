import unittest
import tempfile
import fcntl
import io
from pathlib import Path
from contextlib import nullcontext, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from beidou_pilot.backend import ClientError
from beidou_pilot.cli import dispatch, main, parser
from beidou_pilot.headless_skill_up import skill_up


def state(level_sp=3):
    return {"instance_id": "i", "run_id": "r", "character": {"id": 1, "skill_points": level_sp}}


class SkillUpCliTests(unittest.TestCase):
    def test_arguments(self):
        args = parser().parse_args(["skill-up", "2101002", "--points", "2"])
        self.assertEqual((args.skill_id, args.points), (2101002, 2))

    def test_gui_main_holds_single_control_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = SimpleNamespace(root=root, name="beidou", instance="default", paths=SimpleNamespace(
                state_directory=root, input_lock=root / "input.lock"))

            def verify_lock(*args):
                with backend.paths.input_lock.open("a+") as handle:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return ("i", "r", 1, 3, 0, 1, 1, None)

            with (patch("beidou_pilot.cli.Backend", return_value=backend),
                  patch("beidou_pilot.skill_up.preflight_skill_up", side_effect=verify_lock) as preflight,
                  patch("beidou_pilot.skill_up.skill_up_once", return_value={"level_after": 1}) as once,
                  redirect_stdout(io.StringIO())):
                self.assertEqual(main(["skill-up", "1000", "--json"]), 0)
                preflight.assert_called_once_with(backend, 1000, 1)
                once.assert_called_once_with(backend, 1000, ("i", "r", 1, 3, 0, 1, 1, None))

    def test_gui_running_lua_blocks_skill_up_before_desktop_input(self):
        args = parser().parse_args(["skill-up", "2101002"])
        backend = SimpleNamespace(root=Path("/unused"), name="beidou", instance="default")
        with (patch("beidou_pilot.bridge.BridgeClient") as bridge_cls,
              patch("beidou_pilot.skill_up.preflight_skill_up") as preflight,
              patch("beidou_pilot.skill_up.skill_up_once") as once):
            bridge = bridge_cls.return_value
            bridge.directory.__truediv__.return_value.exists.return_value = True
            bridge.snapshot.return_value = {"scripts": [{"id": "script-1", "status": "running"}]}
            with self.assertRaises(ClientError) as caught:
                dispatch(backend, args)
            self.assertEqual(caught.exception.code, "input_busy")
            self.assertEqual(caught.exception.details["script_id"], "script-1")
            preflight.assert_not_called()
            once.assert_not_called()

    def test_gui_batch_stops_if_identity_changes(self):
        args = parser().parse_args(["skill-up", "2101002", "--points", "2"])
        backend = SimpleNamespace(root=Path("/nonexistent"), instance="default", name="beidou")
        states = [("i", "r", 1, 3, 0, 1, 2), ("i", "other", 1, 2, 1, 1, 1)]
        with (patch("beidou_pilot.skill_up.preflight_skill_up", side_effect=states),
              patch("beidou_pilot.skill_up.skill_up_once", return_value={"level_after": 1}) as once):
            with self.assertRaises(ClientError) as caught:
                dispatch(backend, args)
        self.assertEqual(caught.exception.code, "skill_state_changed")
        self.assertEqual(len(caught.exception.details["confirmed"]), 1)
        once.assert_called_once()

    def test_gui_batch_gate_rejection_preserves_confirmed(self):
        args = parser().parse_args(["skill-up", "2101002", "--points", "2"])
        backend = SimpleNamespace(root=Path("/nonexistent"), instance="default", name="beidou")
        states = [("i", "r", 1, 3, 0, 1, 2), ("i", "r", 1, 2, 1, 1, 1)]
        with (patch("beidou_pilot.skill_up.preflight_skill_up", side_effect=states),
              patch("beidou_pilot.skill_up.skill_up_once", side_effect=[{"level_after": 1},
                    ClientError("skill_up_gate_closed", "门禁关闭")]) as once):
            with self.assertRaises(ClientError) as caught:
                dispatch(backend, args)
        self.assertEqual(caught.exception.code, "skill_up_gate_closed")
        self.assertEqual(caught.exception.details["confirmed"], [{"level_after": 1}])
        self.assertEqual(once.call_count, 2)

    def test_gui_batch_capacity_rejection_preserves_confirmed(self):
        args = parser().parse_args(["skill-up", "2101002", "--points", "2"])
        backend = SimpleNamespace(root=Path("/nonexistent"), instance="default", name="beidou")
        states = [("i", "r", 1, 3, 0, 1, 2), ("i", "r", 1, 2, 1, 1, 1)]
        with (patch("beidou_pilot.skill_up.preflight_skill_up", side_effect=states),
              patch("beidou_pilot.skill_up.skill_up_once", side_effect=[{"level_after": 1},
                    ClientError("skill_up_insufficient_level_capacity", "等级余量不足")]) as once):
            with self.assertRaises(ClientError) as caught:
                dispatch(backend, args)
        self.assertEqual(caught.exception.code, "skill_up_insufficient_level_capacity")
        self.assertEqual(caught.exception.details["confirmed"], [{"level_after": 1}])
        self.assertEqual(once.call_count, 2)

    def test_headless_dispatch(self):
        args = parser().parse_args(["skill-up", "2101002", "--points", "2"])
        backend = SimpleNamespace(name="headless")
        with patch("beidou_pilot.headless_skill_up.skill_up", return_value={"ok": True}) as call:
            self.assertEqual(dispatch(backend, args), {"ok": True})
            call.assert_called_once_with(backend, 2101002, 2)

    def test_single_point_observed(self):
        backend = SimpleNamespace(root=None, name="headless", instance="default")
        backend.read = unittest.mock.Mock(side_effect=[{"skills_complete": True, "character_id": 1, "beginner_skill_ids": [], "beginner_skill_points": 3, "skills": {}},
                                                       {"skills_complete": True, "character_id": 1, "beginner_skill_ids": [], "beginner_skill_points": 3, "skills": {"42": {"level": 1}}}])
        with patch("beidou_pilot.headless_skill_up.BridgeClient") as cls:
            bridge = cls.return_value
            bridge._control.return_value = nullcontext()
            bridge._ready_state.return_value = state()
            bridge._publish.return_value = "request"
            bridge.snapshot.return_value = state(2)
            result = skill_up(backend, 42, 1)
            bridge._publish.assert_called_once_with(state(), "skill-up", 42, ["1"])
            self.assertEqual(result["confirmed_points"], 1)

    def test_preflight_rejection_stops_without_next_packet(self):
        backend = SimpleNamespace(root=None, name="headless", instance="default")
        backend.read = unittest.mock.Mock(return_value={"skills_complete": True, "character_id": 1, "beginner_skill_ids": [], "beginner_skill_points": 3, "skills": {}})
        with patch("beidou_pilot.headless_skill_up.BridgeClient") as cls:
            bridge = cls.return_value
            bridge._control.return_value = nullcontext()
            bridge._ready_state.return_value = state()
            bridge._publish.return_value = "request"
            bridge._wait.side_effect = ClientError("bridge_command_rejected", "rejected", {"reason": "skill_not_eligible"})
            with self.assertRaises(ClientError) as error:
                skill_up(backend, 42, 3)
            self.assertEqual(error.exception.code, "bridge_command_rejected")
            self.assertEqual(error.exception.details["confirmed"], [])
            bridge._publish.assert_called_once_with(state(), "skill-up", 42, ["3"])

    def test_partial_success_then_timeout(self):
        backend = SimpleNamespace(root=None, name="headless", instance="default")
        backend.read = unittest.mock.Mock(side_effect=[{"skills_complete": True, "character_id": 1, "beginner_skill_ids": [], "beginner_skill_points": 3, "skills": {}},
            {"skills_complete": True, "character_id": 1, "beginner_skill_ids": [], "beginner_skill_points": 3, "skills": {"42": {"level": 1}}},
            {"skills_complete": True, "character_id": 1, "beginner_skill_ids": [], "beginner_skill_points": 3, "skills": {"42": {"level": 1}}}])
        with patch("beidou_pilot.headless_skill_up.BridgeClient") as cls:
            bridge = cls.return_value
            bridge._control.return_value = nullcontext()
            bridge._ready_state.side_effect = [state(), state(2)]
            bridge._publish.side_effect = ["first", "second"]
            bridge._wait.side_effect = [state(2), ClientError("bridge_timeout", "timeout")]
            bridge.snapshot.return_value = state(2)
            with self.assertRaises(ClientError) as error:
                skill_up(backend, 42, 2)
            self.assertEqual(error.exception.code, "skill_up_unknown")
            self.assertEqual(len(error.exception.details["confirmed"]), 1)
            self.assertEqual(bridge._publish.call_count, 2)
            self.assertEqual(bridge._publish.call_args.args[3], ["1"])

    def test_second_point_prepublication_failure_preserves_progress(self):
        for failure in ("ready", "read", "publish"):
            with self.subTest(failure=failure):
                backend = SimpleNamespace(root=None, name="headless", instance="default")
                first = {"skills_complete": True, "character_id": 1, "beginner_skill_ids": [], "beginner_skill_points": 3, "skills": {}}
                second = {"skills_complete": True, "character_id": 1, "beginner_skill_ids": [], "beginner_skill_points": 3, "skills": {"42": {"level": 1}}}
                backend.read = unittest.mock.Mock(side_effect=[first, second, ClientError("read_failed", "read") if failure == "read" else second])
                with patch("beidou_pilot.headless_skill_up.BridgeClient") as cls:
                    bridge = cls.return_value
                    bridge._control.return_value = nullcontext()
                    bridge._ready_state.side_effect = [state(), ClientError("not_ready", "ready") if failure == "ready" else state(2)]
                    bridge._publish.side_effect = ["first", ClientError("write_failed", "write") if failure == "publish" else "second"]
                    bridge.snapshot.return_value = state(2)
                    with self.assertRaises(ClientError) as error:
                        skill_up(backend, 42, 2)
                    self.assertEqual(error.exception.code, {"ready": "not_ready", "read": "read_failed", "publish": "write_failed"}[failure])
                    self.assertEqual(len(error.exception.details["confirmed"]), 1)
                    self.assertNotEqual(error.exception.code, "skill_up_unknown")

    def test_beginner_uses_observed_beginner_sp(self):
        backend = SimpleNamespace(root=None, name="headless", instance="default")
        backend.read = unittest.mock.Mock(side_effect=[
            {"skills_complete": True, "character_id": 1, "beginner_skill_ids": [1000], "beginner_skill_points": 3, "skills": {}},
            {"skills_complete": True, "character_id": 1, "beginner_skill_ids": [1000], "beginner_skill_points": 2, "skills": {"1000": {"level": 1}}},
        ])
        with patch("beidou_pilot.headless_skill_up.BridgeClient") as cls:
            bridge = cls.return_value
            bridge._control.return_value = nullcontext()
            bridge._ready_state.return_value = state(0)
            bridge._publish.return_value = "request"
            bridge.snapshot.return_value = state(0)
            result = skill_up(backend, 1000, 1)
            self.assertEqual(result["allocations"][0]["sp_after"], 2)

    def test_missing_beginner_observation_fails_before_publish(self):
        backend = SimpleNamespace(root=None, name="headless", instance="default")
        backend.read = unittest.mock.Mock(return_value={"skills_complete": True, "character_id": 1, "skills": {}})
        with patch("beidou_pilot.headless_skill_up.BridgeClient") as cls:
            bridge = cls.return_value
            bridge._control.return_value = nullcontext()
            bridge._ready_state.return_value = state()
            with self.assertRaises(ClientError) as error:
                skill_up(backend, 1000, 1)
            self.assertEqual(error.exception.code, "skills_unavailable")
            bridge._publish.assert_not_called()

    def test_timeout_is_unknown_and_never_replayed(self):
        backend = SimpleNamespace(root=None, name="headless", instance="default")
        backend.read = unittest.mock.Mock(return_value={"skills_complete": True, "character_id": 1, "beginner_skill_ids": [], "beginner_skill_points": 3, "skills": {}})
        with patch("beidou_pilot.headless_skill_up.BridgeClient") as cls:
            bridge = cls.return_value
            bridge._control.return_value = nullcontext()
            bridge._ready_state.return_value = state()
            bridge._publish.return_value = "request"
            bridge._wait.side_effect = ClientError("bridge_timeout", "timeout")
            with self.assertRaises(ClientError) as error:
                skill_up(backend, 42, 2)
            self.assertEqual(error.exception.code, "skill_up_unknown")
            bridge._publish.assert_called_once_with(state(), "skill-up", 42, ["2"])
