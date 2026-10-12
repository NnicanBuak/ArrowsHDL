from pathlib import Path
import json,subprocess,sys,os
import arrowshdl
from arrowshdl.mapdata import read_map,save_sha256
from arrowshdl.test_harness import add_fixture,make_scenario

root=Path.cwd()
repo=Path(sys.argv[1])
assert not str(Path(arrowshdl.__file__).resolve()).startswith(str(repo/'src'))
commands=[]
def cli(*args):
    completed=subprocess.run([str(Path(sys.executable).with_name('arrowshdl.exe' if os.name=='nt' else 'arrowshdl')),*map(str,args)],
                             capture_output=True,text=True,encoding='utf-8',timeout=120)
    assert completed.returncode==0,(args,completed.stdout,completed.stderr)
    commands.append(dict(command=list(map(str,args)),passed=True))

source=root/'logic.sv'
source.write_text('module logic_unit(input logic a,b,output logic y); always_comb y=a^b; endmodule')
cli('--version');cli('check')
cli('compile',source,'--top','logic_unit','-o',root/'compiled')
cli('build',repo/'examples/alu_workbench/project.toml','--layout','macro-grid','-o',root/'alu')
cli('test',root/'alu/alu_workbench.save.txt',repo/'examples/alu_workbench/vectors.json',
    '--vectors','--manifest',root/'alu/alu_workbench.build.json','-o',root/'alu/report.json')
cli('build',repo/'tests/fixtures/circuits/hdl/half_adder/project.toml','-o',root/'scheme')
cli('test',root/'scheme/half_adder.save.txt',repo/'tests/fixtures/circuits/hdl/half_adder/vectors.json',
    '--vectors','--manifest',root/'scheme/half_adder.build.json','-o',root/'vectors.report.json')
cli('compile','-c',source,'--top','logic_unit','-o',root/'logic.object.json')
cli('link',root/'logic.object.json','--top','logic_unit','-o',root/'linked')
cli('decode',root/'compiled/logic_unit.save.txt','-o',root/'decoded.json')
cli('encode',root/'decoded.json','-o',root/'roundtrip.save.txt')
assert read_map(root/'roundtrip.save.txt')==read_map(root/'compiled/logic_unit.save.txt')
cli('graph',root/'roundtrip.save.txt','-o',root/'graph.json')
cli('preview',root/'roundtrip.save.txt','-o',root/'preview.png')
assert (root/'preview.png').stat().st_size>100
result=arrowshdl.compile(source,top='logic_unit',out=root/'api')
vectors=[dict(inputs=dict(a=a,b=b),expect=dict(y=a^b)) for a,b in ((0,0),(1,0),(1,1),(0,1))]
scenario=make_scenario(result.metadata,vectors,compressed=True)
fixture=add_fixture(result.cells,result.metadata)
report=arrowshdl.simulate(fixture,scenario,optimize_cycles=False)
assert report['passed']
from arrowshdl.mapdata import write_map
write_map(root,'fixture',fixture)
(root/'scenario.json').write_text(json.dumps(scenario))
cli('simulate',root/'fixture.save.txt',root/'scenario.json','-o',root/'simulated.report.json')
native=root/'native.v'
native.write_text('module native(input a,output q,r); arrows_toggle t(a,q); arrows_random n(a,r); endmodule')
native_result=arrowshdl.compile(native,top='native',out=root/'native')
arrowshdl.simulate(add_fixture(native_result.cells,native_result.metadata),dict(ticks=20,
    inputs=[dict(at=native_result.ports['inputs']['a'][0]['fixture'],values=[1]*20)],expect=[],
    observe=[native_result.ports['outputs']['q'][0]['fixture']]))
obj=arrowshdl.compile_object(source,top='logic_unit',out=root/'api.object.json')
linked=arrowshdl.link([root/'api.object.json'],top='logic_unit',out=root/'api-linked')
assert linked.cells==result.cells
assert arrowshdl.build(repo/'tests/fixtures/circuits/hdl/half_adder/project.toml',out=root/'api-built').cells
data=dict(passed=True,version=arrowshdl.__version__,package=str(Path(arrowshdl.__file__).resolve()),
          cwd=str(root),commands=commands,python_api=True,native_library=True,macro_grid=True,
          save_sha256=save_sha256(root/'compiled/logic_unit.save.txt'))
(repo/'build/clean-smoke.report.json').write_text(json.dumps(data,indent=2)+'\n')
print('PASS: clean wheel, external cwd, minimal PATH, all public commands and Python API')
