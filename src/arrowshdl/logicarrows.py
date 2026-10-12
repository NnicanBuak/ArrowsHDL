"""Headless save -> GraphDLC cycle optimizer -> native Rust simulation."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from arrowshdl.arrowasm import MapError, decode
from arrowshdl.mapdata import read_map
from arrowshdl.simulation import simulate

ROOT = Path(__file__).resolve().parents[2]


def main():
    # Stable CLI encoding, including diagnostics in Windows subprocess pipes.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Test Logic Arrows maps with GraphDLC")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--save", type=Path, help="Base64 v0 game save file")
    source.add_argument("--code", help="Base64 v0 game save string")
    source.add_argument("--map", type=Path, help="JSON map model (schema=1)")
    parser.add_argument("--test", required=True, type=Path, help="JSON signal scenario")
    parser.add_argument("--no-cycles", action="store_true", help="Disable ring memory optimization")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=60, help="Timeout per stage in seconds")
    args = parser.parse_args()
    try:
        if not 0 < args.timeout < float("inf"):
            raise MapError("Timeout must be positive")
        cells = read_map(args.map) if args.map else decode(args.save.read_text(encoding="utf-8-sig") if args.save else args.code)
        scenario = json.loads(args.test.read_text(encoding="utf-8-sig"))
        report = simulate(cells, scenario, not args.no_cycles, args.timeout)
        output = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            args.report.write_text(output, encoding="utf-8")
        print(output, end="")
        return 1 if report["passed"] is False else 0
    except (OSError, MapError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
