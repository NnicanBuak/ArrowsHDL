"""Native engine regressions for dependencies a wire-only graph misses."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from arrowasm import Cell,MapError
from native_rules import dependency_links,validate_gate_rule,remove_passive_walls
from timing import causal_depths,level_arrivals
from simulation import simulate
from test_simulator import oracle


class NativeRuleTests(unittest.TestCase):
    def test_passive_wall_removal_preserves_every_active_arrow_trace(self):
        # Includes a detector reading the wall and a blocker aimed at it.
        cells={(-1,0):Cell(22,1),(0,0):Cell(25,0),(1,0):Cell(5,1),
               (2,0):Cell(23,0),(0,1):Cell(3,0),(0,2):Cell(22,0),
               (-1,-2):Cell(22,1),(0,-2):Cell(1,1),(1,-2):Cell(23,0)}
        reduced=remove_passive_walls(cells)
        self.assertEqual(set(cells)-set(reduced),{(0,0)})
        active=[list(p) for p in reduced]
        signals=[dict(at=list(p),values=[0,1,1,0]*8) for p in ((-1,0),(0,2),(-1,-2))]
        original=simulate(cells,dict(ticks=32,inputs=signals,expect=[],observe=active))
        updated=simulate(reduced,dict(ticks=32,inputs=signals,expect=[],observe=active))
        self.assertEqual(original['observations'],updated['observations'])

    def test_native_threshold_cannot_silently_become_three_input_and(self):
        for op,count in (('AND',3),('AND',1),('MAJ',4),('BUF',2),('OR',12)):
            with self.assertRaises(MapError):validate_gate_rule(dict(op=op,inputs=['i']*count))
        for op,count in (('AND',2),('MAJ',3),('ATLEAST2',11),('XOR',11),('NOT',11)):
            validate_gate_rule(dict(op=op,inputs=['i']*count))
        from compact_layout import Router
        from arrow_layout import place_sparse
        node=dict(id='out',op='AND',inputs=['a','b','c'],output='out')
        graph=dict(inputs={n:[dict(index=0,net=n)] for n in ('a','b','c')},
                   outputs={'out':[dict(index=0,net='out')]},nodes=[node])
        with self.assertRaises(MapError):Router(graph,4,1000)
        with self.assertRaises(MapError):place_sparse(graph)

    def test_all_eleven_receiver_contacts_and_assignment_conflicts(self):
        from pin_planning import incoming_contacts,choose_input_contacts
        from compact_layout import wire_cell
        from arrow_layout import destinations
        contacts=incoming_contacts((0,0),excluded=[(1,0)])
        self.assertEqual(len(contacts),11)
        for p in contacts:self.assertEqual(list(destinations(p,wire_cell(p,{(0,0)}))),[(0,0)])
        nets=[str(i) for i in range(11)]
        sources=dict(zip(nets,contacts))
        matched=choose_input_contacts(nets,(0,0),sources,lambda p,n:True,excluded=[(1,0)])
        self.assertEqual(matched,contacts)
        # Greedy allocation would consume the only contact available to b.
        matched=choose_input_contacts(['a','b'],(0,0),{'a':(-1,0),'b':(-1,0)},
            lambda p,n:p in [(-1,0),(0,-1)] if n=='a' else p==(-1,0))
        self.assertEqual(matched,[(0,-1),(-1,0)])

    def compare_engine(self,cells,inputs,ticks):
        points=list(cells)
        expected=oracle(cells,dict(ticks=ticks,inputs=inputs,expect=[dict(at=list(p)) for p in points]))
        for optimized in (False,True):
            report=simulate(cells,dict(ticks=ticks,inputs=inputs,expect=[],observe=[list(p) for p in points]),
                            optimize_cycles=optimized)
            self.assertEqual({tuple(p['at']):p['values'] for p in report['observations']},expected)
        return expected

    def test_detector_reads_pending_delay_without_emission_to_detector(self):
        cells={(-1,0):Cell(22,1),(0,0):Cell(4,0),(0,-1):Cell(23,0),
               (1,0):Cell(5,1),(2,0):Cell(23,0)}
        trace=self.compare_engine(cells,[dict(at=[-1,0],values=[1]+[0]*11)],12)
        self.assertEqual(trace[(0,0)][1],0)  # PENDING is not an emitted signal.
        self.assertEqual(trace[(1,0)][2],1)  # Detector nevertheless reads it.
        self.assertEqual(trace[(0,-1)][2],0)
        self.assertIn((1,0),dependency_links(cells)[(0,0)])
        self.assertIsNotNone(causal_depths(cells,sources=[(-1,0)])[(2,0)])

    def test_reciprocal_arrows_retain_a_pulse_and_require_feedback_contract(self):
        cells={(-1,0):Cell(22,1),(0,0):Cell(1,1),(1,0):Cell(1,3)}
        trace=self.compare_engine(cells,[dict(at=[-1,0],values=[1]+[0]*15)],16)
        self.assertTrue(any(trace[(0,0)][8:]))
        self.assertTrue(any(trace[(1,0)][8:]))
        links=dependency_links(cells)
        self.assertIn((1,0),links[(0,0)])
        self.assertIn((0,0),links[(1,0)])
        with self.assertRaises(MapError):causal_depths(cells)

    def test_generators_ignore_ordinary_inputs_but_remain_blockable(self):
        for kind in (2,9,21):
            cells={(0,0):Cell(kind,0),(1,0):Cell(1,3)}
            self.assertNotIn((0,0),dependency_links(cells)[(1,0)])
            causal_depths(cells)
            cells[(1,0)]=Cell(3,3)
            self.assertIn((0,0),dependency_links(cells)[(1,0)])
        cells={(0,0):Cell(22,1),(1,0):Cell(17,1),(2,0):Cell(1,1)}
        self.assertNotIn((1,0),level_arrivals(cells,{(0,0):0}))
        self.assertNotIn((2,0),level_arrivals(cells,{(0,0):0}))


if __name__=='__main__':unittest.main()
