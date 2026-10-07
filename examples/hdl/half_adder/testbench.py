"""Separate half-adder test program, based on Nandland's published truth table."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from verilog_compile import compile_file
from mapdata import read_map, write_json
from map_preview import render
from test_harness import run_vectors

# A, B, Sum, Carry. Literal oracle, independent of Yosys and the layout code.
TABLE = [(0, 0, 0, 0), (0, 1, 1, 0), (1, 0, 1, 0), (1, 1, 0, 1)]


def vector(row):
    a, b, s, c = row
    return {"inputs": {"i_bit1": a, "i_bit2": b}, "expect": {"o_sum": s, "o_carry": c}}


def run(folder=None):
    source_dir = Path(__file__).resolve().parent
    folder = Path(folder) if folder else source_dir / "build"
    cells, manifest = compile_file(source_dir / "half_adder.v", "half_adder", folder)
    vectors = [vector(row) for row in TABLE]
    # All 16 ordered transitions, without resetting the simulation between vectors.
    vectors += [vector(row) for before in TABLE for after in TABLE for row in (before, after)]
    write_json(folder / "half_adder.vectors.json", {"source": "https://nandland.com/half-adder/", "table_vectors": len(TABLE), "ordered_transitions": len(TABLE) ** 2, "vectors": vectors})
    test_cells, report = run_vectors(cells, manifest, vectors, folder, "half_adder")
    render(read_map(folder / "half_adder.save.txt"), manifest, folder / "half_adder.preview.png")
    render(read_map(folder / "half_adder.test.save.txt"), manifest, folder / "half_adder.test.preview.png", report, report["truth_table"][:4])
    return report


if __name__ == "__main__":
    report = run()
    print(f"half_adder: passed={report['passed']}, vectors={report['vectors']}, checked={report['checked_samples']}, ticks={report['ticks']}")
    raise SystemExit(0 if report["passed"] else 1)

