"""Eight-operation modular ALU: all 2048 inputs on exported physical maps."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
from mapdata import read_map, map_hash, write_json
from map_preview import render
from test_harness import run_vectors, run_vector_batches
from verilog_compile import compile_file
from verilog_frontend import find_yosys


SPEC = '''module spec(input [3:0] a,b,input [2:0] op,output ok);
    wire [3:0] result;
    wire carry_borrow,zero;
    alu4 dut(a,b,op,result,carry_borrow,zero);
    wire [4:0] added = {1'b0,a}+{1'b0,b};
    wire [3:0] expected = op==0 ? a+b : op==1 ? a-b :
        op==2 ? a&b : op==3 ? a^b : op==4 ? a|b :
        op==5 ? a<<1 : op==6 ? a>>1 : ~a;
    wire flag = op==0 ? added[4] : op==1 ? a<b : 1'b0;
    assign ok = (result==expected) && (carry_borrow==flag) &&
                (zero==(expected==0));
endmodule'''


def prove_source():
    script = ('read_verilog design.v; hierarchy -check -top spec; '
              'synth -top spec -flatten -noabc; check -assert; '
              'sat -verify -prove ok 1 -show-inputs -show-outputs')
    with tempfile.TemporaryDirectory(prefix='arrows-alu-proof-') as directory:
        work = Path(directory)
        (work/'design.v').write_text((HERE/'alu4.v').read_text(encoding='utf-8')+'\n'+SPEC, encoding='utf-8')
        proof = subprocess.run([find_yosys(),'-Q','-T','-p',script], cwd=work,
                               capture_output=True, text=True, encoding='utf-8', timeout=90)
    passed = proof.returncode==0 and 'SAT proof finished - no model found: SUCCESS!' in proof.stdout
    folder = HERE/'check';folder.mkdir(parents=True,exist_ok=True)
    (folder/'specification.v').write_text(SPEC,encoding='utf-8')
    (folder/'sat.txt').write_text(proof.stdout+proof.stderr,encoding='utf-8')
    write_json(folder/'alu4.source.report.json', {'passed':passed,'all_input_combinations':2048,
               'method':'Yosys SAT','source_sha256':hashlib.sha256((HERE/'alu4.v').read_bytes()).hexdigest()})
    if not passed:raise RuntimeError(proof.stderr or proof.stdout[-4000:])
    print('ALU source: all 2048 input combinations proved',flush=True)


def vector(a,b,op):
    values=(a+b,a-b,a&b,a^b,a|b,a<<1,a>>1,~a)
    result=values[op]&15
    flag=int(a+b>15) if op==0 else int(a<b) if op==1 else 0
    return {'inputs':dict(a=a,b=b,op=op),'expect':dict(result=result,carry_borrow=flag,zero=int(result==0))}


def vectors():
    for op in range(8):
        for a in range(16):
            for b in range(16):yield vector(a,b,op)
    # All opcode transitions at carry, borrow and alternating-bit backgrounds.
    for a,b in ((0,0),(15,1),(0,15),(7,8),(5,10)):
        for old in range(8):
            for new in range(8):
                yield vector(a,b,old);yield vector(a,b,new);yield vector(a,b,old)
    rng=random.Random(808)
    for _ in range(4096):yield vector(rng.randrange(16),rng.randrange(16),rng.randrange(8))


def run(reuse=False,source_only=False):
    prove_source()
    if source_only:return
    source=HERE/'alu4.v';folder=HERE/'build'
    if reuse:
        meta=json.loads((folder/'alu4.build.json').read_text(encoding='utf-8'))
        cells=read_map(folder/'alu4.save.txt')
        assert meta['source_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
        assert meta['map_hash']==map_hash(cells)
        assert read_map(folder/'alu4.map.json')==cells
    else:
        cells,meta=compile_file(source,'alu4',folder,input_buses=['a','b','op'],input_bus_gap='auto')
    print(f"ALU compiled: {len(cells)} cells; core={meta['logic_core']}; hold={meta['settle_ticks']}",flush=True)
    examples=[vector(a,b,op) for op,(a,b) in enumerate(((15,1),(3,5),(12,10),(12,10),(12,10),(9,0),(9,0),(5,0)))]
    _,small=run_vectors(cells,meta,examples,folder,'alu4',compressed=True)
    if not small['passed']:raise RuntimeError(small['failures'])
    report=run_vector_batches(cells,meta,vectors(),folder,'alu4',
                             progress=lambda r:print(f"ALU checked: {r['vectors']} vectors; failures={r['failure_count']}",flush=True))
    report['unique_input_combinations']=2048
    report['opcode_transition_vectors']=960
    report['random_vectors']=4096
    write_json(folder/'alu4.exhaustive.report.json',report)
    render(cells,meta,folder/'alu4.preview.png')
    render(read_map(folder/'alu4.test.save.txt'),meta,folder/'alu4.test.preview.png')
    if not report['passed']:raise RuntimeError(report['failures'])
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('--reuse',action='store_true')
    parser.add_argument('--source-only',action='store_true')
    args=parser.parse_args();run(args.reuse,args.source_only)
