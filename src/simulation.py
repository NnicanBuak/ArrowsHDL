"""Run the existing GraphDLC engine directly on the cell model."""
import json
import math
import os
from pathlib import Path
import subprocess

from arrowasm import MapError

ROOT = Path(__file__).resolve().parents[1]


def runner_binary():
    return ROOT / "native/target/release" / ("logic-arrows-cli.exe" if os.name == "nt" else "logic-arrows-cli")


def build_runner():
    """Build the one shared engine; projects can use their own budgets."""
    subprocess.run(["cargo", "build", "--release", "--manifest-path", str(ROOT / "native/Cargo.toml")], check=True)
    return runner_binary()


def simulate(cells, scenario, optimize_cycles=True, timeout=60, *, limits=None):
    if not math.isfinite(timeout) or timeout <= 0:
        raise MapError("Таймаут должен быть положительным")
    binary = runner_binary()
    if not binary.is_file():
        raise MapError("Ядро не собрано: cargo build --release --manifest-path ArrowsHDL/native/Cargo.toml")
    test = dict(scenario)
    if limits is not None:
        if not isinstance(limits, dict) or set(limits) - {"nodes", "ticks"}:
            raise MapError("Лимиты поддерживают только nodes и ticks")
        if any(type(v) is not int or v <= 0 for v in limits.values()):
            raise MapError("Лимиты должны быть положительными целыми числами")
        test["limits"] = dict(limits)
    request = {"cells": [{"x": x, "y": y, "type": c.type, "rotation": c.rotation, "mirrored": c.mirrored} for (x, y), c in sorted(cells.items())], "test": test, "optimize_cycles": optimize_cycles}
    graph = subprocess.run(["node", str(ROOT / "src/compile-graph.mjs")], input=json.dumps(request), capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if graph.returncode:
        raise MapError(graph.stderr.strip())
    result = subprocess.run([str(binary)], input=graph.stdout, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if result.returncode not in (0, 1):
        raise MapError(result.stderr.strip())
    return json.loads(result.stdout)
