"""Run the existing GraphDLC engine directly on the cell model."""
import json
import math
import os
from pathlib import Path
import subprocess

from arrowshdl.arrowasm import MapError
from arrowshdl.execution import bounded

ROOT = Path(__file__).resolve().parents[2]


def runner_binary():
    if os.environ.get('ARROWSHDL_NATIVE'):
        return Path(os.environ['ARROWSHDL_NATIVE']).expanduser().resolve()
    from arrowshdl.resources import PACKAGE
    packaged=PACKAGE/'data/native'/('arrowshdl-engine.exe' if os.name=='nt' else 'arrowshdl-engine')
    if packaged.is_file():return packaged
    return ROOT / "native/target/release" / ("logic-arrows-cli.exe" if os.name == "nt" else "logic-arrows-cli")


def build_runner():
    """Build the one shared engine; projects can use their own budgets."""
    if not (ROOT/'native/Cargo.toml').is_file():raise MapError('Simulator engine is missing. Reinstall the ArrowsHDL platform package')
    subprocess.run(["cargo", "build", "--release", "--locked", "--manifest-path", str(ROOT / "native/Cargo.toml")], check=True)
    return runner_binary()


@bounded
def simulate(cells, scenario, optimize_cycles=True, timeout=60, *, limits=None):
    from arrowshdl.progress import report as progress
    progress(5, 'Validating simulation scenario')
    if not math.isfinite(timeout) or timeout <= 0:
        raise MapError("Timeout must be positive")
    binary = runner_binary()
    if not binary.is_file():
        if os.environ.get('ARROWSHDL_NATIVE'):raise MapError('ARROWSHDL_NATIVE points to a missing file')
        binary=build_runner()
    test = dict(scenario)
    def coordinate(value, context):
        if not isinstance(value,list) or len(value)!=2 or any(type(v) is not int for v in value):
            raise MapError(context+': coordinate must be a pair of integers')
        return tuple(value)
    assertions = test.pop('assert', [])
    controls = test.pop('controls', [])
    probes = test.pop('probes', [])
    if not isinstance(probes,list):
        raise MapError('probes: expected a list of free test receiver coordinates')
    if probes:
        from arrowshdl.arrowasm import Cell
        cells = dict(cells)
        for point in probes:
            at=coordinate(point,'probes')
            if at in cells:
                raise MapError(f'Test receiver {at} occupies an existing cell')
            cells[at]=Cell(23,0)
    if not isinstance(assertions,list) or not isinstance(controls,list):
        raise MapError('assert and controls: expected lists of ports')
    if controls:
        from arrowshdl.arrowasm import Cell
        cells = dict(cells)
        test['inputs'] = list(test.get('inputs',[]))
        for control in controls:
            if not isinstance(control,dict) or set(control) != {'at','values'}:
                raise MapError('controls: expected at and values')
            at = coordinate(control['at'],'controls.at')
            if at not in cells or cells[at].type != 24:
                raise MapError(f'controls: {at} must contain a directional type 24 button')
            c = cells[at]
            cells[at] = Cell(22,c.rotation,c.mirrored)
            test['inputs'].append(control)
    test['observe'] = list(test.get('observe',[]))
    for assertion in assertions:
        if not isinstance(assertion,dict) or set(assertion) != {'at','values'}:
            raise MapError('assert: expected at and values')
        at=coordinate(assertion['at'],'assert.at')
        if at not in cells:
            raise MapError(f'assert: cell {at} is missing')
        if assertion['at'] not in test['observe']:
            test['observe'].append(assertion['at'])
    if limits is not None:
        if not isinstance(limits, dict) or set(limits) - {"nodes", "ticks"}:
            raise MapError("Limits support only nodes and ticks")
        if any(type(v) is not int or v <= 0 for v in limits.values()):
            raise MapError("Limits must be positive integers")
        test["limits"] = dict(limits)
    request = {"cells": [{"x": x, "y": y, "type": c.type, "rotation": c.rotation, "mirrored": c.mirrored} for (x, y), c in sorted(cells.items())], "test": test, "optimize_cycles": optimize_cycles}
    from arrowshdl.resources import GRAPH_COMPILER
    from nodejs_wheel import node
    progress(25, f'Compiling physical simulation graph: {len(cells)} arrows')
    graph = node([str(GRAPH_COMPILER)],return_completed_process=True,input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',timeout=timeout)
    fallback=None
    if graph.returncode and optimize_cycles and 'Cycle search budget exceeded' in graph.stderr:
        fallback='cycle search budget exceeded'
        progress(35, 'Cycle optimizer budget exceeded; compiling the physical graph without ring optimization')
        request['optimize_cycles']=False
        graph=node([str(GRAPH_COMPILER)],return_completed_process=True,input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',timeout=timeout)
    if graph.returncode:
        raise MapError(graph.stderr.strip())
    progress(50, 'Running native simulation engine')
    result = subprocess.run([str(binary)], input=graph.stdout, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if result.returncode not in (0, 1):
        raise MapError(result.stderr.strip())
    report = json.loads(result.stdout)
    report['cycle_optimization']=dict(requested=optimize_cycles,enabled=request['optimize_cycles'],fallback=fallback)
    progress(90, 'Checking simulation results')
    from arrowshdl.mapdata import map_hash
    report['simulated_map_hash'] = map_hash(cells)
    observations = {tuple(row['at']):row['values'] for row in report['observations']}
    for assertion in assertions:
        values = assertion['values']
        actual = observations[tuple(assertion['at'])]
        if not isinstance(values,list) or len(values) != len(actual) or any(v is not None and (type(v) is not int or v not in (0,1)) for v in values):
            raise MapError('assert.values: expected one 0, 1 or null per scenario sample')
        for i,(expected,measured) in enumerate(zip(values,actual)):
            if expected is None:
                continue
            report['checked_samples'] += 1
            if measured != expected:
                report['failure_count'] += 1
                if len(report['failures']) < 100:
                    report['failures'].append(dict(sample=i+1,at=assertion['at'],expected=expected,actual=measured))
    if report['checked_samples']:
        report['passed'] = report['failure_count'] == 0
    return report
