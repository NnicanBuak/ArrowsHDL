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


def _result(cells, metadata, output):
    from arrowshdl.artifacts import export
    path = export(output, cells, metadata)
    return BuildResult(cells, {side: metadata[side] for side in ('inputs', 'outputs')}, metadata, {'output': path})


@bounded
def compile(sources, *, top, out, timeout=600, libraries=(), **options):
    from arrowshdl.verilog_compile import compile_file
    from arrowshdl.artifacts import validate_output
    validate_output(out)
    files = [sources] if isinstance(sources, (str, Path)) else list(sources)
    with tempfile.TemporaryDirectory(prefix='arrowshdl-compile-') as directory:
        cells, meta = compile_file([*files, *libraries], top, directory, timeout=timeout, **options)
    return _result(cells, meta, out)


@bounded
def build(project, *, out, timeout=600, **options):
    from arrowshdl.scheme import build_scheme
    from arrowshdl.artifacts import validate_output
    validate_output(out)
    with tempfile.TemporaryDirectory(prefix='arrowshdl-build-') as directory:
        cells, meta = build_scheme(project, directory, timeout=timeout, **options)
    return _result(cells, meta, out)


@bounded
def link(objects, *, top, out, timeout=600, **options):
    from arrowshdl.objects import link_objects
    from arrowshdl.verilog_compile import emit_build
    from arrowshdl.artifacts import validate_output
    validate_output(out)
    graph, log, standard = link_objects(objects, top, timeout)
    with tempfile.TemporaryDirectory(prefix='arrowshdl-link-') as directory:
        cells, meta = emit_build(graph, [], top, Path(directory), log, standard=standard, **options)
    return _result(cells, meta, out)


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
