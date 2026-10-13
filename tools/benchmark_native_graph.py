"""Measure headless graph preparation and native execution separately.

The optional cycle prefilter is applied to a temporary compiler copy. Production
sources are never modified. Compare native observations for both compiler modes.
Run after `cargo build --release --locked --manifest-path native/Cargo.toml`.
"""
import argparse
import json
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile
import time

from arrowshdl.arrowasm import Cell
from arrowshdl.mapdata import read_map
from arrowshdl.resources import GRAPH_COMPILER
from arrowshdl.simulation import runner_binary
from nodejs_wheel import node


# Iteratively remove sources and sinks from the PATH/XOR subgraph. Every real
# cycle survives, including overlapping cycles. This is a conservative filter,
# not an SCC decomposition: bridges between cycles can remain.
PREFILTER = """
  const eligible = nodes.map(n => ALLOWED_IN_CYCLE.has(n.type));
  const incoming = new Int32Array(nodes.length);
  const outgoing = new Int32Array(nodes.length);
  for (const n of nodes) if (eligible[n.nodeIdx]) {
    for (const v of n.links) if (eligible[v.nodeIdx]) {
      outgoing[n.nodeIdx]++; incoming[v.nodeIdx]++;
    }
  }
  const pending = [];
  for (const n of nodes) if (eligible[n.nodeIdx] &&
      (!incoming[n.nodeIdx] || !outgoing[n.nodeIdx])) pending.push(n.nodeIdx);
  for (let cursor = 0; cursor < pending.length; cursor++) {
    const i = pending[cursor];
    if (!eligible[i]) continue;
    eligible[i] = false;
    for (const v of nodes[i].links) if (eligible[v.nodeIdx]) {
      if (--incoming[v.nodeIdx] === 0) pending.push(v.nodeIdx);
    }
    for (const v of nodes[i].backLinks) if (eligible[v.nodeIdx]) {
      if (--outgoing[v.nodeIdx] === 0) pending.push(v.nodeIdx);
    }
  }
  for (const n of nodes) n.cycleCandidate = eligible[n.nodeIdx];
"""


def replaced(source, anchor, replacement):
    if source.count(anchor) != 1:
        raise RuntimeError(f"Compiler instrumentation anchor changed: {anchor!r}")
    return source.replace(anchor, replacement, 1)


def compiler_copy(destination, prefilter):
    source = GRAPH_COMPILER.read_text(encoding="utf-8")
    source = replaced(source, "function compile(request) {",
                      "function compile(request) {\n  const benchStart = performance.now();")
    source = replaced(source, "  const cycles = [];",
                      "  const benchLinksEnd = performance.now();\n  const cycles = [];")
    source = replaced(source, "  const resultNodes = nodes.map",
                      "  const benchCyclesEnd = performance.now();\n  const resultNodes = nodes.map")
    source = replaced(source, "    test: request.test",
                      "    _benchmark: {links_ms: benchLinksEnd - benchStart, "
                      "cycles_ms: benchCyclesEnd - benchLinksEnd, "
                      "serialize_nodes_ms: performance.now() - benchCyclesEnd},\n"
                      "    test: request.test")
    if prefilter:
        source = replaced(source, "    const manager = new CycleManager();",
                          PREFILTER + "\n    const manager = new CycleManager();")
        source = replaced(source, "return ALLOWED_IN_CYCLE.has(node.type);",
                          "return ALLOWED_IN_CYCLE.has(node.type) && node.cycleCandidate !== false;")
    destination.write_text(source, encoding="utf-8")


def compile_graph(compiler, payload):
    start = time.perf_counter()
    result = node([str(compiler)], return_completed_process=True, input=payload,
                  capture_output=True, text=True, encoding="utf-8", timeout=120)
    elapsed = (time.perf_counter() - start) * 1000
    if result.returncode:
        if "Cycle search budget exceeded" not in result.stderr:
            raise RuntimeError(result.stderr)
        request = json.loads(payload)
        request["optimize_cycles"] = False
        graph, fallback = compile_graph(compiler, json.dumps(request))
        return graph, dict(fallback=True, exhausted_search_wall_ms=elapsed,
                          fallback_wall_ms=fallback["wall_ms"], wall_ms=elapsed + fallback["wall_ms"],
                          **graph.pop("_benchmark"))
    graph = json.loads(result.stdout)
    metrics = dict(fallback=False, wall_ms=elapsed, **graph["_benchmark"])
    return graph, metrics


def native_run(payload):
    start = time.perf_counter()
    result = subprocess.run([str(runner_binary())], input=payload, capture_output=True,
                            text=True, encoding="utf-8", timeout=120)
    elapsed = (time.perf_counter() - start) * 1000
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout), elapsed


def request(cells, scenario):
    return dict(cells=[dict(x=x, y=y, type=c.type, rotation=c.rotation, mirrored=c.mirrored)
                       for (x, y), c in sorted(cells.items())],
                test=scenario, optimize_cycles=True)


def chain_case(length, busy=False, dead=0):
    cells = {(0, 0): Cell(22, 1), (length + 1, 0): Cell(23, 0)}
    cells.update({(x, 0): Cell(1, 1) for x in range(1, length + 1)})
    cells.update({(x, 10): Cell(1, 1) for x in range(dead)})
    values = [i % 2 for i in range(5000)] if busy else [1]
    hold = 4 if busy else 1_000_000
    return request(cells, dict(ticks=hold * len(values), hold_ticks=hold,
                              inputs=[dict(at=[0, 0], values=values)], expect=[],
                              observe=[[length + 1, 0]]))


def benchmark(name, req, compilers, repeat):
    payload = json.dumps(req)
    modes = {}
    reports = {}
    compiled = {}
    for mode, compiler in compilers.items():
        compile_metrics, native_ms, setup_ms = [], [], []
        for _ in range(repeat):
            graph, metrics = compile_graph(compiler, payload)
            graph.pop("_benchmark", None)
            compiled[mode] = (graph["nodes"], graph["cycles"])
            native_payload = json.dumps(graph)
            report, elapsed = native_run(native_payload)
            # One tick estimates process startup + JSON parsing + graph setup.
            # It is a separate run, not subtraction of an internal timer.
            graph["test"] = dict(ticks=1, expect=[], observe=req["test"]["observe"])
            _, setup_elapsed = native_run(json.dumps(graph))
            compile_metrics.append(metrics)
            native_ms.append(elapsed)
            setup_ms.append(setup_elapsed)
        modes[mode] = dict(
            compile={key: statistics.median(m[key] for m in compile_metrics)
                     for key in compile_metrics[0]},
            native_wall_ms=statistics.median(native_ms),
            native_one_tick_wall_ms=statistics.median(setup_ms),
            graph_json_bytes=len(native_payload.encode("utf-8")),
            optimized_cycles=report["optimized_cycles"],
        )
        reports[mode] = (report["outputs"], report["observations"], report["failure_count"])
    same = reports["baseline"] == reports["prefilter"]
    if not same:
        raise RuntimeError(f"Cycle prefilter changed observations in {name}")
    return dict(name=name, nodes=len(req["cells"]), ticks=req["test"]["ticks"],
                same_observations=same, same_compiled_graph=compiled["baseline"] == compiled["prefilter"],
                modes=modes)


def verify_prefilter(compilers, root):
    """Check every cell every tick, also against an independent grid oracle."""
    import random
    import sys
    sys.path.insert(0, str(root))
    from tests.test_simulator import oracle
    from arrowshdl.arrowasm import lower, parse
    rng = random.Random(845)
    ring = lower(parse((root / "tests/fixtures/codec/ring.l.asm").read_text()))
    cases = []
    for kind in (1, 3, 17):
        cells = dict(ring)
        if kind == 3:
            cells[1, -1] = Cell(3, 2)
        elif kind == 17:
            cells[1, 0] = Cell(17, 1)
        cases.append((f"ring-{kind}", cells))
    for case in range(4):
        kinds = [v for v in range(1, 26) if v != 20]
        cells = {(x, y): Cell(rng.choice(kinds), rng.randrange(4), bool(rng.randrange(2)))
                 for y in range(9) for x in range(9)}
        cases.append((f"random-grid-{case}", cells))
    for kind in (1, 3, 4, 5, 9, 15, 16, 17, 18, 19, 24, 25):
        cases.append((f"element-{kind}", {(0, 0): Cell(22, 1), (1, 0): Cell(kind, 1),
                      (2, 0): Cell(23, 0), (1, -1): Cell(22, 2)}))
    verified = []
    for name, cells in cases:
        points = [list(p) for p in sorted(cells)]
        scenario = dict(ticks=120, inputs=[dict(at=list(p), values=[rng.randrange(2) for _ in range(120)])
                       for p, c in sorted(cells.items()) if c.type == 22], expect=[], observe=points)
        expected = oracle(cells, dict(scenario, expect=[dict(at=p) for p in points]))
        for mode, compiler in compilers.items():
            graph, _ = compile_graph(compiler, json.dumps(request(cells, scenario)))
            graph.pop("_benchmark", None)
            report, _ = native_run(json.dumps(graph))
            actual = {tuple(row["at"]): row["values"] for row in report["observations"]}
            if actual != expected:
                raise RuntimeError(f"{mode} differs from grid oracle: {name}")
        verified.append(name)
    return dict(cases=verified, count=len(verified), ticks_per_case=120,
                all_cells_each_tick=True, passed=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--maps", nargs="*", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    cases = [(f"chain-{length}-static", chain_case(length)) for length in (256, 1024, 4096)]
    cases += [("chain-4096-busy", chain_case(4096, busy=True)),
              ("chain-256-dead-10000", chain_case(256, dead=10000))]
    many_inputs = chain_case(256)
    for i in range(128):
        many_inputs["cells"].append(dict(x=2 * i, y=20, type=22, rotation=1, mirrored=False))
        many_inputs["test"]["inputs"].append(dict(at=[2 * i, 20], values=[1]))
    cases.append(("chain-256-static-129-inputs", many_inputs))
    root = Path(__file__).resolve().parents[1]
    for fixture in ("ring",):
        from arrowshdl.arrowasm import lower, parse
        cells = lower(parse((root / f"tests/fixtures/codec/{fixture}.l.asm").read_text()))
        scenario = json.loads((root / f"tests/fixtures/codec/{fixture}.test.json").read_text())
        scenario["observe"] = [list(p) for p in sorted(cells)]
        cases.append((fixture, request(cells, scenario)))
    for path in args.maps:
        cells = read_map(path)
        # Saved maps retain their own entry points and state. This workload does
        # not represent a complete interactive project verification.
        cases.append((path.stem, request(cells, dict(ticks=4096, hold_ticks=4096,
                      expect=[], observe=[list(next(iter(sorted(cells))))]))))
    report = dict(platform=platform.platform(), python=platform.python_version(),
                  repeat=args.repeat, engine=str(runner_binary()), cases=[])
    with tempfile.TemporaryDirectory(prefix="arrowshdl-graph-bench-") as folder:
        compilers = {mode: Path(folder) / f"{mode}.mjs" for mode in ("baseline", "prefilter")}
        for mode, path in compilers.items():
            compiler_copy(path, mode == "prefilter")
        report["verification"] = verify_prefilter(compilers, root)
        print(json.dumps(report["verification"]), flush=True)
        for name, req in cases:
            row = benchmark(name, req, compilers, args.repeat)
            report["cases"].append(row)
            print(json.dumps(row), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
