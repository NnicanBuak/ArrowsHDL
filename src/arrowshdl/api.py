"""Stable Python entry points; results include cells, ports and artifact paths."""
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile

from arrowshdl.arrowasm import Cell
from arrowshdl.execution import bounded


@dataclass(frozen=True)
class BuildResult:
    cells: dict[tuple[int, int], Cell]
    ports: dict
    metadata: dict
    artifacts: dict[str, Path]


def _result(cells, metadata, output, preview=None):
    from arrowshdl.artifacts import export
    artifacts={}
    if output is not None:
        artifacts['output']=export(output, cells)
    if preview is not None:
        from arrowshdl.map_preview import render_cells
        preview=Path(preview)
        preview.parent.mkdir(parents=True,exist_ok=True)
        render_cells(cells,preview,metadata)
        artifacts['preview']=preview.resolve()
    return BuildResult(cells, {side: metadata[side] for side in ('inputs', 'outputs')}, metadata, artifacts)


@bounded
def compile(sources, *, top, out=None, timeout=600, libraries=(), preview=None, **options):
    from arrowshdl.verilog_compile import compile_file
    from arrowshdl.artifacts import validate_output,validate_preview
    if out is not None: validate_output(out)
    if preview is not None: validate_preview(preview,out)
    files = [sources] if isinstance(sources, (str, Path)) else list(sources)
    with tempfile.TemporaryDirectory(prefix='arrowshdl-compile-') as directory:
        cells, meta = compile_file([*files, *libraries], top, directory, timeout=timeout, **options)
    return _result(cells, meta, out, preview)


@bounded
def build(project, *, out=None, timeout=600, preview=None, **options):
    from arrowshdl.scheme import build_scheme
    from arrowshdl.artifacts import validate_output,validate_preview
    if out is not None: validate_output(out)
    if preview is not None: validate_preview(preview,out)
    with tempfile.TemporaryDirectory(prefix='arrowshdl-build-') as directory:
        cells, meta = build_scheme(project, directory, timeout=timeout, **options)
    return _result(cells, meta, out, preview)


@bounded
def link(objects, *, top, out=None, timeout=600, preview=None, **options):
    from arrowshdl.objects import link_objects
    from arrowshdl.verilog_compile import emit_build
    from arrowshdl.artifacts import validate_output,validate_preview
    if out is not None: validate_output(out)
    if preview is not None: validate_preview(preview,out)
    graph, log, standard = link_objects(objects, top, timeout)
    with tempfile.TemporaryDirectory(prefix='arrowshdl-link-') as directory:
        cells, meta = emit_build(graph, [], top, Path(directory), log, standard=standard, **options)
    return _result(cells, meta, out, preview)


def compile_object(sources, *, top, out=None, timeout=90, libraries=(), **options):
    from arrowshdl.objects import compile_object as make
    files = [sources] if isinstance(sources, (str, Path)) else list(sources)
    return make([*files, *libraries], top, out, timeout=timeout, **options)


def simulate(cells, scenario, **options):
    from arrowshdl.mapdata import read_map
    from arrowshdl.simulation import simulate as run
    if isinstance(cells, BuildResult):
        cells = cells.cells
    elif isinstance(cells, (str, Path)):
        cells = read_map(Path(cells))
    if isinstance(scenario, (str, Path)):
        scenario = json.loads(Path(scenario).read_text(encoding='utf-8-sig'))
    return run(cells, scenario, **options)


@bounded
def test(source, scenario, *, top=None, vectors=False, layout='auto', timeout=600,
         optimize_cycles=True, **options):
    """Compile source in memory and test the resulting physical game circuit."""
    from arrowshdl.arrowasm import MapError
    from arrowshdl.test_harness import add_fixture,make_scenario
    from arrowshdl.mapdata import map_hash
    source=Path(source)
    if source.suffix.lower()=='.toml':
        result=build(source,layout=layout,timeout=timeout,**options)
    elif source.suffix.lower() in ('.v','.sv'):
        result=compile(source,top=top or source.stem,layout=layout,timeout=timeout,**options)
    else:
        raise MapError('Test input must be a .toml project or .v/.sv source; use simulate for game saves')
    if isinstance(scenario,(str,Path)):
        scenario=json.loads(Path(scenario).read_text(encoding='utf-8-sig'))
    cells=result.cells
    if vectors:
        scenario=make_scenario(result.metadata,scenario,compressed=True)
        cells=add_fixture(cells,result.metadata)
    report=simulate(cells,scenario,timeout=timeout,optimize_cycles=optimize_cycles)
    report['source_map_hash']=map_hash(result.cells)
    return report
