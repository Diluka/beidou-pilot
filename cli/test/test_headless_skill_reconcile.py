import pathlib
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from beidou_pilot.backend import ClientError
from beidou_pilot.headless_skill_up import reconcile_skill_up, skill_up


class ReconcileTest(unittest.TestCase):
    def test_two_confirmed_points_keep_each_request(self):
        backend = SimpleNamespace(root=None, name='headless', instance='default')
        def learned(level):
            return {'skills_complete': True, 'character_id': 42, 'beginner_skill_ids': [],
                    'beginner_skill_points': 0, 'skills': {'123': {'level': level}}}
        def state(sp, records=()):
            return {'ready': True, 'instance_id': 'i', 'run_id': 'r', 'scene_generation': 1,
                    'character': {'id': 42, 'skill_points': sp}, 'skill_up_records': list(records)}
        def record(request, level, sp):
            return {'request_id': request, 'instance_id': 'i', 'run_id': 'r', 'character_id': 42,
                    'skill_id': 123, 'level_before': level, 'sp_before': sp, 'status': 'confirmed'}
        backend.read = Mock(side_effect=[learned(0), learned(1), learned(1), learned(2)])
        with patch('beidou_pilot.headless_skill_up.BridgeClient') as cls:
            bridge = cls.return_value
            bridge._control.return_value = nullcontext()
            bridge._ready_state.side_effect = [state(2), state(1)]
            bridge._publish.side_effect = ['first', 'second']
            bridge.snapshot.side_effect = [state(1, [record('first', 0, 2)]),
                                           state(0, [record('first', 0, 2), record('second', 1, 1)])]
            result = skill_up(backend, 123, 2)
            self.assertEqual(result['confirmed_points'], 2)
            self.assertEqual([item['request_id'] for item in result['allocations']], ['first', 'second'])
            self.assertEqual([call.args[3] for call in bridge._publish.call_args_list],
                             [['2', 'r', '42'], ['1', 'r', '42']])

    def test_scene_change_and_unresolved_never_confirm(self):
        for cause in ('scene', 'unresolved'):
            with self.subTest(cause=cause):
                backend = SimpleNamespace(root=None, name='headless', instance='default')
                backend.read = Mock(side_effect=[
                    {'skills_complete': True, 'character_id': 42, 'beginner_skill_ids': [],
                     'beginner_skill_points': 0, 'skills': {}},
                    {'skills_complete': True, 'character_id': 42, 'beginner_skill_ids': [],
                     'beginner_skill_points': 0, 'skills': {'123': {'level': 1}}}])
                before = {'ready': True, 'instance_id': 'i', 'run_id': 'r', 'scene_generation': 1,
                          'character': {'id': 42, 'skill_points': 2}}
                after = {**before, 'scene_generation': 2 if cause == 'scene' else 1,
                         'character': {'id': 42, 'skill_points': 1}, 'skill_up_records': [
                             {'request_id': 'first', 'instance_id': 'i', 'run_id': 'r', 'character_id': 42,
                              'skill_id': 123, 'level_before': 0, 'sp_before': 2, 'status': 'unresolved'}]}
                with patch('beidou_pilot.headless_skill_up.BridgeClient') as cls:
                    bridge = cls.return_value
                    bridge._control.return_value = nullcontext()
                    bridge._ready_state.return_value = before
                    bridge._publish.return_value = 'first'
                    bridge.snapshot.return_value = after
                    with self.assertRaises(ClientError) as caught:
                        skill_up(backend, 123, 2)
                    self.assertEqual(caught.exception.code, 'skill_up_unknown')
                    self.assertEqual(caught.exception.details['confirmed'], [])
                    self.assertEqual(bridge._publish.call_count, 1)

    def test_native_record_contract(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temp:
            binary = pathlib.Path(temp) / 'contract'
            subprocess.run(['g++', '-std=c++20', '-I', str(root / 'headless/src'),
                            '-I', str(root / 'third_party/json/single_include'),
                            str(root / 'cli/test/headless_skill_records_contract.cpp'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_only_same_run_character_and_skill_can_confirm(self):
        class Backend:
            root = None
            name = 'headless'
            instance = 'default'
        state = {'ready': True, 'instance_id': 'inst', 'run_id': 'run',
                 'character': {'id': 42}, 'skill_up_records': [
                     {'request_id': 'a' * 32, 'run_id': 'run', 'instance_id': 'inst',
                      'character_id': 42, 'skill_id': 1000, 'status': 'confirmed'}]}
        with patch('beidou_pilot.headless_skill_up.BridgeClient') as bridge:
            bridge.return_value.snapshot.return_value = state
            self.assertEqual(reconcile_skill_up(Backend(), 1000, 'a' * 32)['status'], 'confirmed')
            state['run_id'] = 'another'
            self.assertEqual(reconcile_skill_up(Backend(), 1000, 'a' * 32)['status'], 'unresolved')
            state['run_id'] = 'run'
            self.assertEqual(reconcile_skill_up(Backend(), 1001, 'a' * 32)['status'], 'unresolved')
            self.assertEqual(reconcile_skill_up(Backend(), 1000, 'b' * 32)['status'], 'unresolved')
            bridge.return_value._publish.assert_not_called()
