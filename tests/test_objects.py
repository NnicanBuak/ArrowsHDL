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
    def test_verilog_2005_include_paths_and_preprocessor_aware_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);inc=root/'include';inc.mkdir()
            (inc/'logic.vh').write_text('assign y=~a;\n')
            source=root/'logic.v'
            source.write_text('''
// A quote in a comment must not hide active HDL: " initial
`ifdef OMITTED
initial begin $display("initial"); end
`endif
module logic_unit(input a, output y);
    localparam [55:0] MESSAGE = "initial";
    `include "logic.vh"
endmodule
''')
            cells,meta=compile_file([source],'logic_unit',root/'out',include_dirs=[inc],
                                    standard='1364-2005')
            report=simulate(add_fixture(cells,meta),make_scenario(meta,[
                dict(inputs={'a':0},expect={'y':1}),dict(inputs={'a':1},expect={'y':0}),
            ]))
            self.assertTrue(report['passed'],report['failures'])

            (inc/'logic.vh').write_text('initial begin end\nassign y=~a;\n')
            with self.assertRaisesRegex(MapError,'Simulation-only constructs'):
                compile_file([source],'logic_unit',root/'bad',include_dirs=[inc],
                             standard='1364-2005')

    def test_systemverilog_validation_ignores_strings_and_inactive_branches(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'logic.sv'
            source.write_text('''
`ifdef OMITTED
initial begin end
`endif
module logic_unit(input logic a, output logic y);
    localparam string MESSAGE = "initial";
    assign y = ~a;
endmodule
''')
            cells,meta=compile_file([source],'logic_unit',root/'out',standard='1800-2023')
            report=simulate(add_fixture(cells,meta),make_scenario(meta,[
                dict(inputs={'a':0},expect={'y':1}),dict(inputs={'a':1},expect={'y':0}),
            ]))
            self.assertTrue(report['passed'],report['failures'])

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
