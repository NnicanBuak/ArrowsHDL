"""Verilog -> logic graph -> placed cell data -> JSON and Base64."""
import argparse
import hashlib
import math
import os
from pathlib import Path
import subprocess
import sys

from arrowasm import MapError
from arrow_layout import place
from mapdata import read_map, write_json, write_map
from verilog_frontend import synthesize


def compile_file(source, top, folder, timeout=90, max_cells=100_000, layout="compact", input_buses=None, input_bus_gap='auto'):
    if not math.isfinite(timeout) or timeout <= 0:
        raise MapError("Таймаут должен быть положительным")
    netlist, log = synthesize(source, top, timeout)
    cells, manifest = place(netlist, max_cells, layout, input_buses=input_buses, input_bus_gap=input_bus_gap)
    manifest["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest["source"] = source.name
    manifest["yosys"] = netlist["creator"]
    from input_buses import verify_exterior
    verify_exterior(cells,manifest)
    write_map(folder, top, cells)
    verify_exterior(read_map(folder / f'{top}.save.txt'),manifest)
    write_json(folder / f"{top}.logic.json", netlist)
    manifest["logic_sha256"] = hashlib.sha256((folder / f"{top}.logic.json").read_bytes()).hexdigest()
    write_json(folder / f"{top}.build.json", manifest)
    (folder / f"{top}.yosys.log").write_text(log, encoding="utf-8")
    if manifest.get('signals'):
        from signal_view import export_views
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
