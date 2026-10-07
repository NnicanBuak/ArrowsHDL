"""Separate full-adder test program, based on Nandland's published truth table."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from verilog_compile import compile_file
from mapdata import read_map, write_json
from map_preview import render
from test_harness import run_vectors

# A, B, Cin, Sum, Cout; a literal truth table from the tutorial, not a compiler oracle.
TABLE = [(0,0,0,0,0), (1,0,0,1,0), (0,1,0,1,0), (1,1,0,0,1),
         (0,0,1,1,0), (1,0,1,0,1), (0,1,1,0,1), (1,1,1,1,1)]


def vector(row):
    a, b, ci, s, co = row
    return {"inputs": {"i_bit1": a, "i_bit2": b, "i_carry": ci}, "expect": {"o_sum": s, "o_carry": co}}


def run(folder=None):
    source_dir = Path(__file__).resolve().parent
    folder = Path(folder) if folder else source_dir / "build"
    cells, manifest = compile_file(source_dir / "full_adder.v", "full_adder", folder)
    vectors = [vector(row) for row in TABLE]
    vectors += [vector(row) for before in TABLE for after in TABLE for row in (before, after)]
    write_json(folder / "full_adder.vectors.json", {"source": "https://nandland.com/full-adder/", "table_vectors": len(TABLE), "ordered_transitions": len(TABLE) ** 2, "vectors": vectors})
    test_cells, report = run_vectors(cells, manifest, vectors, folder, "full_adder")
    render(read_map(folder / "full_adder.save.txt"), manifest, folder / "full_adder.preview.png")
    render(read_map(folder / "full_adder.test.save.txt"), manifest, folder / "full_adder.test.preview.png", report, report["truth_table"][:8])
    return report


if __name__ == "__main__":
    report = run()
    print(f"full_adder: passed={report['passed']}, vectors={report['vectors']}, checked={report['checked_samples']}, ticks={report['ticks']}")
    raise SystemExit(0 if report["passed"] else 1)

