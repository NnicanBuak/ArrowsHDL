"""Physical truth, pulse width and protected fixtures after direction search."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from arrowasm import Cell
from negotiated_routing import NegotiatedRouter
from simulation import simulate
from route_optimization import optimize_router


def circuit(optimize, blocked=(),first_input='a'):
    logic = dict(id='logic', output='logic', op='AND', inputs=[first_input, 'b'])
    output = dict(id='out', output='out', op='BUF', inputs=['logic'])
    graph = dict(inputs={n: [dict(net=n, index=0)] for n in (first_input, 'b')},
                 outputs={'out': [dict(net='out', index=0)]}, nodes=[logic, output],
                 _route_optimization={'passes': 2} if optimize else False,
                 _blocked_contacts=[list(p) for p in blocked])
    placement = ([dict(kind='input', net=first_input), dict(kind='input', net='b'),
                  dict(kind='gate', node=logic, pins=[(5, 6), (6, 7)]),
                  dict(kind='gate', node=output, rotation=0, pins=[(6, 3)])],
                 [(0, 4), (0, 8), (6, 6), (6, 2)], {})
    router = NegotiatedRouter(graph, 4, 1000, placement)
    router.route()
    return router


def check_truth(router):
    cells = dict(router.cells); inputs = []
    for name, values in zip(router.inputs,([0, 0, 1, 1, 0],[0, 1, 0, 1, 0])):
        entry = router.inputs[name][0]; fixture = tuple(entry['fixture'])
        cells[fixture] = Cell(22, entry['rotation'])
        inputs.append(dict(at=list(fixture), values=values))
    target = router.outputs['out'][0]['fixture']; cells[tuple(target)] = Cell(23, 0)
    report = simulate(cells, dict(ticks=160, hold_ticks=32, inputs=inputs,
                                 expect=[dict(at=target, values=[0, 0, 0, 1, 0])]),
                      optimize_cycles=False)
    if not report['passed']:
        raise AssertionError(report['failures'])


class RouteOptimizationTests(unittest.TestCase):
    def test_and_turns_towards_receiver_and_preserves_all_truth_values(self):
        before = circuit(False); after = circuit(True)
        self.assertLess(len(after.cells), len(before.cells))
        self.assertEqual(after.cells[(6, 6)].rotation, 0)
        self.assertEqual(after.pins[(6, 6)], before.pins[(6, 6)])
        self.assertEqual(after.outputs, before.outputs)
        for router in (before, after):
            check_truth(router)
        self.assertEqual(after.route_optimization['gate_directions'], 4)

    def test_rotation_cannot_use_reserved_native_space_or_input_side(self):
        router = circuit(True, blocked=[(6, 5)])
        self.assertEqual(router.cells[(6, 6)].rotation, 1)
        self.assertNotIn((6, 5), router.cells)
        self.assertGreater(router.route_optimization['rejected_trials'], 0)
        check_truth(router)

    def test_mutable_foreign_wire_does_not_freeze_and_output_direction(self):
        router=circuit(False,first_input='z')
        router.clear_net('z');router.clear_net('logic')
        path=[(0,4),(2,4),(4,4),(6,4),(6,5),(5,6)]
        for p in path[1:-1]:
            if p not in router.cells:router.add(p,'z')
        for p,q in zip(path,path[1:]):router.outs[p].add(q)
        path=[(7,6),(9,6),(9,4),(8,3),(6,3)]
        for p in path[1:-1]:router.add(p,'logic')
        for p,q in zip(path,path[1:]):router.outs[p].add(q)
        router.finish();check_truth(router)
        before=len(router.cells)
        optimize_router(router)
        self.assertEqual(router.cells[(6,6)].rotation,0)
        self.assertLess(len(router.cells),before)
        self.assertTrue(any('z' in c['rerouted_neighbors'] for c in router.route_optimization['changes']))
        check_truth(router)

    def test_and_output_rotates_independently_of_direct_not_macro(self):
        delay = dict(id='delay', output='delay', op='NOT', inputs=['input'])
        edge = dict(id='edge', output='edge', op='AND', inputs=['input', 'delay'])
        output = dict(id='out', output='out', op='BUF', inputs=['edge'])
        graph = dict(inputs={'input': [dict(net='input', index=0)]},
                     outputs={'out': [dict(net='out', index=0)]}, nodes=[delay, edge, output])
        vertices = [dict(kind='input', net='input'),
                    dict(kind='gate', node=delay, pins=[(6, 5)]),
                    dict(kind='gate', node=edge, pins=[(6, 5), (6, 6)]),
                    dict(kind='gate', node=output, rotation=0, pins=[(7, 3)])]
        positions = [(0, 5), (6, 6), (7, 6), (7, 2)]
        traces = []
        for optimized in (False, True):
            variant = dict(graph, _route_optimization=optimized)
            router = NegotiatedRouter(variant, 4, 1000, (deepcopy(vertices), positions[:], {}))
            cells = dict(router.route())
            entry = router.inputs['input'][0]; fixture = tuple(entry['fixture'])
            cells[fixture] = Cell(22, entry['rotation'])
            target = tuple(router.outputs['out'][0]['fixture']); cells[target] = Cell(23, 0)
            values = [0]*20+[1]*20+[0]*20+[1]*20+[0]*20
            report = simulate(cells, dict(ticks=len(values), hold_ticks=1,
                              inputs=[dict(at=list(fixture), values=values)],
                              expect=[], observe=[list(target)]), optimize_cycles=False)
            self.assertFalse(report['failures'])
            traces.append(report['observations'][0]['values'])
            self.assertEqual(router.cells[(6, 6)], Cell(15, 1))
            if optimized:
                self.assertEqual(router.cells[(7, 6)].rotation, 0)
        for trace in traces:
            self.assertEqual(sum(trace), 2, 'Each input edge must produce exactly one one-tick pulse')

    def test_optimized_directions_survive_frozen_output_face_search(self):
        from output_layout import route_with_outputs
        logic=dict(id='logic',output='logic',op='AND',inputs=['a','b'])
        neg=dict(id='neg',output='neg',op='NOT',inputs=['logic'])
        out=dict(id='out',output='out',op='BUF',inputs=['neg'])
        graph=dict(inputs={n:[dict(net=n,index=0)] for n in ('a','b')},
                   outputs={'out':[dict(net='out',index=0)]},nodes=[logic,neg,out],
                   _route_optimization=True,_physical_optimize=False)
        vertices=[dict(kind='input',net='a'),dict(kind='input',net='b'),
                  dict(kind='gate',node=logic,pins=[(5,6),(6,7)]),
                  dict(kind='gate',node=neg,pins=[(6,3)]),
                  dict(kind='gate',node=out,pins=[(11,2)])]
        cells,router=route_with_outputs(graph,(vertices,[(0,4),(0,8),(6,6),(6,2),(12,2)],{}),1000)
        self.assertEqual(cells[(6,6)].rotation,0)
        self.assertTrue(router.output_search['core_connections_verified'])
        inputs=[];physical=dict(cells)
        for name,values in (('a',[0,0,1,1]),('b',[0,1,0,1])):
            e=router.inputs[name][0];p=tuple(e['fixture']);physical[p]=Cell(22,e['rotation'])
            inputs.append(dict(at=list(p),values=values))
        p=tuple(router.outputs['out'][0]['fixture']);physical[p]=Cell(23,0)
        self.assertTrue(simulate(physical,dict(ticks=128,hold_ticks=32,inputs=inputs,
            expect=[dict(at=list(p),values=[1,1,1,0])]),optimize_cycles=False)['passed'])


if __name__ == '__main__':
    unittest.main()
