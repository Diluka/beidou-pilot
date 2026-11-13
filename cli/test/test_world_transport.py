import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '.agents/skills/beidou-game-guide/tools'))
from route_graph import Edge, Scene, paid_route, transport_edges


def scene(number, target=None):
    portals = [] if target is None else [Edge('p', target, None, None, [[0, 0]], [])]
    return Scene(str(number), None, portals)


class TransportTest(unittest.TestCase):
    def test_taxi_evidence_and_conditions(self):
        edges = transport_edges()
        self.assertEqual(next(e['cost'] for e in edges[100000000] if e['to'] == 101000000), 800)
        self.assertIn('4032313', edges[104000000][0]['conditions'])
        self.assertIn('4032288', edges[101000000][0]['conditions'])
        self.assertNotIn(221000000, [e['to'] for e in edges[220000000]])

    def test_multiple_transport_and_portals(self):
        ids = [1, 100000000, 101000000, 120000000, 2]
        scenes = {i: scene(i) for i in ids}
        scenes[1] = scene(1, 100000000)
        scenes[101000000] = scene(101000000, 2)
        result = paid_route(scenes, 1, 2, 'cost')
        self.assertEqual(result['cost'], 800)
        self.assertEqual(result['planning_legs'], 3)
        self.assertEqual(result['steps'][1]['npc'], 1012000)

    def test_airship_details(self):
        edge = transport_edges()[200000100][0]
        self.assertEqual(edge['check_map'], 200000111)
        self.assertIn('4031047', edge['conditions'])

    def test_paid_detour_dominated_by_free_route_is_not_recommended(self):
        start, destination, taxi_stop = 100000000, 104000000, 120000000
        scenes = {start: scene(start, destination), destination: scene(destination),
                  taxi_stop: scene(taxi_stop, start)}
        self.assertIsNone(paid_route(scenes, start, destination, 'cost'))
        self.assertIsNone(paid_route(scenes, start, start, 'cost'))

    def test_no_candidate(self):
        self.assertIsNone(paid_route({1: scene(1), 2: scene(2)}, 1, 2, 'cost'))
