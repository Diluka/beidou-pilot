import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from beidou_pilot.errors import ClientError
from beidou_pilot.skill_up import _native_skill_request, preflight_skill_up, skill_up_once


class NativeSkillRequestTest(unittest.TestCase):
    def test_previously_supported_beginner_is_explicitly_unavailable(self):
        backend = SimpleNamespace(name='beidou')
        for skill in (1001, 1009, 22001000):
            with self.subTest(skill=skill), self.assertRaises(ClientError) as raised:
                preflight_skill_up(backend, skill, 1)
            self.assertEqual(raised.exception.code, 'skill_up_unsupported')

    def test_invalid_beginner_pool_is_unavailable(self):
        backend = SimpleNamespace(root=Path('/unused'), name='beidou', instance='default')
        backend.read = unittest.mock.Mock(return_value={'skills_complete': True, 'character_id': 7,
                                                        'skills': {'1000': {'level': 7}}})
        state = {'instance_id': 'i', 'run_id': 'r', 'scene_generation': 8, 'ready': True,
                 'character': {'id': 7, 'job': 100, 'level': 3, 'skill_points': 0}}
        with patch('beidou_pilot.skill_up.BridgeClient') as bridge:
            bridge.return_value.snapshot.return_value = state
            with self.assertRaises(ClientError) as raised:
                preflight_skill_up(backend, 1000, 1)
        self.assertEqual(raised.exception.code, 'skill_points_unavailable')

    def test_beginner_pool_counts_all_families(self):
        backend = SimpleNamespace(root=Path('/unused'), name='beidou', instance='default')
        backend.read = unittest.mock.Mock(return_value={'skills_complete': True, 'character_id': 7,
            'skills': {'1000': {'level': 1}, '10001001': {'level': 2}, '20011002': {'level': 1}}})
        state = {'instance_id': 'i', 'run_id': 'r', 'scene_generation': 8, 'ready': True,
                 'character': {'id': 7, 'job': 100, 'level': 20, 'skill_points': 0}}
        with patch('beidou_pilot.skill_up.BridgeClient') as bridge:
            bridge.return_value.snapshot.return_value = state
            expected = preflight_skill_up(backend, 1000, 2)
        self.assertEqual(expected[3], 2)

    def test_beginner_uses_beginner_pool_and_confirms_one_point(self):
        backend = SimpleNamespace(root=Path('/unused'), name='beidou', instance='default')
        before_skills = {'skills_complete': True, 'character_id': 7, 'skills': {}}
        after_skills = {'skills_complete': True, 'character_id': 7, 'skills': {'1000': {'level': 1}}}
        backend.read = unittest.mock.Mock(side_effect=[before_skills, after_skills])
        state = {'instance_id': 'i', 'run_id': 'r', 'scene_generation': 8, 'ready': True,
                 'character': {'id': 7, 'job': 100, 'level': 3, 'skill_points': 0}}
        with (patch('beidou_pilot.skill_up.BridgeClient') as bridge,
              patch('beidou_pilot.skill_up._native_skill_request', return_value=('request', 1000)) as publish):
            bridge.return_value.snapshot.return_value = state
            result = skill_up_once(backend, 1000)
        self.assertEqual((result['sp_before'], result['sp_after']), (2, 1))
        publish.assert_called_once_with(backend, 'i', 'r', 8, 7, 1000, 1)

    def test_single_preflight_mismatch_never_publishes(self):
        backend = SimpleNamespace(name='beidou')
        expected = ('i', 'r', 7, 2, 0, 8, 1, (3, 100, ()))
        for changed in [('i', 'other', 7, 2, 0, 8, 1, (3, 100, ())),
                        ('i', 'r', 7, 2, 0, 8, 1, (4, 100, ()) )]:
            with (self.subTest(changed=changed),
                  patch('beidou_pilot.skill_up.preflight_skill_up', return_value=changed),
                  patch('beidou_pilot.skill_up._native_skill_request') as publish):
                with self.assertRaises(ClientError) as raised:
                    skill_up_once(backend, 1000, expected)
                self.assertEqual(raised.exception.code, 'skill_state_changed')
                publish.assert_not_called()

    def test_job_change_after_invocation_is_unknown(self):
        backend = SimpleNamespace(root=Path('/unused'), name='beidou', instance='default')
        backend.read = unittest.mock.Mock(return_value={'skills_complete': True, 'character_id': 7,
                                                        'skills': {'2101002': {'level': 4}}})
        before = ('i', 'r', 7, 3, 3, 8, 1, (None, 210, None))
        state = {'instance_id': 'i', 'run_id': 'r', 'scene_generation': 8, 'ready': True,
                 'character': {'id': 7, 'job': 211, 'skill_points': 2}}
        with (patch('beidou_pilot.skill_up.preflight_skill_up', return_value=before),
              patch('beidou_pilot.skill_up._native_skill_request', return_value=('request', 1000)),
              patch('beidou_pilot.skill_up.BridgeClient') as bridge):
            bridge.return_value.snapshot.return_value = state
            with self.assertRaises(ClientError) as raised:
                skill_up_once(backend, 2101002, before)
        self.assertEqual(raised.exception.code, 'skill_up_unknown')

    def test_one_point_requires_observed_level_and_sp(self):
        backend = SimpleNamespace(root=Path('/unused'), name='beidou', instance='default')
        backend.read = lambda _: {'skills_complete': True, 'character_id': 7, 'skills': {'2101002': {'level': 4}}}
        before = ('i', 'r', 7, 3, 3, 8, 2, (None, 210, None))
        state = {'instance_id': 'i', 'run_id': 'r', 'scene_generation': 8, 'ready': True,
                 'character': {'id': 7, 'job': 210, 'skill_points': 2}}
        with (patch('beidou_pilot.skill_up.preflight_skill_up', return_value=before),
              patch('beidou_pilot.skill_up._native_skill_request', return_value=('request', 1000)) as publish,
              patch('beidou_pilot.skill_up.BridgeClient') as bridge):
            bridge.return_value.snapshot.return_value = state
            result = skill_up_once(backend, 2101002, before)
        publish.assert_called_once_with(backend, 'i', 'r', 8, 7, 2101002, 2)
        self.assertEqual((result['level_after'], result['sp_after']), (4, 2))

    def test_rejected_response_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            backend = SimpleNamespace(paths=SimpleNamespace(bridge=path))
            request_id = 'a' * 32
            (path / ('skill-up-result-' + request_id + '.json')).write_text(json.dumps({'protocol': 1, 'request_id': request_id,
                                                                   'status': 'rejected', 'reason': 'skill_up_ineligible'}))
            with patch('beidou_pilot.skill_up.uuid.uuid4', return_value=SimpleNamespace(hex=request_id)):
                with self.assertRaises(ClientError) as raised:
                    _native_skill_request(backend, 'i', 'r', 1, 2, 3, 4)
            self.assertEqual(raised.exception.code, 'skill_up_ineligible')

    def test_existing_request_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "skill-up.txt").write_text("existing")
            backend = SimpleNamespace(paths=SimpleNamespace(bridge=path))
            with self.assertRaises(ClientError) as raised:
                _native_skill_request(backend, "instance", "run", 1, 2, 3, 4)
            self.assertEqual(raised.exception.code, "skill_up_publish_failed")
            self.assertEqual((path / "skill-up.txt").read_text(), "existing")

    def test_timeout_is_unknown_and_request_is_not_republished(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            backend = SimpleNamespace(paths=SimpleNamespace(bridge=path))
            with patch("beidou_pilot.skill_up.time.monotonic", side_effect=[0, 3]):
                with self.assertRaises(ClientError) as raised:
                    _native_skill_request(backend, "instance", "run", 1, 2, 3, 4)
            self.assertEqual(raised.exception.code, "skill_up_unknown")
            self.assertEqual(len((path / "skill-up.txt").read_text().split()), 9)
            self.assertIn('deadline_ms', raised.exception.details)
