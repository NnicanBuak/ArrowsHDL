"""Compact physical muxes: equivalent maps, ordered banks and direct jumps."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from arrow_layout import edges,place
from input_buses import verify_exterior
from mapdata import read_map
from test_harness import run_vectors
from verilog_compile import compile_file
from verilog_frontend import synthesize


class DenseMuxTests(unittest.TestCase):
    def test_saved_maps_are_compact_and_exhaustively_equivalent(self):
        with tempfile.TemporaryDirectory() as directory:
            for count,limit in ((2,9),(4,27),(8,68)):
                folder=Path(directory)/str(count)
                cells,meta=compile_file(ROOT/f'examples/hdl/multiplexer/mux{count}/mux{count}.v',
                                       f'mux{count}',folder,input_buses=['data','sel'],input_bus_gap='auto')
                self.assertEqual(meta['layout'],'compact-dense-mux-v1')
                self.assertLessEqual(len(cells),limit)
                self.assertTrue(meta['fused_output'])
                self.assertEqual(meta['logic_core']['gates'],4*(count-1))
                self.assertEqual(cells,read_map(folder/f'mux{count}.save.txt'))
                verify_exterior(cells,meta)
                output=tuple(meta['outputs']['y'][0]['contact'])
                self.assertEqual(next(g['op'] for g in meta['gate_labels'] if tuple(g['at'])==output),'OR')
                vectors=[{'inputs':{'data':data,'sel':sel},'expect':{'y':(data>>sel)&1}}
                         for data in range(1<<count) for sel in range(count)]
                vectors+=list(reversed(vectors))
                _,report=run_vectors(cells,meta,vectors,folder,f'mux{count}',compressed=True)
                self.assertTrue(report['passed'],report['failures'])

    def test_jump_enters_and_directly_and_or_can_be_a_jump(self):
        graph,_=synthesize(ROOT/'examples/hdl/multiplexer/mux8/mux8.v','mux8')
        before=deepcopy(graph)
        cells,meta=place(graph,input_buses=['data','sel'],input_bus_gap='auto')
        self.assertEqual(graph,before)
        gates={tuple(g['at']):g['op'] for g in meta['gate_labels']}
        jumps=[(p,q) for p,targets in edges(cells).items() for q in targets
               if cells[p].type==10 and gates.get(q)=='AND']
        self.assertTrue(jumps)
        self.assertTrue(any(gates.get(((p[0]+q[0])//2,(p[1]+q[1])//2))=='NOT' for p,q in jumps))
        self.assertTrue(any(cells[p].type==10 and op=='OR' for p,op in gates.items()))
        data_bus=next(b for b in meta['input_buses'] if b['ports']==['data'])
        self.assertIsNone(data_bus['pitch'])
        self.assertEqual(set(data_bus['pitches']),{1,2})
        self.assertLess(meta['stage_columns'][-1]-meta['stage_columns'][-2],
                        meta['stage_columns'][1]-meta['stage_columns'][0])

    def test_recognition_works_with_unrelated_module_and_port_names(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);source=folder/'picker.v'
            source.write_text('module picker(input [7:0] payload,input [2:0] address,output result); assign result=payload[address]; endmodule',encoding='utf-8')
            cells,meta=compile_file(source,'picker',folder,input_buses=['payload','address'],input_bus_gap='auto')
            self.assertEqual(meta['layout'],'compact-dense-mux-v1')
            self.assertLessEqual(len(cells),68)
            vectors=[{'inputs':{'payload':v,'address':s},'expect':{'result':(v>>s)&1}}
                     for v in range(256) for s in range(8)]
            _,report=run_vectors(cells,meta,vectors,folder,'picker',compressed=True)
            self.assertTrue(report['passed'],report['failures'])


if __name__=='__main__':unittest.main()
