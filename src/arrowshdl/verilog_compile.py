"""Verilog -> logic graph -> placed cell data -> JSON and Base64."""
import argparse
import hashlib
import math
import os
from pathlib import Path
import subprocess
import sys

from arrowshdl.arrowasm import MapError
from arrowshdl.arrow_layout import place
from arrowshdl.mapdata import read_map, write_json, write_map, save_sha256
from arrowshdl.verilog_frontend import synthesize
from arrowshdl.execution import bounded


@bounded
def compile_file(source, top, folder, timeout=600, max_cells=1_000_000, layout="compact", input_buses=None, input_bus_gap='auto', *, standard='1800-2023', include_dirs=(), defines=(), parameters=None, constraints=None, bindings=None, preview=False):
    if not math.isfinite(timeout) or timeout <= 0:
        raise MapError("Таймаут должен быть положительным")
    sources = [Path(source)] if isinstance(source, (str, Path)) else list(map(Path, source))
    netlist, log = synthesize(sources, top, timeout, standard=standard, include_dirs=include_dirs, defines=defines, parameters=parameters)
    return emit_build(netlist, sources, top, Path(folder), log, max_cells=max_cells, layout=layout,
                      input_buses=input_buses, input_bus_gap=input_bus_gap, constraints=constraints,
                      bindings=bindings, preview=preview, standard=standard)


def emit_build(netlist, sources, top, folder, log='', *, max_cells=1_000_000, layout='compact', input_buses=None, input_bus_gap='auto', constraints=None, bindings=None, preview=False, standard='1800-2023'):
    from arrowshdl import __version__
    from arrowshdl.physical import place_physical
    physical = netlist.get('kind') == 'physical'
    if netlist.get('kind') == 'tick':
        from arrowshdl.tick_layout import place_tick
        cells, manifest = place_tick(netlist, max_cells=max_cells, constraints=constraints)
    elif layout == 'macro-grid' and not physical:
        if input_buses:
            raise MapError('macro-grid не поддерживает группировку входных шин')
        from arrowshdl.tick_layout import place_tick
        cells, manifest = place_tick(netlist, max_cells=max_cells, constraints=constraints)
        manifest['layout'] = 'macro-grid-v1'
    elif physical:
        cells, manifest = place_physical(netlist, max_cells=max_cells, constraints=constraints)
    else:
        if layout == 'fixed' or constraints and (constraints.get('grids') or constraints.get('placements')):
            raise MapError('Закреплённые сетки и позиции требуют структурного HDL и шаблона placement.template')
        cells, manifest = place(netlist, max_cells, layout, input_buses=input_buses, input_bus_gap=input_bus_gap)
    manifest['sources'] = [{'name': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in sources]
    if sources:
        manifest['source'] = sources[0].name
        manifest['source_sha256'] = manifest['sources'][0]['sha256']
    manifest['compiler_version'] = __version__
    manifest['standard'] = standard
    manifest["yosys"] = netlist["creator"]
    from arrowshdl.input_buses import verify_exterior
    physical = physical or netlist.get('kind') == 'tick'
    if not physical and layout != 'macro-grid':
        verify_exterior(cells,manifest)
    write_map(folder, top, cells)
    manifest['save_sha256'] = save_sha256(folder / f'{top}.save.txt')
    if not physical:
        if layout != 'macro-grid':verify_exterior(read_map(folder / f'{top}.save.txt'),manifest)
        write_json(folder / f"{top}.logic.json", netlist)
        manifest["logic_sha256"] = hashlib.sha256((folder / f"{top}.logic.json").read_bytes()).hexdigest()
    if bindings:
        import json
        metadata = json.loads(Path(bindings).read_text(encoding='utf-8-sig'))
        if metadata.get('map_hash') and metadata['map_hash'] != manifest['map_hash']:
            raise MapError('bindings относятся к другой карте')
        manifest['observations'] = metadata
        if physical:
            manifest['hdl_ports'] = {side:manifest[side] for side in ('inputs','outputs')}
            for key in ('inputs','outputs','io_devices','profile','settle_ticks'):
                if key in metadata:
                    manifest[key] = metadata[key]
        write_json(folder / f'{top}.bindings.json', metadata)
        manifest['bindings_sha256'] = hashlib.sha256(Path(bindings).read_bytes()).hexdigest()
    write_json(folder / f"{top}.build.json", manifest)
    if preview and manifest.get('signals'):
        from arrowshdl.signal_view import export_views
        export_views(read_map(folder / f'{top}.save.txt'), manifest, folder, top)
    return cells, manifest


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Компиляция комбинационного Verilog в карты Стрелочек")
    parser.add_argument("source", type=Path)
    parser.add_argument("--top")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--layout", choices=("compact", "sparse"), default="compact")
    parser.add_argument('--input-bus', action='append', default=[], metavar='PORT[,PORT]', help='Сгруппировать входы в шину; флаг можно повторять')
    parser.add_argument('--input-bus-gap', default='auto', help='auto (подбор) или число пустых клеток между источниками')
    parser.add_argument("--trace-layout", action="store_true", help="Показывать попытки размещения и причины отказа")
    args = parser.parse_args()
    if args.input_bus_gap != 'auto':
        try: args.input_bus_gap=int(args.input_bus_gap)
        except ValueError: parser.error('--input-bus-gap: ожидается auto или целое число')
    if args.trace_layout:
        os.environ['ARROWSHDL_LAYOUT_TRACE']='1'
    try:
        cells, manifest = compile_file(args.source, args.top or args.source.stem, args.out, args.timeout, layout=args.layout, input_buses=args.input_bus, input_bus_gap=args.input_bus_gap)
        print(f"{manifest['top']}: {len(cells)} клеток, {manifest['logic_nodes']} элементов логики, установление <= {manifest['settle_ticks']} тактов")
        if core:=manifest.get('logic_core'):
            print(f"Ядро без трасс ввода/вывода: {core['cells']} клеток, {core['bounds']['width']}×{core['bounds']['height']}, {core['ticks']} тактов")
        return 0
    except (MapError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
