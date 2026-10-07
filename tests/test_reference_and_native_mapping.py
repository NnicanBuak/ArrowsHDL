"""The supplied image, phased register transfers, and safe native technology mapping."""
from copy import deepcopy
from itertools import product
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'examples/reference_adder8'))
from arrowasm import Cell,MapError
from mapdata import read_map
from simulation import simulate
from test_harness import add_fixture,run_vectors
from verilog_compile import compile_file
from technology_mapping import map_native_gates
from protocol import manifest,scenario
from recognize import recognize
from testbench import core


class ReferenceTests(unittest.TestCase):
    def test_image_reconstruction_and_register_transitions(self):
        path=ROOT/'examples/reference_adder8/build/reference.map.json'
        expected=read_map(path)
        cells,_=recognize()
        self.assertEqual(cells,expected)
        self.assertEqual(len(cells),411)
        meta=manifest(cells)
        original=dict(cells)
        fixture=add_fixture(cells,meta)
        self.assertEqual(cells,original)
        self.assertEqual(len(fixture)-len(cells),30)
        cases=[{'a':a,'b':b} for a,b in ((0,0),(255,255),(255,1),(0,0),(127,1),(85,170))]
        cases += [{'a':1<<i,'b':0} for i in range(8)]
        cases += [{'a':0,'b':1<<i} for i in range(8)]
        r=simulate(fixture,scenario(meta,cases),optimize_cycles=False)
        self.assertTrue(r['passed'],r['failures'])
        self.assertEqual(r['checked_samples'],len(cases)*9)
        wrong=scenario(meta,[{'a':0,'b':0}])
        wrong['expect'][0]['values'][-1]=1
        self.assertFalse(simulate(fixture,wrong,optimize_cycles=False)['passed'])

    def test_reference_core_is_an_exact_subset(self):
        cells=read_map(ROOT/'examples/reference_adder8/build/reference.map.json')
        part,meta=core(cells)
        self.assertEqual(len(part),56)
        self.assertTrue(all(cells[p]==c for p,c in part.items()))
        vectors=[{'inputs':{'a':a,'b':b},'expect':{'sum':(a+b)&255,'cout':(a+b)>>8}} for a,b in ((255,255),(1,255),(0,0),(128,128),(85,170))]
        with tempfile.TemporaryDirectory() as d:
            _,r=run_vectors(part,meta,vectors,Path(d),'core',compressed=True)
            self.assertTrue(r['passed'],r['failures'])

    def test_variable_frames_match_full_tick_simulation(self):
        cells={(0,0):Cell(22,1),(1,0):Cell(1,1),(2,0):Cell(23,0)}
        packed={'ticks':10,'frame_ticks':[1,4,1,4],'inputs':[{'at':[0,0],'values':[1,1,0,0]}],
                'expect':[{'at':[2,0],'values':[None,1,None,0]}]}
        full={'ticks':10,'inputs':[{'at':[0,0],'values':[1]*5+[0]*5}],
              'expect':[{'at':[2,0],'values':[None]*4+[1]+[None]*4+[0]}]}
        a,b=simulate(cells,packed),simulate(cells,full)
        self.assertTrue(a['passed'] and b['passed'])
        self.assertEqual(a['checked_samples'],b['checked_samples'])
        self.assertEqual(a['outputs'][0]['values'],[b['outputs'][0]['values'][i] for i in (0,4,5,9)])
        for durations in ([],[1,0,5,4],[1,1,1,1],[1,4,1,5]):
            with self.subTest(durations=durations),self.assertRaises(MapError):
                simulate(cells,dict(packed,frame_ticks=durations))
        with self.assertRaises(MapError):simulate(cells,dict(packed,hold_ticks=1))

    def test_three_bit_adder_is_not_a_fixed_eight_bit_template(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);source=folder/'three.v'
            source.write_text('module three(input [2:0] a,b,input cin,output [2:0] sum,output cout); wire [3:0] c; assign c[0]=cin; assign cout=c[3]; genvar i; generate for(i=0;i<3;i=i+1) begin wire p; assign p=a[i]^b[i]; assign sum[i]=p^c[i]; assign c[i+1]=(a[i]&b[i])|(p&c[i]); end endgenerate endmodule',encoding='utf-8')
            cells,meta=compile_file(source,'three',folder)
            self.assertEqual(meta['adder_bits'],3)
            self.assertEqual(len(meta['technology_mapping']),3)
            self.assertLess(len(cells),30)
            vectors=[{'inputs':{'a':a,'b':b,'cin':ci},'expect':{'sum':(a+b+ci)&7,'cout':(a+b+ci)>>3}} for a,b,ci in product(range(8),range(8),range(2))]
            _,r=run_vectors(cells,meta,vectors,folder,'three',compressed=True)
            self.assertTrue(r['passed'],r['failures'])

    def test_observed_propagate_net_cannot_be_removed(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);source=folder/'observe.v'
            source.write_text('module observe(input a,b,c,output sum,cout,p); assign p=a^b; assign sum=p^c; assign cout=(a&b)|(p&c); endmodule',encoding='utf-8')
            cells,meta=compile_file(source,'observe',folder)
            self.assertEqual(meta['technology_mapping'],[])
            vectors=[{'inputs':{'a':a,'b':b,'c':c},'expect':{'sum':(a+b+c)&1,'cout':(a+b+c)>>1,'p':a^b}} for a,b,c in product(range(2),repeat=3)]
            _,r=run_vectors(cells,meta,vectors,folder,'observe',compressed=True)
            self.assertTrue(r['passed'],r['failures'])


if __name__=='__main__':unittest.main()
