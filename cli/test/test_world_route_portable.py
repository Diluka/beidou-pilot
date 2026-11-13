import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[2] / '.agents/skills/beidou-game-guide/tools'


class PortableWorldRouteTest(unittest.TestCase):
    def test_standalone_graph_and_transport(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / 'skill'
            tools = skill / 'tools'
            refs = skill / 'references'
            tools.mkdir(parents=True)
            refs.mkdir()
            for name in ('world_route.py', 'route_graph.py'):
                shutil.copyfile(TOOLS / name, tools / name)
            def edge(target, script=None):
                return dict(name='out', target=target, target_name='in', script=script,
                            sources=[[1, 2]], receivers=[[3, 4]])
            data = {'version': 1, 'source': 'fixture', 'maps': [
                {'id': 100000000, 'name': '甲', 'link': 101000000, 'edges': [edge(2), edge(103000000, 'dynamic')]},
                {'id': 2, 'name': '中', 'link': None, 'edges': [edge(103000000)]},
                {'id': 103000000, 'name': '乙', 'link': None, 'edges': []},
            ]}
            (refs / 'world-graph.json').write_text(json.dumps(data), encoding='utf-8')
            env = {'PATH': os.environ.get('PATH', ''), 'CLIENT_ROOT': '/nonexistent',
                   'MAPLE_RESOURCES_CONFIG': '/nonexistent', 'PYTHONDONTWRITEBYTECODE': '1'}
            result = subprocess.run([sys.executable, str(tools / 'world_route.py'), '甲', '乙'],
                                    cwd=tmp, env=env, text=True, capture_output=True, check=True)
            report = json.loads(result.stdout)
            self.assertIn('换 2 次场景', report['route'])
            paid = report['paid_candidates']['lowest_listed_fare']
            self.assertEqual(paid['cost'], 1000)
            self.assertEqual(paid['steps'][0]['kind'], 'taxi')
            self.assertIn('jobId==0', paid['steps'][0]['conditions'])
            reverse = subprocess.run([sys.executable, str(tools / 'world_route.py'), '乙', '甲'],
                                     cwd=tmp, env=env, text=True, capture_output=True, check=True)
            self.assertIn('未在已收录', json.loads(reverse.stdout)['route'])


if __name__ == '__main__':
    unittest.main()
