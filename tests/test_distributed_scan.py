"""Independent grid semantics and timing for reusable native control logic."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from distributed_scan import parallelize_or_scan
from native_macros import level_timer,timer_latency_bounds,harness,validate_template
from simulation import simulate
from timing import causal_depths,level_arrivals,propagation_bound
from arrowasm import Cell,MapError


def scan_graph():
    def node(name,op,*args):return dict(id=name,output=name,op=op,inputs=list(args))
    return dict(inputs={},outputs={'carry':[dict(index=0,net='driver')]},nodes=[
        node('up','AND','first','north'),node('previous','OR','west','up'),
        node('prefix','OR','value','previous'),node('end','AND','last','prefix'),
        node('row','OR','end','east'),node('driver','BUF','row')])


class DistributedTests(unittest.TestCase):
    def test_parallel_scan_all_requests_and_simultaneous_ties(self):
        before=scan_graph();snapshot=deepcopy(before)
        after=parallelize_or_scan(before,value='value',row='row',north_carry='north',east_row='east',carry_port='carry')
        self.assertEqual(before,snapshot)
        width=height=3
        for mask in range(512):
            for graph in (before,after):
                states=[dict.fromkeys((n['output'] for n in graph['nodes']),0) for _ in range(9)]
                for _ in range(100):
                    next_states=[]
                    for index in range(9):
                        x,y=index%width,index//width
                        nets=dict(states[index],value=(mask>>index)&1,first=int(x==0),last=int(x==width-1),
                            west=states[index-1]['prefix'] if x else 0,
                            east=states[index+1]['row'] if x+1<width else 0,
                            north=states[index-width]['driver'] if y else 0)
                        current={}
                        for node in graph['nodes']:
                            bits=[nets[n] for n in node['inputs']]
                            current[node['output']]=int(all(bits) if node['op']=='AND' else any(bits))
                        next_states.append(current)
                    if next_states==states:break
                    states=next_states
                else:self.fail('Scan did not converge')
                for i,state in enumerate(states):
                    self.assertEqual(state['previous'],int(bool(mask&((1<<i)-1))))
                    self.assertEqual(state['prefix'],int(bool(mask&((1<<(i+1))-1))))
        invalid=deepcopy(before);invalid['nodes'].append(dict(id='extra',output='extra',op='BUF',inputs=['end']))
        with self.assertRaises(MapError):parallelize_or_scan(invalid,value='value',row='row',north_carry='north',east_row='east',carry_port='carry')

    def test_native_counter_timer_all_start_phases_and_retention(self):
        for exponent in (0,1,5,10):
            macro=level_timer(exponent);validate_template(macro)
            limits=timer_latency_bounds(exponent)
            for phase in range(8):
                cells,sources=harness(macro);start=32+phase
                ticks=start+2*limits['max']+8
                trace=[0]*start+[1]*(ticks-start)
                r=simulate(cells,dict(ticks=ticks,inputs=[dict(at=list(sources['start']),values=trace)],expect=[],
                    observe=[list(macro.outputs['done'])]),optimize_cycles=False)
                values=r['observations'][0]['values'];first=values.index(1)
                self.assertGreaterEqual(first-start,limits['min'])
                self.assertLessEqual(first-start,limits['max'])
                self.assertEqual(values[first:],[1]*(ticks-first))

    def test_causal_timing_uses_physical_jumps_delays_and_barriers(self):
        cells={(0,0):Cell(1,1),(1,0):Cell(4,1),(2,0):Cell(10,1),(4,0):Cell(1,1)}
        self.assertEqual(propagation_bound(cells,margin=0),5)
        self.assertEqual(causal_depths(cells,source_times={(0,0):10})[(4,0)],14)
        self.assertEqual(level_arrivals(cells,{(0,0):0})[(4,0)],4)
        cells[(4,0)]=Cell(19,1)
        self.assertNotIn((4,0),level_arrivals(cells,{(0,0):0}))


if __name__=='__main__':unittest.main()
