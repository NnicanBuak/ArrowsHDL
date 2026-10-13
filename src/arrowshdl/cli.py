"""Public command-line API. Build artifacts are written only to --out."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import os
from arrowshdl import api

from arrowshdl import __version__
from arrowshdl.arrowasm import MapError, encode
from arrowshdl.mapdata import read_map, to_document, write_json
from arrowshdl.manifest import load_project
from arrowshdl.standards import DEFAULT_STANDARD, SUPPORTED_STANDARDS
from arrowshdl.verilog_compile import compile_file, emit_build


def _json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(prog='arrowshdl', description='Compile Verilog into Logic Arrows maps')
    parser.add_argument('--version', action='version', version=f'ArrowsHDL {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('health', help='Check ArrowsHDL operational health',
                        description='Check runtimes, compilation, save codec, simulation and preview rendering.')
    compile = commands.add_parser('compile', help='Compile HDL sources')
    compile.add_argument('sources', nargs='+', type=Path)
    compile.add_argument('--top')
    compile.add_argument('-o', '--out', required=True, type=Path, metavar='FILE',help='Encoded game scheme (.txt)')
    compile.add_argument('-c', action='store_true', help='Write a reusable RTLIL module object (.aho.json)')
    compile.add_argument('--std', choices=SUPPORTED_STANDARDS, default=DEFAULT_STANDARD)
    compile.add_argument('-I', dest='includes', action='append', default=[], type=Path)
    compile.add_argument('-L', '--library', dest='libraries', action='append', default=[], type=Path, help='Additional HDL library file')
    compile.add_argument('-D', dest='defines', action='append', default=[])
    compile.add_argument('-G', dest='parameters', action='append', default=[], metavar='NAME=VALUE')
    compile.add_argument('--extern', action='append',default=[],help='Declared module interface resolved at link time; requires -c')
    compile.add_argument('--layout', choices=('auto','compact', 'sparse', 'fixed', 'macro-grid'), default='auto')
    compile.add_argument('--compact',action='store_true',help='Search additional graph placements for fewer arrows and a smaller complete map')
    compile.add_argument('--input-bus', action='append', default=[])
    compile.add_argument('--input-bus-gap', default='auto')
    compile.add_argument('--timeout', type=float, default=600)
    compile.add_argument('--max-cells', type=int, default=1000000)
    build = commands.add_parser('build', help='Build a scheme from a TOML project')
    build.add_argument('project', type=Path)
    build.add_argument('-o', '--out', required=True, type=Path, metavar='FILE',help='Encoded game scheme (.txt)')
    build.add_argument('--timeout', type=float, default=600)
    build.add_argument('--layout', choices=('auto','compact', 'sparse', 'macro-grid'), default='auto', help='Compiler layout algorithm')
    build.add_argument('--compact',action='store_true',help='Search additional graph placements for fewer arrows and a smaller complete map')
    build.add_argument('--max-cells', type=int, default=1000000)
    build.add_argument('--test', action='store_true', help='Replace buttons with test sources and preserve displays')
    link = commands.add_parser('link', help='Link RTLIL objects into a scheme')
    link.add_argument('objects', nargs='+', type=Path)
    link.add_argument('--top', required=True)
    link.add_argument('-o', '--out', required=True, type=Path, metavar='FILE',help='Encoded game scheme (.txt)')
    link.add_argument('--timeout', type=float, default=600)
    link.add_argument('--layout', choices=('auto','compact', 'sparse', 'fixed', 'macro-grid'), default='auto')
    link.add_argument('--compact',action='store_true',help='Search additional graph placements for fewer arrows and a smaller complete map')
    for name in ('simulate', 'test'):
        sim = commands.add_parser(name, help='Run the physical simulator')
        sim.add_argument('map', nargs='?', type=Path)
        sim.add_argument('scenario', nargs='?', type=Path)
        sim.add_argument('-o', '--out', type=Path)
        if name == 'test':
            sim.add_argument('--suite', type=Path, help='Run repository unittest regressions')
        sim.add_argument('--manifest', type=Path)
        sim.add_argument('--timeout', type=float, default=120)
        sim.add_argument('--no-optimize-cycles', action='store_true')
    for name in ('encode', 'decode', 'graph'):
        codec = commands.add_parser(name, help='Convert maps and game saves')
        codec.add_argument('source', type=Path)
        codec.add_argument('-o', '--out', required=True, type=Path)
    preview = commands.add_parser('preview', help='Render a scheme preview')
    preview.add_argument('map', type=Path)
    preview.add_argument('manifest', nargs='?', type=Path)
    preview.add_argument('-o', '--out', required=True, type=Path)
    preview.add_argument('--style','--preview-style',dest='style',choices=('default','logical'),default='default',
                         help='Preview style: default cell map or logical graph overlay')
    preview.add_argument('--top', help='Top module when previewing HDL source')
    preview.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args(argv)
    os.environ['ARROWSHDL_PROGRESS'] = '1'
    from arrowshdl.progress import report, reset
    reset()
    report(0, f'Starting {args.command}')
    try:
        if args.command=='health':
            from arrowshdl.health import health
            return health()
        elif args.command == 'compile':
            top = args.top or args.sources[0].stem
            parameters = {}
            for pair in args.parameters:
                if '=' not in pair:
                    raise MapError('-G: expected NAME=VALUE')
                name, value = pair.split('=', 1)
                parameters[name] = value
            opts = dict(standard=args.std, include_dirs=args.includes, defines=args.defines, parameters=parameters)
            if args.c:
                from arrowshdl.objects import compile_object
                compile_object([*args.sources, *args.libraries], top, args.out, args.timeout, blackbox_modules=args.extern,**opts)
                report(100, f'Object written: {args.out}')
                return 0
            if args.extern:raise MapError('--extern requires -c')
            gap = args.input_bus_gap if args.input_bus_gap == 'auto' else int(args.input_bus_gap)
            result = api.compile(args.sources, top=top, out=args.out, timeout=args.timeout,
                libraries=args.libraries, max_cells=args.max_cells, layout=args.layout,
                input_buses=args.input_bus, input_bus_gap=gap,compact=args.compact, **opts)
            cells, manifest = result.cells, result.metadata
        elif args.command == 'build':
            result = api.build(args.project,out=args.out,timeout=args.timeout,layout=args.layout,
                               max_cells=args.max_cells,testing=args.test,compact=args.compact)
            cells, manifest = result.cells, result.metadata
        elif args.command == 'link':
            result = api.link(args.objects, top=args.top, out=args.out, timeout=args.timeout, layout=args.layout,compact=args.compact)
            cells, manifest = result.cells, result.metadata
        elif args.command in ('simulate', 'test'):
            if getattr(args,'suite',None):
                from arrowshdl.checks import check_suite
                return check_suite(args.suite,args.out)
            if not args.map or not args.scenario or not args.out:
                raise MapError('Specify map, scenario and --out, or use test --suite')
            from arrowshdl.simulation import simulate
            from arrowshdl.test_harness import add_fixture
            cells = read_map(args.map)
            from arrowshdl.artifacts import read_metadata
            metadata = _json(args.manifest) if args.manifest else read_metadata(args.map)
            scenario = _json(args.scenario)
            if metadata:
                cells = add_fixture(cells, metadata)
            report = simulate(cells, scenario, timeout=args.timeout, optimize_cycles=not args.no_optimize_cycles)
            from arrowshdl.mapdata import save_sha256, map_hash
            report.update(save_sha256=save_sha256(args.map), source_map_hash=map_hash(read_map(args.map)),
                          scenario_sha256=save_sha256(args.scenario))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.out, report)
            from arrowshdl.progress import report as log_progress
            log_progress(100, f'Report written: {args.out}')
            status = 'TRACE' if report['passed'] is None else 'PASS' if report['passed'] else 'FAIL'
            print(f"{status}: {report.get('checked_samples', 0)} checks")
            return 1 if report['passed'] is False else 0
        elif args.command == 'encode':
            report(25, 'Reading and validating map')
            cells = read_map(args.source)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(encode(cells)+'\n', encoding='ascii')
            report(100, f'Save written: {args.out}')
            return 0
        elif args.command in ('decode','graph'):
            report(25, 'Reading and validating map')
            args.out.parent.mkdir(parents=True, exist_ok=True)
            cells=read_map(args.source)
            document=to_document(cells)
            if args.command=='graph':
                from arrowshdl.native_rules import dependency_links
                document=dict(format='arrowshdl-placed-graph',version=1,map=document,
                              dependencies=[dict(at=list(p),to=[list(q) for q in sorted(targets)])
                                            for p,targets in sorted(dependency_links(cells).items())])
            write_json(args.out,document)
            report(100, f'Output written: {args.out}')
            return 0
        elif args.command == 'preview':
            args.out.parent.mkdir(parents=True, exist_ok=True)
            from arrowshdl.map_preview import render_cells
            if args.map.suffix.lower() == '.toml':
                from arrowshdl.scheme import build_scheme
                import tempfile
                report(5, 'Compiling project for preview')
                with tempfile.TemporaryDirectory(prefix='arrowshdl-preview-') as directory:
                    cells, metadata = build_scheme(args.map, directory, timeout=args.timeout)
                    render_cells(cells, args.out, metadata, style=args.style)
            elif args.map.suffix.lower() in ('.v', '.sv'):
                from arrowshdl.verilog_compile import compile_file
                import tempfile
                report(5, 'Compiling HDL for preview')
                with tempfile.TemporaryDirectory(prefix='arrowshdl-preview-') as directory:
                    cells, metadata = compile_file(args.map, args.top or args.map.stem, directory, timeout=args.timeout)
                    render_cells(cells, args.out, metadata, style=args.style)
            else:
                report(25, 'Rendering placed arrows and ports')
                from arrowshdl.artifacts import read_metadata
                metadata = _json(args.manifest) if args.manifest else read_metadata(args.map)
                render_cells(read_map(args.map), args.out, metadata, style=args.style)
            report(100, f'Preview written: {args.out}')
            return 0
        report(100, f'Output written: {args.out}')
        print(f"{manifest['top']}: {len(cells)} arrows, {manifest['bounds']['width']}×{manifest['bounds']['height']}")
        return 0
    except (MapError, OSError, ValueError, subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2
