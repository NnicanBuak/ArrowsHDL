"""Maximum placement search on mixed Boolean cones and composed modules."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from input_buses import verify_exterior
from placement_search import search_placement
from technology_mapping import merge_duplicate_logic,map_native_gates
from test_harness import run_vectors
from verilog_frontend import synthesize


class PlacementSearchTests(unittest.TestCase):
    def test_mixed_operations_are_not_a_mux_template(self):
        graph={'top':'mixed','inputs':{n:[{'index':0,'net':n}] for n in ('a','b','c')},
               'outputs':{'y':[{'index':0,'net':'port:y'}]},'nodes':[
                   {'id':'invert','op':'NOT','inputs':['a'],'output':'n'},
                   {'id':'parity','op':'XOR','inputs':['n','b'],'output':'p'},
                   {'id':'inclusive','op':'OR','inputs':['a','c'],'output':'q'},
                   {'id':'join','op':'AND','inputs':['p','q'],'output':'r'},
                   {'id':'terminal','op':'BUF','inputs':['r'],'output':'port:y'}]}
        before=deepcopy(graph)
        cells,meta=search_placement(dict(graph,_physical_optimize=True),10000)
        self.assertEqual(graph,before)
        self.assertGreater(meta['placement_search']['valid'],0)
        verify_exterior(cells,meta)
        vectors=[{'inputs':dict(zip(('a','b','c'),bits)),
                  'expect':{'y':((1-bits[0])^bits[1])&(bits[0]|bits[2])}}
                 for bits in product(range(2),repeat=3)]
        with tempfile.TemporaryDirectory() as d:
            _,report=run_vectors(cells,meta,vectors+list(reversed(vectors)),Path(d),'mixed',compressed=True)
            self.assertTrue(report['passed'],report['failures'])

    def test_connected_modules_compare_flat_and_hierarchical_placement(self):
        source='''module transform(input a,b,c,output y);
            wire p=(~a)^b; wire q=a|c; assign y=p&q; endmodule
            module composed(input a,b,c,d,output y,p);
            transform first(a,b,c,p); transform second(p,c,d,y); endmodule'''
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);path=folder/'composed.v';path.write_text(source,encoding='utf-8')
            graph,_=synthesize(path,'composed');mapped,_=map_native_gates(graph);mapped,_=merge_duplicate_logic(mapped)
            mapped['_physical_optimize']=True
            cells,meta=search_placement(mapped,10000)
            self.assertEqual(set(meta['placement_search']['composition_modes']),{True,False})
            self.assertIn('module_translation',meta['placement_search']['operations'])
            self.assertIn('module_rotation',meta['placement_search']['operations'])
            verify_exterior(cells,meta)
            vectors=[]
            for a,b,c,d in product(range(2),repeat=4):
                p=((1-a)^b)&(a|c);y=((1-p)^c)&(p|d)
                vectors.append({'inputs':dict(a=a,b=b,c=c,d=d),'expect':dict(p=p,y=y)})
            _,report=run_vectors(cells,meta,vectors+list(reversed(vectors)),folder,'composed',compressed=True)
            self.assertTrue(report['passed'],report['failures'])


if __name__=='__main__':unittest.main()
