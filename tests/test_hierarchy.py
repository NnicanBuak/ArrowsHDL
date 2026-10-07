"""Flattened hierarchy annotations are provenance, never electrical cells."""
from itertools import product
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from arrowasm import MapError
from test_harness import run_vectors
from verilog_compile import compile_file
from verilog_frontend import normalize,synthesize


class HierarchyTests(unittest.TestCase):
    def test_two_child_modules_synthesize_and_simulate(self):
        code='''
module pair_and(input [1:0] a,b,output [1:0] y); assign y=a&b; endmodule
module pair_xor(input [1:0] a,b,output [1:0] y); assign y=a^b; endmodule
module composed(input [1:0] a,b,output [1:0] p,q);
    pair_and u_and(a,b,p);
    pair_xor u_xor(a,b,q);
endmodule
'''
        with tempfile.TemporaryDirectory() as work:
            folder=Path(work);source=folder/'composed.v'
            source.write_text(code,encoding='utf-8')
            graph,_=synthesize(source,'composed')
            self.assertEqual({s['module'] for s in graph['scopes']},{'pair_and','pair_xor'})
            self.assertEqual({s['name'] for s in graph['scopes']},{'u_and','u_xor'})
            self.assertEqual(len(graph['nodes']),8)
            cells,meta=compile_file(source,'composed',folder)
            vectors=[{'inputs':{'a':a,'b':b},'expect':{'p':a&b,'q':a^b}} for a,b in product(range(4),repeat=2)]
            _,report=run_vectors(cells,meta,vectors+list(reversed(vectors)),folder,'composed',compressed=True)
            self.assertTrue(report['passed'],report['failures'])
            self.assertEqual(report['checked_samples'],128)

    def test_scopeinfo_with_electrical_connections_is_rejected(self):
        raw={'modules':{'broken':{'ports':{'a':{'direction':'input','bits':[2]},'y':{'direction':'output','bits':[3]}},
             'cells':{'metadata':{'type':'$scopeinfo','attributes':{},'connections':{'Y':[3]},'port_directions':{'Y':'output'}}}}}}
        with self.assertRaises(MapError):normalize(raw,'broken')


if __name__=='__main__':
    unittest.main()
