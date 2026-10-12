"""Public builds preserve tick semantics, independent entropy and deadlines."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import arrowshdl
from arrowshdl.test_harness import add_fixture
from arrowshdl.technology_mapping import merge_duplicate_logic


class PublicApiTests(unittest.TestCase):
    def test_optional_cycle_optimizer_failure_preserves_simulation(self):
        from arrowshdl.simulation import simulate
        from nodejs_wheel import node
        from subprocess import CompletedProcess
        cells={(0,0):arrowshdl.Cell(22,1),(1,0):arrowshdl.Cell(1,1),(2,0):arrowshdl.Cell(23,0)}
        scenario=dict(ticks=40,hold_ticks=10,inputs=[dict(at=[0,0],values=[0,1,0,1])],
                      expect=[dict(at=[2,0],values=[0,1,0,1])])
        calls=0
        def limited(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==1:return CompletedProcess(args,2,'','Error: Cycle search budget exceeded; use --no-optimize-cycles')
            return node(*args,**kwargs)
        with patch('nodejs_wheel.node',side_effect=limited):
            result=simulate.__wrapped__(cells,scenario)
        self.assertTrue(result['passed'],result['failures'])
        self.assertFalse(result['cycle_optimization']['enabled'])
        self.assertEqual(result['cycle_optimization']['fallback'],'cycle search budget exceeded')

    def test_native_exported_fanout_alias_input_and_constants(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'ports.v'
            source.write_text('''module ports(input a,output q,alias_q,r,pass,zero,one);
                arrows_toggle t(a,q); arrows_toggle u(q,r);
                assign alias_q=q; assign pass=a; assign zero=0; assign one=1;
                endmodule''')
            result=arrowshdl.compile(source,top='ports',out=root/'out.json',timeout=60)
            fixture=add_fixture(result.cells,result.metadata)
            ports=result.ports['outputs']
            keys=('q','alias_q','r','pass','zero','one')
            report=arrowshdl.simulate(fixture,dict(ticks=400,
                inputs=[dict(at=result.ports['inputs']['a'][0]['fixture'],values=[0]*100+[1]*200+[0]*100)],
                expect=[],observe=[ports[k][0]['fixture'] for k in keys]),optimize_cycles=False)
            traces=[row['values'] for row in report['observations']]
            self.assertEqual(set(traces[0][200:250]),{0,1})
            self.assertEqual(set(traces[1][200:250]),{0,1})
            self.assertEqual(set(traces[2][200:250]),{0,1})
            self.assertEqual([traces[3][t] for t in (90,250,390)],[0,1,0])
            self.assertEqual(traces[4],[0]*400)
            self.assertEqual(traces[5][-100:],[1]*100)

    def test_native_toggle_latch_random_and_atomic_timers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'native.v'
            source.write_text('''module native(input a,b, output q,s,r0,r1,edge_y,rise_y,timer_y,det_y,pulse);
                arrows_toggle t(a,q); arrows_set l({a,b},s);
                arrows_random random0(a,r0); arrows_random random1(a,r1);
                arrows_edge edge0(a,edge_y); arrows_rise rise0(a,rise_y);
                arrows_timer #(.TICKS(4)) timer0(a,timer_y);
                arrows_detector detector0(a,det_y); arrows_impulse pulse0(pulse);
                endmodule''',encoding='utf-8')
            result = arrowshdl.compile(source,top='native',out=root/'out.json',timeout=60)
            self.assertTrue(result.artifacts['output'].is_file())
            labels = result.metadata['gate_labels']
            points = {n['op']:tuple(n['at']) for n in labels if n['native']}
            randoms = [n['at'] for n in labels if n['op']=='RANDOM']
            self.assertEqual(len(randoms),2)
            fixture = add_fixture(result.cells,result.metadata)
            count = 800
            a = [0]*200+[1]*400+[0]*200
            b = [0]*200+[1]*200+[0]*400
            timer=points['TIMER'];detector=points['DETECTOR']
            observe = [list(points[op]) for op in ('TOGGLE','SET','RISE','EDGE','IMPULSE')]+randoms+[
                list(timer),[timer[0]-4,timer[1]],list(detector),[detector[0],detector[1]-1]]
            scenario = dict(ticks=count,seed=123456789,
                inputs=[dict(at=result.ports['inputs'][name][0]['fixture'],values=a if name=='a' else b) for name in ('a','b')],
                expect=[],observe=observe)
            report = arrowshdl.simulate(fixture,scenario,optimize_cycles=False,timeout=60)
            traces = [row['values'] for row in report['observations']]
            self.assertTrue(all(x!=y for x,y in zip(traces[0][350:390],traces[0][351:391])))
            self.assertEqual([traces[1][t] for t in (180,380,580,780)],[0,1,0,0])
            self.assertEqual(sum(traces[2]),1)
            self.assertEqual(sum(traces[3]),2)
            self.assertEqual(traces[4],[1]+[0]*(count-1))
            self.assertEqual(set(traces[5][350:550]),{0,1})
            self.assertNotEqual(traces[5],traces[6])
            self.assertEqual(traces[7][4:],traces[8][:-4])
            self.assertEqual(traces[9][1:],traces[10][:-1])
            again = arrowshdl.simulate(fixture,scenario,optimize_cycles=False,timeout=60)
            self.assertEqual(report['observations'],again['observations'])

    def test_scenario_extensions_reject_invalid_coordinates(self):
        cells={(0,0):arrowshdl.Cell(24,1)}
        for extension in ({'controls':[dict(at=0,values=[1])]},
                          {'assert':[dict(at=[9,9],values=[1])]},
                          {'probes':[[0,0]]}):
            with self.assertRaises(arrowshdl.MapError):
                arrowshdl.simulate(cells,dict(ticks=1,inputs=[],expect=[],**extension))

    def test_memory_and_random_are_never_shared_by_boolean_optimizer(self):
        graph = dict(inputs={},outputs={},nodes=[dict(id=str(i),op=op,inputs=['x'],output=str(i))
                    for i,op in enumerate(('RANDOM','RANDOM','TOGGLE','TOGGLE'))])
        optimized,changes = merge_duplicate_logic(graph)
        self.assertEqual(len(optimized['nodes']),4)
        self.assertFalse(changes)

    def test_whole_build_timeout_is_enforced_and_invalid_budget_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'logic.v'
            source.write_text('module logic_unit(input a,b,output y); assign y=a&b; endmodule')
            started=time.monotonic()
            with self.assertRaisesRegex(arrowshdl.MapError,'Overall timeout'):
                arrowshdl.compile(source,top='logic_unit',out=root/'out.json',timeout=0.01)
            self.assertLess(time.monotonic()-started,5)
            for budget in (0,-1,float('nan')):
                with self.assertRaises(arrowshdl.MapError):
                    arrowshdl.build(root/'missing.toml',out=root/'out.json',timeout=budget)


if __name__=='__main__':unittest.main()
