"""Core optimization ignores port tails and preserves physical behavior."""
from itertools import product
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from arrowasm import Cell,MapError
from arrow_layout import depth_of,logic_core_metrics,place
from compact_layout import Router,arrange_buses
from mapdata import map_hash
from simulation import simulate
from test_harness import add_fixture,make_scenario


class LogicFirstTests(unittest.TestCase):
    def test_astar_cannot_route_behind_external_ports(self):
        router=Router.__new__(Router)
        router.cells={(0,0):None,(6,0):None}
        router.owners={(0,0):'n',(6,0):'n'}
        router.outs={(0,0):set()}
        router.bounds=(0,0,6,2)
        router.routing_limits=[0,0,6,None]
        router.reserved={(2,0),(4,0)}
        path=router.path({(0,0)},(6,0),4)
        self.assertIsNotNone(path)
        self.assertTrue(all(0<=x<=6 and y>=0 for x,y in path))
        self.assertFalse(router.route_allowed((-1,0)))
        self.assertFalse(router.route_allowed((0,-1)))
        self.assertFalse(router.route_allowed((7,0)))

    def test_io_retry_restores_a_partially_routed_map(self):
        graph={'top':'retry','inputs':{'a':[{'index':i,'net':f'i{i}'} for i in range(2)]},
               'outputs':{'y':[{'index':0,'net':'port:y'}]},'nodes':[
                   {'id':'negate','op':'NOT','inputs':['i0'],'output':'n0'},
                   {'id':'mask','op':'AND','inputs':['n0','i1'],'output':'n1'},
                   {'id':'terminal','op':'BUF','inputs':['n1'],'output':'port:y'}]}
        router=Router(graph,4,1000,arrange_buses(graph,4,'sides',0,logic_first=True))
        original=router.route_phase
        calls=0

        def fail_after_mutation(targets):
            nonlocal calls
            calls+=1
            original(targets)
            if calls==2:
                raise MapError('external route conflict after mutation')

        with patch.object(router,'route_phase',side_effect=fail_after_mutation):
            cells=router.route()
        self.assertTrue(router.io_conflict_fallback)
        self.assertEqual(calls,3)
        meta={'map_hash':map_hash(cells),'inputs':router.inputs,'outputs':router.outputs,
              'settle_ticks':depth_of(cells)+2}
        vectors=[{'inputs':{'a':a},'expect':{'y':int(a==2)}} for a in (0,2,1,3,2,0,3,1)]
        report=simulate(add_fixture(cells,meta),make_scenario(meta,vectors,compressed=True))
        self.assertTrue(report['passed'],report['failures'])

    def test_isolated_sink_is_rejected_without_flooding_the_board(self):
        router=Router.__new__(Router)
        router.cells={(0,0):None,(50,50):None}
        router.owners={(0,0):'n',(50,50):'n'}
        router.outs={(0,0):set()}
        router.bounds=(0,0,100,100)
        router.reserved={(50+dx*distance,50+dy*distance)
                         for dx,dy in ((1,0),(0,1),(-1,0),(0,-1),(1,1),(-1,1),(1,-1),(-1,-1))
                         for distance in ((1,) if dx and dy else (1,2))}
        with patch('compact_layout.heappop',side_effect=AssertionError('isolated sink should not flood A*')):
            self.assertIsNone(router.path({(0,0)},(50,50),3))

    def test_conflicting_nets_do_not_repeat_until_global_budget(self):
        # Two forced jump paths share the only intermediate cell. Rip-up can
        # alternate them forever, but cannot create a legal simultaneous route.
        router=Router.__new__(Router)
        allowed={(0,0),(4,0),(2,-2),(2,2),(2,0)}
        router.cells={p:None for p in allowed if p!=(2,0)}
        router.owners={(0,0):'a',(4,0):'a',(2,-2):'b',(2,2):'b'}
        router.outs={p:set() for p in router.cells}
        router.fixed_cells=set(router.cells)
        router.fixed_outs={p:set() for p in router.cells}
        router.roots={'a':(0,0),'b':(2,-2)}
        router.bounds=(0,-2,4,2)
        router.reserved={(x,y) for x in range(-32,37) for y in range(-34,35)}-allowed
        router.max_cells=100
        router.ripups=0
        original=router.path
        with patch.object(router,'path',side_effect=original) as calls:
            with self.assertRaisesRegex(MapError,'повторно конфликтует'):
                router.route_phase({'a':{(4,0)},'b':{(2,2)}})
            self.assertLess(calls.call_count,80)

    def test_astar_shortest_routes_with_jumps_and_obstacles(self):
        router=Router.__new__(Router)
        router.cells={(0,0):None,(6,0):None}
        router.owners={(0,0):'n',(6,0):'n'}
        router.outs={(0,0):set()}
        router.bounds=(0,-1,6,1)
        router.reserved=set()
        path=router.path({(0,0)},(6,0),1)
        # Every arrow travels at most two cells: three hops are necessary here.
        self.assertEqual(len(path)-1,3)
        router.reserved={(2,0),(4,0)}
        path=router.path({(0,0)},(6,0),1)
        # Three hops would require exactly the blocked horizontal jumps.
        self.assertEqual(len(path)-1,4)
        self.assertFalse(set(path)&router.reserved)
        self.assertEqual((path[0],path[-1]),((0,0),(6,0)))

    def test_long_io_tails_do_not_change_logic_core_or_its_timing(self):
        metrics=[]
        full_depth=[]
        for length in (1,20):
            cells={(x,0):Cell(1,1) for x in range(-length,length+3)}
            cells[(0,0)]=cells[(2,0)]=Cell(15,1)
            gates={(0,0):{'output':'inverted'},(2,0):{'output':'restored'},(length+2,0):{'output':'port:y'}}
            metrics.append(logic_core_metrics(cells,gates,{'port:y'}))
            full_depth.append(depth_of(cells))
            test=dict(cells)
            test[(-length-1,0)]=Cell(22,1)
            test[(length+3,0)]=Cell(23,0)
            hold=depth_of(cells)+2
            report=simulate(test,{'ticks':hold*4,'hold_ticks':hold,
                'inputs':[{'at':[-length-1,0],'values':[0,1,0,1]}],
                'expect':[{'at':[length+3,0],'values':[0,1,0,1]}]})
            self.assertTrue(report['passed'],report['failures'])
        for metric in metrics:
            self.assertEqual(metric['cells'],3)
            self.assertEqual(metric['gates'],2)
            self.assertEqual(metric['ticks'],3)
            self.assertEqual(metric['bounds']['area'],3)
        self.assertGreater(full_depth[1],full_depth[0])
        self.assertGreater(metrics[1]['excluded_io_cells'],metrics[0]['excluded_io_cells'])

    def test_fixed_ports_across_core_candidates_and_nonadder_truth_table(self):
        graph={'top':'logic','inputs':{'a':[{'index':i,'net':f'i{i}'} for i in range(2)]},
               'outputs':{'y':[{'index':0,'net':'port:y'}]},'nodes':[
                   {'id':'negate','op':'NOT','inputs':['i0'],'output':'n0'},
                   {'id':'mask','op':'AND','inputs':['n0','i1'],'output':'n1'},
                   {'id':'parity','op':'XOR','inputs':['n0','n1'],'output':'n2'},
                   {'id':'terminal','op':'BUF','inputs':['n2'],'output':'port:y'}]}
        contacts=[]
        for pitch,seed in product((3,4,5,8),(0,1)):
            vertices,positions,_=arrange_buses(graph,pitch,'sides',seed,logic_first=True)
            contacts.append({v.get('net',v.get('node',{}).get('output')):p for v,p in zip(vertices,positions)
                             if v['kind']=='input' or v.get('node',{}).get('output')=='port:y'})
        self.assertTrue(all(c==contacts[0] for c in contacts))
        cells,meta=place(graph)
        self.assertFalse(meta['optimization']['io_in_objective'])
        self.assertIn(0.5, meta['optimization']['aspect_candidates'])
        self.assertIn(4.0, meta['optimization']['aspect_candidates'])
        self.assertEqual(meta['optimization']['initial_corridor'], 0)
        self.assertEqual(meta['logic_core']['gates'],3)
        vectors=[{'inputs':{'a':a},'expect':{'y':int(a==0)}} for a in range(4)]*3
        report=simulate(add_fixture(cells,meta),make_scenario(meta,vectors,compressed=True))
        self.assertTrue(report['passed'],report['failures'])


if __name__=='__main__':
    unittest.main()
