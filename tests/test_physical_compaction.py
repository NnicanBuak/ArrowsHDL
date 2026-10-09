"""Common physical optimizer: unrelated Boolean graphs, exact saved maps."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from compact_layout import arrange_buses,router_manifest,place_packed
from input_buses import configure,apply_placement,verify_exterior
from mapdata import read_map,write_map
from output_layout import route_with_outputs
from physical_compaction import compact_manifest
from test_harness import run_vectors


def make_graph(operations,results):
    nodes=[{'id':f'operator:{i}','op':op,'inputs':args,'output':net}
           for i,(op,args,net) in enumerate(operations)]
    for name,net in results.items():
        nodes.append({'id':'terminal:'+name,'op':'BUF','inputs':[net],'output':'port:'+name})
    return {'top':'circuit','inputs':{n:[{'index':0,'net':n}] for n in ('a','b','c')},
            'outputs':{n:[{'index':0,'net':'port:'+n}] for n in results},'nodes':nodes}


def vectors(graph):
    result=[]
    for bits in product(range(2),repeat=3):
        value=dict(zip(('a','b','c'),bits));value.update(const0=0,const1=1)
        for node in graph['nodes']:
            arguments=[value[n] for n in node['inputs']];op=node['op']
            value[node['output']]={'NOT':lambda:1-arguments[0],'AND':lambda:int(all(arguments)),
                                   'OR':lambda:int(any(arguments)),'XOR':lambda:sum(arguments)%2,
                                   'MAJ':lambda:int(sum(arguments)>=2),'BUF':lambda:arguments[0]}[op]()
        result.append({'inputs':dict(zip(('a','b','c'),bits)),
                       'expect':{n:value[es[0]['net']] for n,es in graph['outputs'].items()}})
    return result+list(reversed(result))


class PhysicalCompactionTests(unittest.TestCase):
    def test_general_packer_matches_adder_size_without_adder_backend(self):
        import random
        from technology_mapping import map_native_gates,merge_duplicate_logic
        from verilog_frontend import synthesize
        graph,_=synthesize(ROOT/'examples/hdl/adder8/adder8.v','adder8')
        mapped,_=map_native_gates(graph);mapped,_=merge_duplicate_logic(mapped)
        cells,meta=place_packed(dict(mapped,_physical_optimize=True),10000)
        self.assertEqual(meta['layout'],'compact-connected-modules-v1')
        self.assertLessEqual(len(cells),58)
        self.assertLessEqual(meta['bounds']['area'],72)
        verify_exterior(cells,meta)
        rng=random.Random(1501)
        values=[(a,b,c) for a,b in ((0,0),(255,0),(255,255),(127,1),(85,170)) for c in (0,1)]
        values += [(rng.randrange(256),rng.randrange(256),rng.randrange(2)) for _ in range(256)]
        cases=[{'inputs':{'a':a,'b':b,'cin':c},'expect':{'sum':(a+b+c)&255,'cout':(a+b+c)>>8}} for a,b,c in values]
        with tempfile.TemporaryDirectory() as directory:
            _,report=run_vectors(cells,meta,cases,Path(directory),'general',compressed=True)
            self.assertTrue(report['passed'],report['failures'])

    def optimize(self,graph,gap=None):
        original=deepcopy(graph)
        if gap is not None:graph=dict(graph,_input_bus_config=configure(graph,['a,b,c'],gap))
        placement=arrange_buses(graph,4,'sides',0,logic_first=True)
        placement=apply_placement(graph,placement)
        cells,router=route_with_outputs(graph,placement,10000)
        meta=router_manifest(graph,router,cells,'compact-test')
        before=deepcopy(meta);saved=dict(cells)
        compact,after=compact_manifest(cells,meta,graph)
        self.assertEqual(cells,saved);self.assertEqual(meta,before)
        self.assertEqual({n['id'] for n in original['nodes']},{g['id'] for g in after['gate_labels']})
        self.assertLessEqual(len(compact),len(cells))
        self.assertLessEqual(after['bounds']['area'],before['bounds']['area'])
        self.assertEqual(after['logic_core']['gates'],before['logic_core']['gates'])
        self.assertTrue(after['physical_compaction']['exact_edges_verified'])
        verify_exterior(compact,after)
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            write_map(folder,'circuit',compact)
            self.assertEqual(compact,read_map(folder/'circuit.save.txt'))
            for tag,cs,ms in (('before',cells,meta),('after',compact,after)):
                _,report=run_vectors(cs,ms,vectors(original),folder/tag,'circuit',compressed=True)
                self.assertTrue(report['passed'],report['failures'])
            repeat,repeated=compact_manifest(compact,after,graph)
            self.assertEqual(compact,repeat)
        return compact,after

    def test_parity_decoder_threshold_fanout_and_multiple_outputs(self):
        cases=[
            ([('XOR',['a','b'],'p'),('XOR',['p','c'],'q')],{'y':'q'}),
            ([('NOT',['a'],'n'),('AND',['n','b'],'d'),('OR',['d','c'],'r')],{'y':'r'}),
            ([('XOR',['a','b','c'],'p'),('MAJ',['a','b','c'],'m')],{'odd':'p','threshold':'m'}),
            ([('AND',['a','b'],'p'),('OR',['a','c'],'q'),('XOR',['p','q'],'r')],{'first':'p','last':'r'}),
            ([('OR',['a','const1'],'p'),('AND',['b','const0'],'q')],{'one':'p','zero':'q'}),
        ]
        reductions=[]
        for operations,outputs in cases:
            with self.subTest(outputs=outputs):
                _,meta=self.optimize(make_graph(operations,outputs))
                reductions.append(meta['physical_compaction']['removed_relays'])
        self.assertGreater(sum(reductions),0)

    def test_manual_bus_spacing_and_auto_order_survive_compaction(self):
        graph=make_graph([('NOT',['a'],'n'),('XOR',['n','b'],'p'),('OR',['p','c'],'q')],{'y':'q'})
        for gap in (0,2,'auto'):
            with self.subTest(gap=gap):
                _,meta=self.optimize(graph,gap)
                fixtures=[meta['inputs'][n][0]['fixture'] for n in ('a','b','c')]
                self.assertEqual(len({p[0] for p in fixtures}),1)
                steps=[b[1]-a[1] for a,b in zip(fixtures,fixtures[1:])]
                self.assertTrue(all(s>0 for s in steps))
                if gap!='auto':self.assertEqual(steps,[gap+1,gap+1])


if __name__=='__main__':unittest.main()
