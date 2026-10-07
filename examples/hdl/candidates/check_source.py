"""Check proposed HDL sources and prove their combinational specifications.

This checks the HDL front end only. Physical arrow maps are built after selection.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from mapdata import write_json
from verilog_frontend import find_yosys,synthesize


ALU_SPEC="""
module spec_check_alu8(input [7:0] a,b,input [1:0] op,output ok);
    wire [7:0] result;
    wire carry_borrow,zero;
    alu8 dut(a,b,op,result,carry_borrow,zero);
    wire [8:0] added = {1'b0,a}+{1'b0,b};
    wire [7:0] expected = op[1] ? (op[0] ? (a^b) : (a&b)) : (op[0] ? (a-b) : (a+b));
    wire expected_flag = op[1] ? 1'b0 : (op[0] ? (a<b) : added[8]);
    assign ok = (result==expected) && (carry_borrow==expected_flag) && (zero==(expected==8'b0));
endmodule
"""
MUL_SPEC="""
module spec_check_mul4(input [3:0] a,b,output ok);
    wire [7:0] product;
    mul4 dut(a,b,product);
    wire [7:0] expected = a*b;
    assign ok = product==expected;
endmodule
"""


def sort_spec(width=4, top='sort4'):
    text=f"""
module spec_check_{top}(input [{width-1}:0] x0,x1,x2,x3,output ok);
    wire [{width-1}:0] y0,y1,y2,y3;
    {top} dut(x0,x1,x2,x3,y0,y1,y2,y3);
"""
    for i in range(4):
        for side in ('x','y'):
            terms=["{2'b0,("+f'{side}{j}==x{i}'+")}" for j in range(4)]
            text+=f"    wire [2:0] count_{side}{i} = "+'+'.join(terms)+';\n'
    counts=' && '.join(f'(count_x{i}==count_y{i})' for i in range(4))
    return text+'    assign ok = (y0<=y1) && (y1<=y2) && (y2<=y3) && '+counts+';\nendmodule\n'


def check(name):
    source=HERE/name/f'{name}.v'
    code=source.read_text(encoding='utf-8')
    graph,log=synthesize(source,name)
    spec={'alu8':ALU_SPEC,'mul4':MUL_SPEC,'sort4':sort_spec(),
          'sort4x8':sort_spec(8,'sort4x8')}[name]
    proof_top='spec_check_'+name
    script=f'read_verilog design.v; hierarchy -check -top {proof_top}; synth -top {proof_top} -flatten -noabc; check -assert; sat -verify -prove ok 1 -show-inputs -show-outputs'
    with tempfile.TemporaryDirectory(prefix='arrows-hdl-proposal-') as work:
        folder=Path(work)
        (folder/'design.v').write_text(code+'\n'+spec,encoding='utf-8')
        result=subprocess.run([find_yosys(),'-Q','-T','-p',script],cwd=folder,capture_output=True,
                              text=True,encoding='utf-8',errors='replace',timeout=90)
    success=result.returncode==0 and 'SAT proof finished - no model found: SUCCESS!' in result.stdout
    if not success:raise RuntimeError(result.stderr or result.stdout[-4000:])
    out=source.parent/'check'
    out.mkdir(parents=True,exist_ok=True)
    report={'schema':1,'top':name,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'compatible_with_current_frontend':True,'modules':re.findall(r'\bmodule\s+(\w+)',code),
            'yosys':graph['creator'],'input_bits':sum(len(es) for es in graph['inputs'].values()),
            'output_bits':sum(len(es) for es in graph['outputs'].values()),
            'logic_nodes_including_output_buffers':len(graph['nodes']),
            'operations':dict(Counter(n['op'] for n in graph['nodes'])),
            'all_input_combinations':2**sum(len(es) for es in graph['inputs'].values()),
            'specification_proved_for_all_inputs':True,'proof_method':'Yosys SAT, combinational',
            'physical_arrow_map_built':False}
    write_json(out/f'{name}.logic.json',graph)
    write_json(out/f'{name}.check.json',report)
    (out/'specification.v').write_text(spec,encoding='utf-8')
    (out/'sat.txt').write_text(result.stdout,encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('name',choices=('alu8','mul4','sort4','sort4x8'))
    check(parser.parse_args().name)
