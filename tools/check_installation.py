"""Exercise the installed wheel and public commands outside the checkout."""
from pathlib import Path
import json
import os
import subprocess
import sys
import sysconfig

import arrowshdl
from arrowshdl.mapdata import read_map, save_sha256, write_map
from arrowshdl.test_harness import add_fixture, make_scenario

root = Path.cwd().resolve()
repo = Path(sys.argv[1]).resolve()
package = Path(arrowshdl.__file__).resolve()
assert not package.is_relative_to(repo / 'src'), package
assert not root.is_relative_to(repo), 'Run this smoke test outside the checkout'
commands = []
environment = dict(os.environ, PYTHONUTF8='1')
environment.pop('PYTHONPATH', None)
scripts = Path(sysconfig.get_path('scripts'))
environment['PATH'] = str(scripts) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + (
    str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32')
    if os.name == 'nt' else '/usr/bin:/bin')


def cli(*args):
    executable = scripts / ('arrowshdl.exe' if os.name == 'nt' else 'arrowshdl')
    completed = subprocess.run([str(executable), *map(str, args)], env=environment,
        capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert completed.returncode == 0, (args, completed.stdout, completed.stderr)
    commands.append(dict(command=list(map(str, args)), passed=True))


source = root / 'logic.sv'
source.write_text('module logic_unit(input logic a,b,output logic y); always_comb y=a^b; endmodule', encoding='utf-8')
project = root / 'project.toml'
project.write_text('version=3\ntop="logic_unit"\nsources=["logic.sv"]\n', encoding='utf-8')
vectors = [dict(inputs=dict(a=a, b=b), expect=dict(y=a ^ b)) for a in (0, 1) for b in (0, 1)]
vector_file = root / 'vectors.json'
vector_file.write_text(json.dumps(vectors), encoding='utf-8')

cli('--version')
module = subprocess.run([sys.executable, '-m', 'arrowshdl', '--version'], env=environment,
    capture_output=True, text=True, encoding='utf-8', timeout=30)
assert module.returncode == 0 and arrowshdl.__version__ in module.stdout
cli('health')
cli('compile', source, '--top', 'logic_unit', '-o', root / 'compiled.save.txt', '--preview', root / 'compiled.png')
cli('build', project, '-o', root / 'scheme.save.txt')
cli('test', project, vector_file, '--vectors', '-o', root / 'project.report.json')
cli('test', source, vector_file, '--top', 'logic_unit', '--vectors', '-o', root / 'source.report.json')
assert all(json.loads((root / name).read_text())['passed'] for name in ('project.report.json', 'source.report.json'))
cli('compile', '-c', source, '--top', 'logic_unit', '-o', root / 'logic.aho.json')
cli('link', root / 'logic.aho.json', '--top', 'logic_unit', '-o', root / 'linked.save.txt')
cli('decode', root / 'compiled.save.txt', '-o', root / 'decoded.json')
cli('encode', root / 'decoded.json', '-o', root / 'roundtrip.save.txt')
assert read_map(root / 'roundtrip.save.txt') == read_map(root / 'compiled.save.txt')
cli('graph', root / 'roundtrip.save.txt', '-o', root / 'graph.json')
cli('preview', root / 'roundtrip.save.txt', '-o', root / 'preview.png')
assert (root / 'preview.png').stat().st_size > 100

result = arrowshdl.compile(source, top='logic_unit', out=root / 'api.save.txt')
fixture = add_fixture(result.cells, result.metadata)
scenario = make_scenario(result.metadata, vectors, compressed=True)
assert arrowshdl.simulate(fixture, scenario, optimize_cycles=False)['passed']
write_map(root, 'fixture', fixture)
(root / 'scenario.json').write_text(json.dumps(scenario), encoding='utf-8')
cli('simulate', root / 'fixture.save.txt', root / 'scenario.json', '-o', root / 'simulated.report.json')
assert json.loads((root / 'simulated.report.json').read_text())['passed']
arrowshdl.compile_object(source, top='logic_unit', out=root / 'api.aho.json')
assert arrowshdl.link([root / 'api.aho.json'], top='logic_unit').cells == result.cells
built = arrowshdl.build(project)
assert arrowshdl.simulate(add_fixture(built.cells, built.metadata),
    make_scenario(built.metadata, vectors, compressed=True))['passed']

native = root / 'native.v'
native.write_text('module native(input a,output q); arrows_toggle t(a,q); endmodule', encoding='utf-8')
native_result = arrowshdl.compile(native, top='native')
trace = arrowshdl.simulate(add_fixture(native_result.cells, native_result.metadata), dict(ticks=80,
    inputs=[dict(at=native_result.ports['inputs']['a'][0]['fixture'], values=[1] * 80)], expect=[],
    observe=[native_result.ports['outputs']['q'][0]['fixture']]), optimize_cycles=False)
assert set(trace['observations'][0]['values'][-40:]) == {0, 1}
from arrowshdl.components import load_component
from arrowshdl.manifest import component_file
for name in ('history64', 'seven_segment'):
    assert load_component(component_file(root, 'library:' + name))[0]

data = dict(passed=True, version=arrowshdl.__version__, package=str(package), cwd=str(root),
    commands=commands, python_api=True, native_library=True, external_cwd=True, minimal_path=True,
    save_sha256=save_sha256(root / 'compiled.save.txt'))
output = repo / 'build/clean-smoke.report.json'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
print('PASS: installed wheel, external cwd, minimal PATH, public commands and Python API')
