"""Public command-line API. Build artifacts are written only to --out."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
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
    parser = argparse.ArgumentParser(prog='arrowshdl', description='Verilog → карта Logic Arrows')
    parser.add_argument('--version', action='version', version=f'ArrowsHDL {__version__}')
    commands = parser.add_subparsers(dest='command', required=True)
    check=commands.add_parser('check',help='Проверить установку или запустить набор тестов компилятора')
    check.add_argument('--suite',type=Path,help='Папка тестов из исходного репозитория')
    compile = commands.add_parser('compile', help='Скомпилировать исходники HDL')
    compile.add_argument('sources', nargs='+', type=Path)
    compile.add_argument('--top')
    compile.add_argument('-o', '--out', required=True, type=Path)
    compile.add_argument('-c', action='store_true', help='Получить объект модуля .aho.json')
    compile.add_argument('--std', choices=SUPPORTED_STANDARDS, default=DEFAULT_STANDARD)
    compile.add_argument('-I', dest='includes', action='append', default=[], type=Path)
    compile.add_argument('-L', '--library', dest='libraries', action='append', default=[], type=Path, help='Дополнительный файл библиотеки HDL')
    compile.add_argument('-D', dest='defines', action='append', default=[])
    compile.add_argument('-G', dest='parameters', action='append', default=[], metavar='NAME=VALUE')
    compile.add_argument('--extern', action='append',default=[],help='Модуль с объявленным интерфейсом, реализация поступит при link; только -c')
    compile.add_argument('--layout', choices=('compact', 'sparse', 'fixed', 'macro-grid'), default='compact')
    compile.add_argument('--input-bus', action='append', default=[])
    compile.add_argument('--input-bus-gap', default='auto')
    compile.add_argument('--timeout', type=float, default=600)
    compile.add_argument('--max-cells', type=int, default=1000000)
    compile.add_argument('--preview', action='store_true')
    build = commands.add_parser('build', help='Прочитать проект TOML и собрать схему')
    build.add_argument('project', type=Path)
    build.add_argument('-o', '--out', required=True, type=Path)
    build.add_argument('--timeout', type=float, default=600)
    build.add_argument('--layout', choices=('compact', 'sparse', 'macro-grid'), default='compact', help='Алгоритм компилятора; не является частью схемы')
    build.add_argument('--max-cells', type=int, default=1000000)
    build.add_argument('--test', action='store_true', help='Заменить кнопки тестовыми источниками, сохранить дисплеи')
    link = commands.add_parser('link', help='Скомпоновать объекты RTLIL в карту')
    link.add_argument('objects', nargs='+', type=Path)
    link.add_argument('--top', required=True)
    link.add_argument('-o', '--out', required=True, type=Path)
    link.add_argument('--timeout', type=float, default=600)
    link.add_argument('--layout', choices=('compact', 'sparse', 'fixed', 'macro-grid'), default='compact')
    for name in ('simulate', 'test'):
        sim = commands.add_parser(name, help='Запустить общий физический симулятор')
        sim.add_argument('map', nargs='?', type=Path)
        sim.add_argument('scenario', nargs='?', type=Path)
        sim.add_argument('-o', '--out', type=Path)
        if name == 'test':
            sim.add_argument('--suite', type=Path, help='Общие регрессии unittest из исходного репозитория')
        sim.add_argument('--manifest', type=Path)
        sim.add_argument('--vectors', action='store_true', help='scenario содержит список логических векторов inputs/expect; требуется --manifest')
        sim.add_argument('--timeout', type=float, default=120)
        sim.add_argument('--no-optimize-cycles', action='store_true')
    for name in ('encode', 'decode', 'graph'):
        codec = commands.add_parser(name, help='Преобразовать карту и сохранение')
        codec.add_argument('source', type=Path)
        codec.add_argument('-o', '--out', required=True, type=Path)
    preview = commands.add_parser('preview', help='Получить предпросмотр схемы')
    preview.add_argument('map', type=Path)
    preview.add_argument('manifest', nargs='?', type=Path)
    preview.add_argument('-o', '--out', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command=='check':
            from arrowshdl.checks import check_installation,check_suite
            return check_suite(args.suite) if args.suite else check_installation()
        elif args.command == 'compile':
            top = args.top or args.sources[0].stem
            parameters = {}
            for pair in args.parameters:
                if '=' not in pair:
                    raise MapError('-G: ожидается NAME=VALUE')
                name, value = pair.split('=', 1)
                parameters[name] = value
            opts = dict(standard=args.std, include_dirs=args.includes, defines=args.defines, parameters=parameters)
            if args.c:
                from arrowshdl.objects import compile_object
                compile_object([*args.sources, *args.libraries], top, args.out, args.timeout, blackbox_modules=args.extern,**opts)
                print(f'{top}: объект {args.out}')
                return 0
            if args.extern:raise MapError('--extern применяется только с -c')
            gap = args.input_bus_gap if args.input_bus_gap == 'auto' else int(args.input_bus_gap)
            result = api.compile(args.sources, top=top, out=args.out, timeout=args.timeout,
                libraries=args.libraries, max_cells=args.max_cells, layout=args.layout,
                input_buses=args.input_bus, input_bus_gap=gap, preview=args.preview, **opts)
            cells, manifest = result.cells, result.metadata
        elif args.command == 'build':
            from arrowshdl.scheme import build_scheme
            cells, manifest = build_scheme(args.project,args.out,timeout=args.timeout,layout=args.layout,
                                          max_cells=args.max_cells,testing=args.test)
        elif args.command == 'link':
            result = api.link(args.objects, top=args.top, out=args.out, timeout=args.timeout, layout=args.layout)
            cells, manifest = result.cells, result.metadata
        elif args.command in ('simulate', 'test'):
            if getattr(args,'suite',None):
                from arrowshdl.checks import check_suite
                return check_suite(args.suite,args.out)
            if not args.map or not args.scenario or not args.out:
                raise MapError('Укажите map, scenario и --out, либо test --suite')
            from arrowshdl.simulation import simulate
            from arrowshdl.test_harness import add_fixture
            cells = read_map(args.map)
            scenario = _json(args.scenario)
            if args.vectors:
                if not args.manifest:
                    raise MapError('--vectors требует --manifest')
                from arrowshdl.test_harness import make_scenario
                scenario = make_scenario(_json(args.manifest), scenario, compressed=True)
            if args.manifest:
                cells = add_fixture(cells, _json(args.manifest))
            report = simulate(cells, scenario, timeout=args.timeout, optimize_cycles=not args.no_optimize_cycles)
            from arrowshdl.mapdata import save_sha256, map_hash
            report.update(save_sha256=save_sha256(args.map), source_map_hash=map_hash(read_map(args.map)),
                          scenario_sha256=save_sha256(args.scenario))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_json(args.out, report)
            status = 'TRACE' if report['passed'] is None else 'PASS' if report['passed'] else 'FAIL'
            print(f"{status}: {report.get('checked_samples', 0)} проверок")
            return 1 if report['passed'] is False else 0
        elif args.command == 'encode':
            cells = read_map(args.source)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(encode(cells)+'\n', encoding='ascii')
            return 0
        elif args.command in ('decode','graph'):
            args.out.parent.mkdir(parents=True, exist_ok=True)
            cells=read_map(args.source)
            document=to_document(cells)
            if args.command=='graph':
                from arrowshdl.native_rules import dependency_links
                document=dict(format='arrowshdl-placed-graph',version=1,map=document,
                              dependencies=[dict(at=list(p),to=[list(q) for q in sorted(targets)])
                                            for p,targets in sorted(dependency_links(cells).items())])
            write_json(args.out,document)
            return 0
        elif args.command == 'preview':
            args.out.parent.mkdir(parents=True, exist_ok=True)
            from arrowshdl.map_preview import render_cells
            render_cells(read_map(args.map), args.out, _json(args.manifest) if args.manifest else None)
            return 0
        print(f"{manifest['top']}: {len(cells)} стрелок, {manifest['bounds']['width']}×{manifest['bounds']['height']}")
        return 0
    except (MapError, OSError, ValueError, subprocess.TimeoutExpired,subprocess.CalledProcessError) as exc:
        print(f'Ошибка: {exc}', file=sys.stderr)
        return 2
