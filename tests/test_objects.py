"""Standard preprocessing and independently compiled, checked module interfaces."""
from pathlib import Path
import tempfile
import unittest

from arrowshdl.arrowasm import MapError
from arrowshdl.objects import compile_object,link_objects
from arrowshdl.verilog_compile import emit_build,compile_file
from arrowshdl.test_harness import add_fixture,make_scenario
from arrowshdl.simulation import simulate


class ObjectTests(unittest.TestCase):
    def test_separate_objects_link_and_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            top=root/'top.v';child=root/'child.v'
            top.write_text('module child(input a,b, output y); endmodule\nmodule top(input a,b,output y); child u(a,b,y); endmodule')
            child.write_text('module child(input a,b,output y); assign y=a&b; endmodule')
            a,b=root/'top.aho.json',root/'child.aho.json'
            compile_object([top],'top',a,blackbox_modules=['child'])
            compile_object([child],'child',b)
            graph,log,standard=link_objects([a,b],'top')
            cells,meta=emit_build(graph,[],'top',root/'build',log,standard=standard)
            vectors=[dict(inputs=dict(a=i,b=j),expect=dict(y=i*j)) for i,j in ((0,0),(0,1),(1,1),(1,0))]
            report=simulate(add_fixture(cells,meta),make_scenario(meta,vectors))
            self.assertTrue(report['passed'],report['failures'])
            child.write_text('module child(input [1:0] a,input b,output y); assign y=a[0]&b; endmodule')
            compile_object([child],'child',b)
            with self.assertRaises(MapError):link_objects([a,b],'top')

    def test_sv_2023_macros_include_parameter_and_comb_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inc=root/'inc';inc.mkdir()
            (inc/'op.svh').write_text('`define OP(a,b) ((a) ^ (b))\n')
            source=root/'logic.sv'
            source.write_text('`include "op.svh"\nmodule logic_unit #(parameter N=2)(input logic [N-1:0] a,b,output logic [N-1:0] y); always_comb y=`OP(a,b); endmodule')
            cells,meta=compile_file([source],'logic_unit',root/'out',include_dirs=[inc],parameters={'N':3},standard='1800-2023')
            self.assertEqual(len(meta['inputs']['a']),3)
            vectors=[dict(inputs=dict(a=i,b=7-i),expect=dict(y=i^(7-i))) for i in range(8)]
            report=simulate(add_fixture(cells,meta),make_scenario(meta,vectors))
            self.assertTrue(report['passed'],report['failures'])


if __name__=='__main__':unittest.main()
