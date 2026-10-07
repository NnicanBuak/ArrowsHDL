"""Headless save -> GraphDLC cycle optimizer -> native Rust simulation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from arrowasm import MapError, decode
from mapdata import read_map
from simulation import simulate

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Stable CLI encoding, including diagnostics in Windows subprocess pipes.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Автотесты карт Стрелочек через GraphDLC без браузера")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--save", type=Path, help="Файл сохранения Base64 v0")
    source.add_argument("--code", help="Строка сохранения Base64 v0")
    source.add_argument("--map", type=Path, help="Модель карты JSON schema=1")
    parser.add_argument("--test", required=True, type=Path, help="JSON сценарий сигналов")
    parser.add_argument("--no-cycles", action="store_true", help="Отключить оптимизацию кольцевой памяти")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=60, help="Ограничение каждой стадии, секунды")
    args = parser.parse_args()
    try:
        if not 0 < args.timeout < float("inf"):
            raise MapError("Таймаут должен быть положительным")
        cells = read_map(args.map) if args.map else decode(args.save.read_text(encoding="utf-8-sig") if args.save else args.code)
        scenario = json.loads(args.test.read_text(encoding="utf-8-sig"))
        report = simulate(cells, scenario, not args.no_cycles, args.timeout)
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            args.report.write_text(output, encoding="utf-8")
        print(output, end="")
        return 0 if report["passed"] else 1
    except (OSError, MapError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
