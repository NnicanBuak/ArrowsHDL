"""8-bit adder: unchanged graph, two placements, independent arithmetic tests."""
import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from arrow_layout import place
from mapdata import read_map, write_json, write_map
from map_preview import render
from test_harness import run_vectors, run_vector_batches
from verilog_compile import compile_file

EXAMPLES = [(0,0,0), (1,1,0), (127,1,0), (255,0,1),
            (255,255,0), (255,255,1), (85,170,0), (85,170,1)]


def vector(a, b, cin):
    total = a + b + cin  # Python integer arithmetic; independent of synthesized logic.
    return {"inputs": {"a": a, "b": b, "cin": cin},
            "expect": {"sum": total & 255, "cout": total >> 8}}


def transition_vectors():
    vectors = [vector(*case) for case in EXAMPLES]
    # Every carry-chain length, in both directions, including all-eight-bit carry.
    for length in range(1, 9):
        chain = (1 << length) - 1
        for case in ((chain,1,0), (chain,0,1), (255-chain,chain,0), (255-chain,chain,1)):
            vectors.extend((vector(0,0,0), vector(*case), vector(255,255,1), vector(*case)))
    # Every single input bit toggles while the remaining inputs are stable.
    for bit in range(8):
        for a, b, ci in ((0,0,0), (255,0,1), (85,170,0), (255,255,1)):
            for case in ((a,b,ci), (a^(1<<bit),b,ci), (a,b,ci), (a,b^(1<<bit),ci)):
                vectors.append(vector(*case))
    rng = random.Random(808)
    for _ in range(1024):
        a, b, ci = rng.randrange(256), rng.randrange(256), rng.randrange(2)
        vectors.extend((vector(a,b,ci), vector(a^255,b^255,ci^1)))
    return vectors


def run(folder=None, exhaustive=True, progress=None):
    source_dir = Path(__file__).resolve().parent
    folder = Path(folder) if folder else source_dir / "build"
    cells, manifest = compile_file(source_dir / "adder8.v", "adder8", folder)
    graph_path = folder / "adder8.logic.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph_hash = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    # Both backends consume this exact graph. No resynthesis or source changes.
    sparse, baseline = place(graph, layout="sparse")
    baseline["logic_sha256"] = graph_hash
    manifest["logic_sha256"] = graph_hash
    write_json(folder / "adder8.build.json", manifest)
    write_map(folder / "baseline", "adder8", sparse)
    write_json(folder / "baseline/adder8.build.json", baseline)
    comparison = {"logic_sha256": graph_hash, "same_logic_graph": True,
                  "sparse": {key: baseline[key] for key in ("cells", "bounds", "settle_ticks")},
                  "compact": {key: manifest[key] for key in ("cells", "bounds", "settle_ticks")},
                  "cell_reduction_percent": round(100 * (1-len(cells)/len(sparse)), 2),
                  "area_reduction_percent": round(100 * (1-manifest["bounds"]["area"]/baseline["bounds"]["area"]), 2)}
    write_json(folder / "adder8.comparison.json", comparison)
    vectors = transition_vectors()
    write_json(folder / "adder8.vectors.json", {"reference": "sum=(a+b+cin)&255; cout=(a+b+cin)>>8", "vectors": vectors})
    _, report = run_vectors(cells, manifest, vectors, folder, "adder8", compressed=True)
    # Validate the old backend on the identical source graph as a comparison.
    _, baseline_report = run_vectors(sparse, baseline, [vector(*v) for v in EXAMPLES], folder / "baseline", "adder8", compressed=True)
    report["baseline_passed"] = baseline_report["passed"]
    if exhaustive:
        all_vectors = (vector(a,b,ci) for a,b,ci in product(range(256), range(256), range(2)))
        report["exhaustive"] = run_vector_batches(cells, manifest, all_vectors, folder, "adder8", progress=progress)
    report["passed"] &= report["baseline_passed"] and report.get("exhaustive", {}).get("passed", True)
    write_json(folder / "adder8.report.json", report)
    render(read_map(folder / "adder8.save.txt"), manifest, folder / "adder8.preview.png")
    render(read_map(folder / "adder8.test.save.txt"), manifest, folder / "adder8.test.preview.png", report, report["truth_table"][:8])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Полный прогон физической схемы 8-битного сумматора")
    parser.add_argument("--quick", action="store_true", help="Только переходы и граничные случаи, без полного перебора")
    args = parser.parse_args()
    report = run(exhaustive=not args.quick, progress=lambda s: print(f"exhaustive: {s['vectors']}/131072, failures={s['failure_count']}", flush=True))
    print(f"adder8: passed={report['passed']}, transition_vectors={report['vectors']}, checked={report['checked_samples']}, exhaustive={report.get('exhaustive', {}).get('vectors', 0)}")
    raise SystemExit(0 if report["passed"] else 1)
