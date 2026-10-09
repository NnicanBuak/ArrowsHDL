"""Prove all binary values; test a serialized arrow map against decimal Python."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / 'src'))
from mapdata import map_hash, read_map, write_json
from test_harness import run_vectors, run_vector_batches
from verilog_compile import compile_file
from verilog_frontend import find_yosys


def decimal_digits(value):
    return sum(int(digit) << (4*index) for index, digit in enumerate(reversed(str(value))))


def prove(width):
    digits = 2 if width == 4 else 3
    # Explicit four-bit wires avoid unsized arithmetic concatenation operands.
    wires = '\n'.join(f'wire [3:0] digit{d} = (binary / {10**d}) % 10;' for d in range(digits))
    expected = ','.join(f'digit{d}' for d in reversed(range(digits)))
    spec = f'''module spec(input [{width-1}:0] binary,output ok);
    wire [{digits*4-1}:0] bcd;
    bcd{width} dut(binary,bcd);
    {wires}
    assign ok = bcd == {{{expected}}};
endmodule'''
    script = ('read_verilog design.v; hierarchy -check -top spec; '
              'synth -top spec -flatten -noabc; check -assert; '
              'sat -verify -prove ok 1 -show-inputs -show-outputs')
    with tempfile.TemporaryDirectory(prefix='arrows-bcd-proof-') as directory:
        work = Path(directory)
        (work/'design.v').write_text((HERE/'binary_to_bcd.v').read_text(encoding='utf-8')+'\n'+spec, encoding='utf-8')
        result = subprocess.run([find_yosys(),'-Q','-T','-p',script],cwd=work,
                                capture_output=True,text=True,encoding='utf-8',timeout=90)
    passed = result.returncode == 0 and 'SAT proof finished - no model found: SUCCESS!' in result.stdout
    check = HERE/'check';check.mkdir(parents=True,exist_ok=True)
    (check/f'bcd{width}.specification.v').write_text(spec,encoding='utf-8')
    (check/f'bcd{width}.sat.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
    write_json(check/f'bcd{width}.source.report.json',dict(passed=passed,input_combinations=1<<width,
        method='Yosys SAT',source_sha256=hashlib.sha256((HERE/'binary_to_bcd.v').read_bytes()).hexdigest()))
    if not passed:raise RuntimeError(result.stderr or result.stdout[-4000:])
    print(f'BCD{width}: all {1<<width} values proved',flush=True)


def run(width,source_only=False,reuse=False):
    prove(width)
    if source_only:return
    top=f'bcd{width}';folder=HERE/'build'/top;source=HERE/'binary_to_bcd.v'
    if reuse:
        meta=json.loads((folder/f'{top}.build.json').read_text(encoding='utf-8'))
        cells=read_map(folder/f'{top}.save.txt')
        assert meta['source_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
        assert meta['map_hash']==map_hash(cells)
        assert read_map(folder/f'{top}.map.json')==cells
    else:
        cells,meta=compile_file(source,top,folder,input_buses=['binary'],input_bus_gap='auto')
    print(f'{top}: compiled {len(cells)} cells; hold={meta["settle_ticks"]}',flush=True)
    def vector(value):return dict(inputs=dict(binary=value),expect=dict(bcd=decimal_digits(value)))
    samples=[vector(v) for v in ((0,9,10,15) if width==4 else (0,9,10,99,100,225,255))]
    _,small=run_vectors(cells,meta,samples,folder,top,compressed=True)
    if not small['passed']:raise RuntimeError(small['failures'])
    values=list(range(1<<width))
    report=run_vector_batches(cells,meta,(vector(v) for v in values+list(reversed(values))),folder,top)
    write_json(folder/f'{top}.exhaustive.report.json',report)
    if not report['passed']:raise RuntimeError(report['failures'])
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('--width',type=int,choices=(4,8),default=4)
    parser.add_argument('--source-only',action='store_true')
    parser.add_argument('--reuse',action='store_true')
    args=parser.parse_args();run(args.width,args.source_only,args.reuse)
