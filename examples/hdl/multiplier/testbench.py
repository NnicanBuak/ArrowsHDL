"""Compile three unsigned multipliers and verify every input pair on saved maps."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from verilog_compile import compile_file
from mapdata import read_map, write_json
from map_preview import render
from test_harness import run_vectors


def run():
    here = Path(__file__).resolve().parent
    summary = []
    for width in (2, 3, 4):
        stem = f"mul{width}"
        folder = here / stem / "build"
        cells, manifest = compile_file(here / stem / f"{stem}.v", stem, folder)
        limit = 1 << width
        vectors = [{"inputs": {"a": a, "b": b}, "expect": {"product": a * b}}
                   for a in range(limit) for b in range(limit)]
        # Reverse order exercises transitions without restarting the simulator.
        vectors += list(reversed(vectors))
        write_json(folder / f"{stem}.vectors.json", {"oracle": "Python a * b", "unique_pairs": limit ** 2, "vectors": vectors})
        _, report = run_vectors(cells, manifest, vectors, folder, stem, compressed=True)
        render(read_map(folder / f"{stem}.save.txt"), manifest, folder / f"{stem}.preview.png")
        render(read_map(folder / f"{stem}.test.save.txt"), manifest, folder / f"{stem}.test.preview.png", report, report["truth_table"][:8])
        row = {"name": stem, "input_bits": width, "values_per_input": limit,
               "unique_pairs": limit ** 2, "cells": len(cells), "bounds": manifest["bounds"],
               "settle_ticks": manifest["settle_ticks"], "passed": report["passed"],
               "vectors": report["vectors"], "checked_samples": report["checked_samples"]}
        summary.append(row)
        print(row, flush=True)
        if not report["passed"]:
            raise RuntimeError(f"{stem}: physical map failed multiplication checks")
    write_json(here / "comparison.json", summary)
    return summary


if __name__ == "__main__":
    run()
