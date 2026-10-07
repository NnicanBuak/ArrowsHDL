"""Compile 2:1, 4:1 and 8:1 multiplexers; exhaustively verify exported maps."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from verilog_compile import compile_file
from mapdata import read_map, write_json
from map_preview import render
from test_harness import run_vectors
from streaming import verify_streaming


def run():
    here = Path(__file__).resolve().parent
    summary = []
    for count in (2, 4, 8):
        stem = f"mux{count}"
        folder = here / stem / "build"
        cells, manifest = compile_file(here / stem / f"{stem}.v", stem, folder,
                                       input_buses=['data','sel'], input_bus_gap='auto')
        vectors = [{"inputs": {"data": data, "sel": sel},
                    "expect": {"y": (data >> sel) & 1}}
                   for data in range(1 << count) for sel in range(count)]
        unique = len(vectors)
        vectors += list(reversed(vectors))
        write_json(folder / f"{stem}.vectors.json", {"oracle": "(data >> sel) & 1", "unique_combinations": unique, "vectors": vectors})
        _, report = run_vectors(cells, manifest, vectors, folder, stem, compressed=True)
        render(read_map(folder / f"{stem}.save.txt"), manifest, folder / f"{stem}.preview.png")
        examples = [row for row in report["truth_table"][:unique]
                    if row["inputs"]["data"] == 1 << row["inputs"]["sel"]]
        render(read_map(folder / f"{stem}.test.save.txt"), manifest, folder / f"{stem}.test.preview.png", report, examples[:8])
        row = {"name": stem, "data_inputs": count, "select_bits": (count - 1).bit_length(),
               "unique_combinations": unique, "cells": len(cells), "bounds": manifest["bounds"],
               "settle_ticks": manifest["settle_ticks"], "passed": report["passed"],
               "logic_core": manifest["logic_core"], "layout": manifest["layout"],
               "vectors": report["vectors"], "checked_samples": report["checked_samples"]}
        summary.append(row)
        print(row, flush=True)
        if not report["passed"]:
            raise RuntimeError(f"{stem}: exported map failed selection checks")
        streams=verify_streaming(manifest,folder,stem)
        row['stream_latencies']=[channel['latency_ticks'] for channel in streams]
    write_json(here / "comparison.json", summary)
    return summary


if __name__ == "__main__":
    run()
