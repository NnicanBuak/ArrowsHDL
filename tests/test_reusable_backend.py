"""Reusable native layouts, physical paths, routing and resource budgets."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from arrowasm import Cell, MapError
from compact_layout import Router
from negotiated_routing import NegotiatedRouter
from native_macros import adder_groups, verify_macros,replace_native_cells
from simulation import simulate
from incremental_routing import changed_nets,restore_wires


class ReusableBackendTests(unittest.TestCase):
    def test_reserved_native_contacts_and_adaptive_pins_use_jump_or_diagonal(self):
        node=dict(id='out',output='out',op='AND',inputs=['a','b'])
        graph=dict(inputs={n:[dict(net=n,index=0)] for n in ('a','b')},outputs={},nodes=[node],
                   _blocked_contacts=[[-1,0],[0,-1],[0,1]])
        vertices=[dict(kind='input',net='a'),dict(kind='input',net='b'),
                  dict(kind='gate',node=node,pins=[(-1,0),(0,-1)],pin_policy='adaptive')]
        positions=[(-6,-3),(-6,3),(0,0)]
        router=Router(graph,4,1000,(vertices,positions,{}))
        self.assertEqual(len(router.pins[(0,0)]),2)
        self.assertFalse(set(router.pins[(0,0)])&set(map(tuple,graph['_blocked_contacts'])))
        cells=dict(router.route())
        for name,values in (('a',[0,0,1,1]),('b',[0,1,0,1])):
            e=router.inputs[name][0];cells[tuple(e['fixture'])]=Cell(22,e['rotation'])
        cells[(1,0)]=Cell(23,0)
        self.assertTrue(simulate(cells,dict(ticks=128,hold_ticks=32,
            inputs=[dict(at=router.inputs[n][0]['fixture'],values=v) for n,v in (('a',[0,0,1,1]),('b',[0,1,0,1]))],
            expect=[dict(at=[1,0],values=[0,0,0,1])]))['passed'])
        vertices[-1]=dict(kind='gate',node=node,pins=[(-1,0),(0,-1)])
        with self.assertRaises(MapError):Router(graph,4,1000,(vertices,positions,{}))

    def test_external_wiring_respects_empty_reserved_module_space(self):
        from fixed_wiring import FixedWiring
        fixed={(-2,0):Cell(22,1),(-1,0):Cell(10,1),(0,0):Cell(23,0),(8,0):Cell(23,0)}
        reserved={(x,y) for x in range(2,7) for y in range(-2,3)}
        router=FixedWiring(fixed,reserved=reserved)
        router.connection('across',(1,0),[((7,0),(8,0))])
        result=router.route_all()
        self.assertFalse(set(result)&reserved)
        self.assertTrue(simulate(result,dict(ticks=64,hold_ticks=16,
            inputs=[dict(at=[-2,0],values=[0,1,0,1])],
            expect=[dict(at=[8,0],values=[0,1,0,1])]))['passed'])

    def test_native_recompile_preserves_interfaces_and_rejects_short(self):
        original={(0,-1):Cell(22,2),(0,0):Cell(1,1),(1,0):Cell(1,1),
                  (2,0):Cell(23,0),(9,9):Cell(23,0)}
        replacement={(0,0):Cell(7,1),(1,0):Cell(7,1)}
        updated=replace_native_cells(original,replacement,combinational=True)
        self.assertEqual(updated[(9,9)],original[(9,9)])
        self.assertEqual(original[(0,0)].type,1)
        report=simulate(updated,dict(ticks=32,hold_ticks=8,
            inputs=[dict(at=[0,-1],values=[0,1,0,1])],
            expect=[dict(at=[2,0],values=[0,1,0,1])]))
        self.assertTrue(report['passed'])
        with self.assertRaises(MapError):
            replace_native_cells(original|{(0,1):Cell(23,0)},replacement)
        with self.assertRaises(MapError):
            replace_native_cells(original,{(0,0):Cell(1,1),(1,0):Cell(6,1)},combinational=True)

    def test_incremental_change_preserves_other_output_truth(self):
        nodes=[dict(id='logic',output='o',op='AND',inputs=['a','b']),
               dict(id='parity',output='p',op='XOR',inputs=['a','b']),
               dict(id='out',output='out',op='BUF',inputs=['o']),
               dict(id='parity_out',output='parity_out',op='BUF',inputs=['p'])]
        graph=dict(inputs={'a':[dict(net='a',index=0)],'b':[dict(net='b',index=0)]},
                   outputs={'o':[dict(net='out',index=0)],'p':[dict(net='parity_out',index=0)]},nodes=nodes)
        vertices=[dict(kind='input',net='a'),dict(kind='input',net='b')]+[dict(kind='gate',node=n) for n in nodes]
        positions=[(0,0),(0,8),(8,0),(8,8),(12,0),(12,8)]
        old=NegotiatedRouter(graph,4,1000,(vertices,positions,{}));cells=old.route()
        from copy import deepcopy
        updated=deepcopy(graph);updated['nodes'][0]['op']='OR'
        replacement=vertices[:2]+[dict(kind='gate',node=n,pins=old.pins[p]) for n,p in zip(updated['nodes'],positions[2:])]
        new=NegotiatedRouter(updated,4,1000,(replacement,positions,{}))
        affected=changed_nets(graph,updated)
        restore_wires(new,cells,old.owners,affected)
        self.assertIn('p',set(new.owners.values()))
        result=dict(new.route())
        inputs=[];expect=[]
        vectors=[(0,0),(0,1),(1,0),(1,1)]
        for i,name in enumerate(('a','b')):
            e=new.inputs[name][0];p=tuple(e['fixture']);result[p]=Cell(22,e['rotation'])
            inputs.append(dict(at=list(p),values=[v[i] for v in vectors]))
        for name,truth in (('o',[int(any(v)) for v in vectors]),('p',[sum(v)%2 for v in vectors])):
            p=tuple(new.outputs[name][0]['fixture']);result[p]=Cell(23,0)
            expect.append(dict(at=list(p),values=truth))
        self.assertTrue(simulate(result,dict(ticks=128,hold_ticks=32,inputs=inputs,expect=expect))['passed'])

    def test_native_macros_and_non_game_bindings(self):
        self.assertTrue(verify_macros()['passed'])
        graph={'nodes': [dict(id='sum', output='sum', op='XOR', inputs=['a','b','c']),
                         dict(id='carry', output='carry', op='MAJ', inputs=['c','a','b'])]}
        groups=adder_groups(graph)
        self.assertEqual(len(groups),1)
        self.assertEqual(len(groups[0]['macro'].cells),5)

    def test_jump_buffer_uses_real_fixture_and_preserves_truth(self):
        node=dict(id='pass',op='BUF',inputs=['i'],output='o')
        graph=dict(inputs={'i':[dict(net='i',index=0)]},
                   outputs={'o':[dict(net='o',index=0)]},nodes=[node])
        placement=([dict(kind='input',net='i'),
                    dict(kind='gate',node=node,cell_type=10,pins=[(1,0)])],
                   [(0,0),(2,0)],{})
        for cls in (Router,NegotiatedRouter):
            router=cls(graph,4,100,placement)
            cells=dict(router.route())
            self.assertEqual(router.output_interfaces['o'],(4,0))
            self.assertNotIn((3,0),cells)
            cells[(-1,0)]=Cell(22,1); cells[(4,0)]=Cell(23,0)
            trace=[0,1,0,1]
            report=simulate(cells,dict(ticks=32,hold_ticks=8,
                inputs=[dict(at=[-1,0],values=trace)],
                expect=[dict(at=[4,0],values=trace)]),optimize_cycles=False)
            self.assertTrue(report['passed'])
        for bad in (18,True,99):
            with self.assertRaises(MapError):
                Router(graph,4,100,([placement[0][0],dict(placement[0][1],cell_type=bad)],placement[1],{}))

    def test_limits_are_shared_validated_and_do_not_mutate_scenario(self):
        cells={(0,0):Cell(22,1),(1,0):Cell(23,0)}
        case=dict(ticks=4,inputs=[dict(at=[0,0],values=[1]*4)],
                  expect=[dict(at=[1,0],values=[0,1,1,1])])
        self.assertTrue(simulate(cells,case,limits={'nodes':2,'ticks':4})['passed'])
        self.assertNotIn('limits',case)
        for limits in ({'nodes':1},{'ticks':3},{'ticks':0},{'ticks':True},{'unknown':10}):
            with self.assertRaises(MapError):simulate(cells,case,limits=limits)
        # A former project fork is unnecessary for requests beyond the default.
        longer=dict(ticks=1_000_002,hold_ticks=1_000_002,
                    inputs=[dict(at=[0,0],values=[1])],expect=[dict(at=[1,0],values=[1])])
        with self.assertRaises(MapError):simulate(cells,longer)
        self.assertTrue(simulate(cells,longer,limits={'ticks':2_000_000})['passed'])


if __name__=='__main__':unittest.main()
