"""Smoke-test the installed wheel from an unrelated working directory."""
from pathlib import Path
import json
import os
import subprocess
import sys

import arrowshdl
from arrowshdl.mapdata import read_map,save_sha256
from arrowshdl.test_harness import add_fixture,make_scenario

root=Path.cwd()
repo=Path(sys.argv[1])
assert not str(Path(arrowshdl.__file__).resolve()).startswith(str(repo/'src'))
commands=[]


def cli(*args):
    executable=Path(sys.executable).with_name('arrowshdl.exe' if os.name=='nt' else 'arrowshdl')
    completed=subprocess.run([str(executable),*map(str,args)],capture_output=True,text=True,
                             encoding='utf-8',timeout=120)
    assert completed.returncode==0,(args,completed.stdout,completed.stderr)
    commands.append(tuple(map(str,args)))


source=root/'logic.sv'
source.write_text('module logic_unit(input logic a,b,output logic y); always_comb y=a^b; endmodule')
cli('--version')
cli('health')

compiled=root/'compiled.save.txt'
cli('compile',source,'--top','logic_unit','-o',compiled)
scheme=root/'scheme.save.txt'
cli('build',repo/'tests/fixtures/circuits/hdl/half_adder/project.toml','-o',scheme)
scenario_path=root/'identity.scenario.json'
scenario_path.write_text(json.dumps({'ticks':8,'inputs':[{'at':[0,0],'values':[1,0,1,1,0,0,0,0]}],
    'expect':[{'at':[2,0],'values':[0,0,1,0,1,1,0,0]}]}),encoding='utf-8')
cli('test',repo/'tests/fixtures/codec/identity.save.txt',scenario_path,'-o',root/'test.report.json')

obj=root/'logic.object.json'
cli('compile','-c',source,'--top','logic_unit','-o',obj)
linked=root/'linked.save.txt'
cli('link',obj,'--top','logic_unit','-o',linked)
decoded=root/'decoded.json'
roundtrip=root/'roundtrip.save.txt'
cli('decode',compiled,'-o',decoded)
cli('encode',decoded,'-o',roundtrip)
assert read_map(roundtrip)==read_map(compiled)
cli('graph',roundtrip,'-o',root/'graph.json')
cli('preview',roundtrip,'-o',root/'preview.png')
assert (root/'preview.png').stat().st_size>100

result=arrowshdl.compile(source,top='logic_unit',out=root/'api.save.txt')
vectors=[dict(inputs=dict(a=a,b=b),expect=dict(y=a^b)) for a,b in ((0,0),(1,0),(1,1),(0,1))]
scenario=make_scenario(result.metadata,vectors,compressed=True)
fixture=add_fixture(read_map(result.artifacts['output']),result.metadata)
assert arrowshdl.simulate(fixture,scenario,optimize_cycles=False)['passed']

native=root/'native.v'
native.write_text('module native(input a,output q,r); arrows_toggle t(a,q); arrows_random n(a,r); endmodule')
native_result=arrowshdl.compile(native,top='native',out=root/'native.save.txt')
arrowshdl.simulate(add_fixture(native_result.cells,native_result.metadata),dict(ticks=20,
    inputs=[dict(at=native_result.ports['inputs']['a'][0]['fixture'],values=[1]*20)],expect=[],
    observe=[native_result.ports['outputs']['q'][0]['fixture']]))

arrowshdl.compile_object(source,top='logic_unit',out=root/'api.object.json')
api_linked=arrowshdl.link([root/'api.object.json'],top='logic_unit',out=root/'api-linked.save.txt')
assert api_linked.cells==result.cells
api_built=arrowshdl.build(repo/'tests/fixtures/circuits/hdl/half_adder/project.toml',
                          out=root/'api-built.save.txt')
assert api_built.cells

assert save_sha256(compiled)
print('PASS: clean wheel, external cwd, minimal PATH, public commands and in-memory test fixtures')
